from collections import defaultdict
from datetime import date
from typing import Any, Collection
from uuid import UUID

from sqlalchemy import insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.schedule.domain.entities.schedule_upload import (
    EmployeeScheduleView,
    ExistingScheduleAssignment,
    NewScheduleAssignment,
    NewScheduleUploadBatch,
    RestDayPatternRef,
    ScheduleTemplateRef,
    ScheduleUploadBatch,
    ScheduleUploadBatchRow,
    ScheduleUploadBatchStatus,
    ScheduleWorkSegment,
    TeamEmployee,
)
from app.filemaintenance.schedule.domain.schedule_timeline import AssignmentRevision
from app.filemaintenance.schedule.infrastructure.db_model import (
    EmployeeScheduleAssignmentModel,
    RestDayPatternModel,
    ScheduleSegmentModel,
    ScheduleTemplateModel,
)
from app.filemaintenance.schedule.infrastructure.schedule_upload_db_model import (
    ScheduleUploadBatchModel,
    ScheduleUploadBatchRowModel,
    schedule_upload_batch_no_seq,
)
from app.payroll.infrastructure.db_model import PayrollSystemParametersModel

APPROVED_ASSIGNMENT_STATUS = "APPROVED"
WORK_SEGMENT_TYPE = "WORK"


def _employee_name(values: Any) -> str:
    return values["preferred_name"] or " ".join(
        part
        for part in (values["first_name"], values["middle_name"], values["last_name"], values["suffix"])
        if part
    )


_EMPLOYEE_NAME_COLUMNS = (
    EmployeeModel.first_name,
    EmployeeModel.middle_name,
    EmployeeModel.last_name,
    EmployeeModel.suffix,
    EmployeeModel.preferred_name,
)


def _approved_assignment_conditions():
    return (
        EmployeeScheduleAssignmentModel.is_active.is_(True),
        EmployeeScheduleAssignmentModel.status == APPROVED_ASSIGNMENT_STATUS,
    )


class SqlAlchemyScheduleUploadRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def schedule_approval_required(self, company_ids: Collection[UUID]) -> bool:
        ids = set(company_ids)
        if not ids:
            return True
        rows = await self._session.execute(
            select(
                PayrollSystemParametersModel.company_id,
                PayrollSystemParametersModel.schedule_assignment_approval_required,
            ).where(PayrollSystemParametersModel.company_id.in_(ids))
        )
        settings = dict(rows.tuples())
        return any(settings.get(company_id, True) for company_id in ids)

    async def find_team_employees(
        self,
        supervisor_employee_id: UUID,
        employee_codes: Collection[str],
        on_date: date,
    ) -> list[TeamEmployee]:
        assignment = EmploymentAssignmentModel
        rows = await self._session.execute(
            select(
                EmployeeModel.id.label("employee_id"),
                EmployeeModel.employee_no.label("employee_code"),
                assignment.company_id,
                *_EMPLOYEE_NAME_COLUMNS,
            )
            .join(assignment, assignment.employee_id == EmployeeModel.id)
            .where(
                EmployeeModel.employee_no.in_(list(employee_codes)),
                EmployeeModel.is_active.is_(True),
                EmployeeModel.record_status == "ACTIVE",
                assignment.supervisor_employee_id == supervisor_employee_id,
                assignment.is_active.is_(True),
                assignment.status == "ACTIVE",
                assignment.effective_from <= on_date,
                or_(assignment.effective_to.is_(None), assignment.effective_to >= on_date),
                or_(assignment.separation_date.is_(None), assignment.separation_date >= on_date),
            )
            .distinct()
        )
        return [
            TeamEmployee(
                employee_id=row["employee_id"],
                employee_code=row["employee_code"],
                employee_name=_employee_name(row),
                company_id=row["company_id"],
            )
            for row in rows.mappings()
        ]

    async def find_schedule_templates(
        self,
        company_ids: Collection[UUID],
        schedule_codes: Collection[str],
    ) -> list[ScheduleTemplateRef]:
        if not company_ids or not schedule_codes:
            return []
        templates = await self._session.scalars(
            select(ScheduleTemplateModel).where(
                ScheduleTemplateModel.company_id.in_(list(company_ids)),
                ScheduleTemplateModel.schedule_code.in_(list(schedule_codes)),
            )
        )
        return [
            ScheduleTemplateRef(
                id=template.id,
                company_id=template.company_id,
                schedule_code=template.schedule_code,
                schedule_name=template.schedule_name,
                status=template.status,
                is_active=template.is_active,
                effective_from=template.effective_from,
                effective_to=template.effective_to,
            )
            for template in templates
        ]

    async def find_rest_day_patterns(self, pattern_codes: Collection[str]) -> list[RestDayPatternRef]:
        patterns = await self._session.scalars(
            select(RestDayPatternModel).where(RestDayPatternModel.pattern_code.in_(list(pattern_codes)))
        )
        return [
            RestDayPatternRef(
                id=pattern.id,
                pattern_code=pattern.pattern_code,
                pattern_name=pattern.pattern_name,
                is_active=pattern.is_active,
            )
            for pattern in patterns
        ]

    async def list_approved_assignments(
        self, employee_ids: Collection[UUID]
    ) -> list[ExistingScheduleAssignment]:
        if not employee_ids:
            return []
        rows = await self._session.execute(
            select(EmployeeScheduleAssignmentModel, ScheduleTemplateModel.schedule_code)
            .join(
                ScheduleTemplateModel,
                ScheduleTemplateModel.id == EmployeeScheduleAssignmentModel.schedule_template_id,
            )
            .where(
                EmployeeScheduleAssignmentModel.employee_id.in_(list(employee_ids)),
                *_approved_assignment_conditions(),
            )
            .order_by(EmployeeScheduleAssignmentModel.effective_from)
        )
        return [
            ExistingScheduleAssignment(
                id=model.id,
                employee_id=model.employee_id,
                schedule_template_id=model.schedule_template_id,
                schedule_code=schedule_code,
                rest_day_pattern_id=model.rest_day_pattern_id,
                assignment_type=model.assignment_type,
                effective_from=model.effective_from,
                effective_to=model.effective_to,
            )
            for model, schedule_code in rows.all()
        ]

    async def next_batch_sequence(self) -> int:
        return int(await self._session.scalar(select(schedule_upload_batch_no_seq.next_value())))

    async def add_batch(self, batch: NewScheduleUploadBatch) -> UUID:
        model = ScheduleUploadBatchModel(
            batch_no=batch.batch_no,
            supervisor_employee_id=batch.supervisor_employee_id,
            uploaded_by=batch.uploaded_by,
            file_name=batch.file_name,
            row_count=len(batch.rows),
            status=ScheduleUploadBatchStatus.PENDING_APPROVAL.value,
        )
        self._session.add(model)
        await self._session.flush()
        self._session.add_all(
            ScheduleUploadBatchRowModel(
                batch_id=model.id,
                row_no=row.row_no,
                employee_id=row.employee_id,
                employee_code=row.employee_code,
                employee_name=row.employee_name,
                schedule_code=row.schedule_code,
                assignment_type=row.assignment_type,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                rest_day_pattern_code=row.rest_day_pattern_code,
                reason=row.reason,
            )
            for row in batch.rows
        )
        await self._session.flush()
        return model.id

    def _batch_query(self):
        return select(ScheduleUploadBatchModel, *_EMPLOYEE_NAME_COLUMNS).join(
            EmployeeModel, EmployeeModel.id == ScheduleUploadBatchModel.supervisor_employee_id
        )

    @staticmethod
    def _to_batch(row: Any, rows: tuple[ScheduleUploadBatchRow, ...] = ()) -> ScheduleUploadBatch:
        model: ScheduleUploadBatchModel = row[0]
        return ScheduleUploadBatch(
            id=model.id,
            batch_no=model.batch_no,
            supervisor_employee_id=model.supervisor_employee_id,
            supervisor_name=_employee_name(row._mapping),
            uploaded_by=model.uploaded_by,
            file_name=model.file_name,
            row_count=model.row_count,
            status=ScheduleUploadBatchStatus(model.status),
            submitted_at=model.submitted_at,
            reviewed_by=model.reviewed_by,
            reviewed_at=model.reviewed_at,
            review_remarks=model.review_remarks,
            rows=rows,
        )

    async def get_batch(self, batch_id: UUID, *, for_update: bool = False) -> ScheduleUploadBatch | None:
        query = self._batch_query().where(ScheduleUploadBatchModel.id == batch_id)
        if for_update:
            query = query.with_for_update(of=ScheduleUploadBatchModel)
        row = (await self._session.execute(query)).first()
        if row is None:
            return None
        row_models = await self._session.scalars(
            select(ScheduleUploadBatchRowModel)
            .where(ScheduleUploadBatchRowModel.batch_id == batch_id)
            .order_by(ScheduleUploadBatchRowModel.row_no)
        )
        return self._to_batch(
            row,
            tuple(
                ScheduleUploadBatchRow(
                    row_no=model.row_no,
                    employee_id=model.employee_id,
                    employee_code=model.employee_code,
                    employee_name=model.employee_name,
                    schedule_code=model.schedule_code,
                    assignment_type=model.assignment_type,
                    effective_from=model.effective_from,
                    effective_to=model.effective_to,
                    rest_day_pattern_code=model.rest_day_pattern_code,
                    reason=model.reason,
                    assignment_id=model.employee_schedule_assignment_id,
                )
                for model in row_models
            ),
        )

    async def list_batches(
        self,
        *,
        uploaded_by: UUID | None,
        status: ScheduleUploadBatchStatus | None,
        limit: int,
    ) -> list[ScheduleUploadBatch]:
        query = self._batch_query()
        if uploaded_by is not None:
            query = query.where(ScheduleUploadBatchModel.uploaded_by == uploaded_by)
        if status is not None:
            query = query.where(ScheduleUploadBatchModel.status == status.value)
        rows = await self._session.execute(
            query.order_by(ScheduleUploadBatchModel.submitted_at.desc()).limit(limit)
        )
        return [self._to_batch(row) for row in rows.all()]

    async def save_batch_review(self, batch: ScheduleUploadBatch) -> None:
        await self._session.execute(
            update(ScheduleUploadBatchModel)
            .where(ScheduleUploadBatchModel.id == batch.id)
            .values(
                status=batch.status.value,
                reviewed_by=batch.reviewed_by,
                reviewed_at=batch.reviewed_at,
                review_remarks=batch.review_remarks,
            )
        )

    async def lock_employees(self, employee_ids: Collection[UUID]) -> None:
        if employee_ids:
            await self._session.execute(
                select(EmployeeModel.id)
                .where(EmployeeModel.id.in_(list(employee_ids)))
                .order_by(EmployeeModel.id)
                .with_for_update()
            )

    async def revise_assignment(self, revision: AssignmentRevision, actor_id: UUID) -> None:
        values: dict[str, Any] = {
            "updated_by": actor_id,
            "row_version": EmployeeScheduleAssignmentModel.row_version + 1,
        }
        if revision.retire:
            values["is_active"] = False
        else:
            values["effective_from"] = revision.effective_from
            values["effective_to"] = revision.effective_to
        await self._session.execute(
            update(EmployeeScheduleAssignmentModel)
            .where(EmployeeScheduleAssignmentModel.id == revision.assignment.id)
            .values(**values)
        )

    async def add_assignment(self, assignment: NewScheduleAssignment) -> UUID:
        return await self._session.scalar(
            insert(EmployeeScheduleAssignmentModel)
            .values(
                employee_id=assignment.employee_id,
                schedule_template_id=assignment.schedule_template_id,
                rest_day_pattern_id=assignment.rest_day_pattern_id,
                assignment_type=assignment.assignment_type,
                effective_from=assignment.effective_from,
                effective_to=assignment.effective_to,
                reason=assignment.reason,
                status=APPROVED_ASSIGNMENT_STATUS,
                approved_by=assignment.approved_by,
                approved_at=assignment.approved_at,
                created_by=assignment.created_by,
                updated_by=assignment.approved_by,
            )
            .returning(EmployeeScheduleAssignmentModel.id)
        )

    async def link_batch_row(self, batch_id: UUID, row_no: int, assignment_id: UUID) -> None:
        await self._session.execute(
            update(ScheduleUploadBatchRowModel)
            .where(
                ScheduleUploadBatchRowModel.batch_id == batch_id,
                ScheduleUploadBatchRowModel.row_no == row_no,
            )
            .values(employee_schedule_assignment_id=assignment_id)
        )


