from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable
from uuid import UUID

from app.attendance.application.clock import ph_today, utc_now
from app.core.generics.uc_base import BaseUseCase
from app.filemaintenance.schedule.application.schedule_upload_ports import (
    ScheduleUploadFileReader,
    ScheduleUploadUnitOfWork,
)
from app.filemaintenance.schedule.application.schedule_upload_validator import (
    ScheduleUploadEvaluation,
    ScheduleUploadValidator,
)
from app.filemaintenance.schedule.domain.entities.schedule_upload import (
    EmployeeScheduleView,
    NewScheduleAssignment,
    NewScheduleUploadBatch,
    ScheduleUploadBatch,
    ScheduleUploadBatchRow,
    ScheduleUploadBatchStatus,
    ScheduleUploadValidation,
)
from app.filemaintenance.schedule.domain.schedule_upload_exceptions import (
    ScheduleUploadNoLongerApplicableError,
    ScheduleUploadNotFoundError,
    ScheduleUploadRejectedFileError,
)
from app.filemaintenance.schedule.domain.schedule_upload_rules import format_batch_no

MAX_LISTED_BATCHES = 200


@dataclass(frozen=True)
class ScheduleUploadFileInput:
    supervisor_employee_id: UUID
    uploaded_by: UUID
    file_name: str
    content: bytes


class _ScheduleUploadUseCase:
    def __init__(self, uow: ScheduleUploadUnitOfWork, clock: Callable[[], datetime] = utc_now):
        self._uow = uow
        self._clock = clock


class _FileUploadUseCase(_ScheduleUploadUseCase):
    def __init__(
        self,
        uow: ScheduleUploadUnitOfWork,
        reader: ScheduleUploadFileReader,
        clock: Callable[[], datetime] = utc_now,
    ):
        super().__init__(uow, clock)
        self._reader = reader

    async def _evaluate(self, uow: ScheduleUploadUnitOfWork, data: ScheduleUploadFileInput) -> ScheduleUploadEvaluation:
        upload = self._reader.read(data.content)
        return await ScheduleUploadValidator(uow.schedule_uploads).evaluate(
            supervisor_employee_id=data.supervisor_employee_id,
            raw_rows=upload.rows,
            today=ph_today(self._clock()),
            file_errors=upload.file_errors,
        )


class PreviewScheduleUploadUseCase(_FileUploadUseCase, BaseUseCase[ScheduleUploadValidation]):
    async def _execute(self, data: ScheduleUploadFileInput) -> ScheduleUploadValidation:
        async with self._uow as uow:
            return (await self._evaluate(uow, data)).validation


class SubmitScheduleUploadUseCase(_FileUploadUseCase, BaseUseCase[ScheduleUploadBatch]):
    async def _execute(self, data: ScheduleUploadFileInput) -> ScheduleUploadBatch:
        async with self._uow as uow:
            evaluation = await self._evaluate(uow, data)
            if not evaluation.validation.is_valid:
                raise ScheduleUploadRejectedFileError(evaluation.validation.error_count)

            repository = uow.schedule_uploads
            sequence = await repository.next_batch_sequence()
            batch_id = await repository.add_batch(
                NewScheduleUploadBatch(
                    batch_no=format_batch_no(ph_today(self._clock()).year, sequence),
                    supervisor_employee_id=data.supervisor_employee_id,
                    uploaded_by=data.uploaded_by,
                    file_name=data.file_name,
                    rows=tuple(
                        ScheduleUploadBatchRow(
                            row_no=resolved.row.row_no,
                            employee_id=resolved.employee.employee_id,
                            employee_code=resolved.employee.employee_code,
                            employee_name=resolved.employee.employee_name,
                            schedule_code=resolved.row.schedule_code,
                            assignment_type=resolved.row.assignment_type,
                            effective_from=resolved.row.effective_from,
                            effective_to=resolved.row.effective_to,
                            rest_day_pattern_code=resolved.row.rest_day_pattern_code,
                            reason=resolved.row.reason,
                        )
                        for resolved in evaluation.resolved_rows
                    ),
                )
            )
            batch = await repository.get_batch(batch_id)
            if batch is None:
                raise RuntimeError("The schedule upload batch could not be reloaded after saving.")
            company_ids = {resolved.employee.company_id for resolved in evaluation.resolved_rows}
            if await repository.schedule_approval_required(company_ids):
                return batch
            now = self._clock()
            approved = batch.approve_on_submission(now)
            return await _apply_schedule_upload(uow, batch, approved, data.uploaded_by, now)


@dataclass(frozen=True)
class ListScheduleUploadBatchesInput:
    uploaded_by: UUID | None = None
    status: ScheduleUploadBatchStatus | None = None


class ListScheduleUploadBatchesUseCase(_ScheduleUploadUseCase, BaseUseCase[list[ScheduleUploadBatch]]):
    async def _execute(self, data: ListScheduleUploadBatchesInput) -> list[ScheduleUploadBatch]:
        async with self._uow as uow:
            return await uow.schedule_uploads.list_batches(
                uploaded_by=data.uploaded_by, status=data.status, limit=MAX_LISTED_BATCHES
            )


@dataclass(frozen=True)
class GetScheduleUploadBatchInput:
    batch_id: UUID
    uploaded_by: UUID | None = None
    """When set, only a batch uploaded by this user is visible."""