class SqlAlchemyEmployeeScheduleReader:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_employee_schedules(self, employee_id: UUID, from_date: date) -> list[EmployeeScheduleView]:
        rows = (
            await self._session.execute(
                select(
                    EmployeeScheduleAssignmentModel,
                    ScheduleTemplateModel.schedule_code,
                    ScheduleTemplateModel.schedule_name,
                    ScheduleTemplateModel.schedule_type,
                    RestDayPatternModel.pattern_code,
                    RestDayPatternModel.pattern_name,
                )
                .join(
                    ScheduleTemplateModel,
                    ScheduleTemplateModel.id == EmployeeScheduleAssignmentModel.schedule_template_id,
                )
                .outerjoin(
                    RestDayPatternModel,
                    RestDayPatternModel.id == EmployeeScheduleAssignmentModel.rest_day_pattern_id,
                )
                .where(
                    EmployeeScheduleAssignmentModel.employee_id == employee_id,
                    *_approved_assignment_conditions(),
                    or_(
                        EmployeeScheduleAssignmentModel.effective_to.is_(None),
                        EmployeeScheduleAssignmentModel.effective_to >= from_date,
                    ),
                )
                .order_by(EmployeeScheduleAssignmentModel.effective_from)
            )
        ).all()

        template_ids = {row[0].schedule_template_id for row in rows}
        segments_by_template: dict[UUID, list[ScheduleWorkSegment]] = defaultdict(list)
        if template_ids:
            segments = await self._session.scalars(
                select(ScheduleSegmentModel)
                .where(
                    ScheduleSegmentModel.schedule_template_id.in_(template_ids),
                    ScheduleSegmentModel.segment_type == WORK_SEGMENT_TYPE,
                )
                .order_by(ScheduleSegmentModel.schedule_template_id, ScheduleSegmentModel.segment_sequence)
            )
            for segment in segments:
                segments_by_template[segment.schedule_template_id].append(
                    ScheduleWorkSegment(segment.start_time, segment.end_time, segment.end_day_offset)
                )

        return [
            EmployeeScheduleView(
                assignment_id=assignment.id,
                schedule_code=schedule_code,
                schedule_name=schedule_name,
                schedule_type=schedule_type,
                assignment_type=assignment.assignment_type,
                effective_from=assignment.effective_from,
                effective_to=assignment.effective_to,
                rest_day_pattern_code=pattern_code,
                rest_day_pattern_name=pattern_name,
                approved_at=assignment.approved_at,
                work_segments=tuple(segments_by_template.get(assignment.schedule_template_id, ())),
            )
            for assignment, schedule_code, schedule_name, schedule_type, pattern_code, pattern_name in rows
        ]


class SqlAlchemyScheduleUploadUnitOfWork:
    """Adapts the generic unit of work to the schedule upload unit-of-work port."""

    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow
        self.schedule_uploads: SqlAlchemyScheduleUploadRepository
        self.employee_schedules: SqlAlchemyEmployeeScheduleReader

    async def __aenter__(self) -> "SqlAlchemyScheduleUploadUnitOfWork":
        active = await self._uow.__aenter__()
        self.schedule_uploads = SqlAlchemyScheduleUploadRepository(active.session)
        self.employee_schedules = SqlAlchemyEmployeeScheduleReader(active.session)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._uow.__aexit__(exc_type, exc_val, exc_tb)