class GetScheduleUploadBatchUseCase(_ScheduleUploadUseCase, BaseUseCase[ScheduleUploadBatch]):
    async def _execute(self, data: GetScheduleUploadBatchInput) -> ScheduleUploadBatch:
        async with self._uow as uow:
            batch = await uow.schedule_uploads.get_batch(data.batch_id)
        if batch is None or (data.uploaded_by is not None and batch.uploaded_by != data.uploaded_by):
            raise ScheduleUploadNotFoundError("Schedule upload batch not found.")
        return batch


@dataclass(frozen=True)
class ReviewScheduleUploadBatchInput:
    batch_id: UUID
    reviewer_id: UUID
    remarks: str | None = None


async def _load_for_update(uow: ScheduleUploadUnitOfWork, batch_id: UUID) -> ScheduleUploadBatch:
    batch = await uow.schedule_uploads.get_batch(batch_id, for_update=True)
    if batch is None:
        raise ScheduleUploadNotFoundError("Schedule upload batch not found.")
    return batch


async def _apply_schedule_upload(
    uow: ScheduleUploadUnitOfWork,
    batch: ScheduleUploadBatch,
    approved: ScheduleUploadBatch,
    actor_id: UUID,
    now: datetime,
) -> ScheduleUploadBatch:
    repository = uow.schedule_uploads
    await repository.lock_employees({row.employee_id for row in batch.rows})
    evaluation = await ScheduleUploadValidator(repository).evaluate(
        supervisor_employee_id=batch.supervisor_employee_id,
        raw_rows=[row.to_raw() for row in batch.rows],
        today=ph_today(now),
    )
    if not evaluation.validation.is_valid:
        raise ScheduleUploadNoLongerApplicableError(evaluation.validation.error_messages())

    for revision in evaluation.plan.revisions:
        await repository.revise_assignment(revision, actor_id)
    for continuation in evaluation.plan.continuations:
        source = continuation.source
        await repository.add_assignment(
            NewScheduleAssignment(
                employee_id=source.employee_id,
                schedule_template_id=source.schedule_template_id,
                rest_day_pattern_id=source.rest_day_pattern_id,
                assignment_type=source.assignment_type,
                effective_from=continuation.effective_from,
                effective_to=continuation.effective_to,
                reason=f"Resumes assignment {source.id} after schedule upload {batch.batch_no}.",
                created_by=actor_id,
                approved_by=actor_id,
                approved_at=now,
            )
        )

    assignment_ids: dict[int, UUID] = {}
    for resolved in evaluation.resolved_rows:
        assignment_id = await repository.add_assignment(
            NewScheduleAssignment(
                employee_id=resolved.employee.employee_id,
                schedule_template_id=resolved.template.id,
                rest_day_pattern_id=resolved.rest_day_pattern.id if resolved.rest_day_pattern else None,
                assignment_type=resolved.row.assignment_type,
                effective_from=resolved.row.effective_from,
                effective_to=resolved.row.effective_to,
                reason=resolved.row.reason or f"Schedule upload {batch.batch_no}",
                created_by=batch.uploaded_by,
                approved_by=actor_id,
                approved_at=now,
            )
        )
        await repository.link_batch_row(batch.id, resolved.row.row_no, assignment_id)
        assignment_ids[resolved.row.row_no] = assignment_id

    await repository.save_batch_review(approved)
    return replace(
        approved,
        rows=tuple(
            replace(row, assignment_id=assignment_ids.get(row.row_no)) for row in approved.rows
        ),
    )


class ApproveScheduleUploadBatchUseCase(_ScheduleUploadUseCase, BaseUseCase[ScheduleUploadBatch]):
    """Re-validates a pending batch and applies it atomically to employee schedules."""

    async def _execute(self, data: ReviewScheduleUploadBatchInput) -> ScheduleUploadBatch:
        async with self._uow as uow:
            batch = await _load_for_update(uow, data.batch_id)
            now = self._clock()
            approved = batch.approve(data.reviewer_id, now, (data.remarks or "").strip() or None)
            return await _apply_schedule_upload(uow, batch, approved, data.reviewer_id, now)


class RejectScheduleUploadBatchUseCase(_ScheduleUploadUseCase, BaseUseCase[ScheduleUploadBatch]):
    async def _execute(self, data: ReviewScheduleUploadBatchInput) -> ScheduleUploadBatch:
        async with self._uow as uow:
            batch = await _load_for_update(uow, data.batch_id)
            rejected = batch.reject(data.reviewer_id, self._clock(), data.remarks or "")
            await uow.schedule_uploads.save_batch_review(rejected)
            return rejected


@dataclass(frozen=True)
class CancelScheduleUploadBatchInput:
    batch_id: UUID
    user_id: UUID


class CancelScheduleUploadBatchUseCase(_ScheduleUploadUseCase, BaseUseCase[ScheduleUploadBatch]):
    async def _execute(self, data: CancelScheduleUploadBatchInput) -> ScheduleUploadBatch:
        async with self._uow as uow:
            batch = await _load_for_update(uow, data.batch_id)
            if batch.uploaded_by != data.user_id:
                raise ScheduleUploadNotFoundError("Schedule upload batch not found.")
            cancelled = batch.cancel(data.user_id, self._clock())
            await uow.schedule_uploads.save_batch_review(cancelled)
            return cancelled


@dataclass(frozen=True)
class ListMySchedulesInput:
    employee_id: UUID


class ListMySchedulesUseCase(_ScheduleUploadUseCase, BaseUseCase[list[EmployeeScheduleView]]):
    """Lists the signed-in employee's current and upcoming approved schedules."""

    async def _execute(self, data: ListMySchedulesInput) -> list[EmployeeScheduleView]:
        async with self._uow as uow:
            return await uow.employee_schedules.list_employee_schedules(
                data.employee_id, ph_today(self._clock())
            )
