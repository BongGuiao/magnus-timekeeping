from dataclasses import replace
from datetime import date
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.schedule.domain.entities.schedule_segment import ScheduleSegmentEntity
from app.filemaintenance.schedule.domain.entities.schedule_template import ScheduleTemplateEntity
from app.filemaintenance.schedule.infrastructure.db_model import (
    ScheduleSegmentModel,
    ScheduleTemplateModel,
)


class ScheduleTemplateConflictError(ValueError):
    pass


class ScheduleTemplateReferenceError(ValueError):
    pass


class ScheduleTemplateValidationError(ValueError):
    pass


class ScheduleSegmentConflictError(ValueError):
    pass


class ScheduleSegmentReferenceError(ValueError):
    pass


def _translate_segment_integrity_error(error: IntegrityError) -> NoReturn:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint_name == "uq_schedule_segments_break_slot":
        raise ScheduleSegmentConflictError("Each attendance break slot can have only one segment.") from error
    if constraint_name == "ck_schedule_segments_break_rule":
        raise ScheduleSegmentReferenceError("Break rules require a break slot, WORK sequence and positive minutes.") from error
    if constraint_name in (
        "uq_schedule_segments_template_sequence",
        "schedule_segments_schedule_template_id_segment_sequence_key",
    ):
        raise ScheduleSegmentConflictError(
            "A segment with this sequence already exists for the schedule template."
        ) from error
    if constraint_name in ("schedule_segments_schedule_template_id_fkey",):
        raise ScheduleSegmentReferenceError("The schedule template does not exist.") from error
    raise error


def _translate_integrity_error(error: IntegrityError) -> NoReturn:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint_name in (
        "uq_schedule_templates_company_code",
        "schedule_templates_company_id_schedule_code_key",
    ):
        raise ScheduleTemplateConflictError(
            "A schedule template with this code already exists for the company."
        ) from error
    if constraint_name in (
        "schedule_templates_company_id_fkey",
        "schedule_templates_holiday_calendar_id_fkey",
    ):
        raise ScheduleTemplateReferenceError(
            "The company or holiday calendar does not exist."
        ) from error
    raise error


def _validate_effective_period(effective_from: date, effective_to: date | None) -> None:
    if effective_to is not None and effective_to < effective_from:
        raise ScheduleTemplateValidationError(
            "effective_to must be on or after effective_from."
        )


async def _normalize_break_segment(
    repo, template_id: UUID, payload: dict[str, Any], segment_id: UUID | None = None,
) -> dict[str, Any]:
    if payload["segment_type"] == "WORK":
        if payload.get("break_slot") or payload.get("work_segment_sequence") or payload.get("break_minutes"):
            raise ScheduleSegmentReferenceError("WORK segments cannot have break rules.")
        return payload
    if payload.get("break_slot") is None:
        if payload.get("work_segment_sequence") is not None or payload.get("break_minutes", 0):
            raise ScheduleSegmentReferenceError("Select an attendance break slot for this break rule.")
        return payload
    work = await repo.find_one(
        ScheduleSegmentModel.schedule_template_id == template_id,
        ScheduleSegmentModel.segment_sequence == payload.get("work_segment_sequence"),
        ScheduleSegmentModel.segment_type == "WORK",
    )
    if work is None:
        raise ScheduleSegmentReferenceError("Select an existing WORK segment for the break.")
    duration = (
        work.end_day_offset * 1440
        + work.end_time.hour * 60 + work.end_time.minute
        - work.start_time.hour * 60 - work.start_time.minute
    )
    if not 0 < payload.get("break_minutes", 0) <= duration:
        raise ScheduleSegmentReferenceError("Break minutes must be positive and within the WORK duration.")
    duplicate = await repo.find_one(
        ScheduleSegmentModel.schedule_template_id == template_id,
        ScheduleSegmentModel.break_slot == payload["break_slot"],
    )
    if duplicate is not None and duplicate.id != segment_id:
        raise ScheduleSegmentConflictError("Each attendance break slot can have only one segment.")
    if payload["segment_type"] == "PAID_BREAK" and payload.get("auto_deduct"):
        raise ScheduleSegmentReferenceError("Auto deduct applies only to unpaid breaks.")
    return {
        **payload,
        "start_time": work.start_time,
        "end_time": work.end_time,
        "end_day_offset": work.end_day_offset,
        "punch_required": not payload.get("auto_deduct", False),
    }


class CreateScheduleTemplateUseCase(BaseUseCase[ScheduleTemplateEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> ScheduleTemplateEntity:
        _validate_effective_period(payload["effective_from"], payload.get("effective_to"))
        try:
            async with self.uow as uow:
                repo = uow.get_repo(ScheduleTemplateEntity, ScheduleTemplateModel)
                return await repo.add(payload)
        except IntegrityError as error:
            _translate_integrity_error(error)


class GetScheduleTemplateUseCase(BaseUseCase[ScheduleTemplateEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, template_id: UUID) -> ScheduleTemplateEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(ScheduleTemplateEntity, ScheduleTemplateModel)
            return await repo.find_one(ScheduleTemplateModel.id == template_id)


class ListScheduleTemplatesUseCase(BaseUseCase[list[ScheduleTemplateEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID | None = None,
        schedule_type: str | None = None,
        template_status: str | None = None,
        is_active: bool | None = None,
        effective_from: date | None = None,
        effective_to: date | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ScheduleTemplateEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(ScheduleTemplateEntity, ScheduleTemplateModel)
            criteria = []
            if company_id is not None:
                criteria.append(ScheduleTemplateModel.company_id == company_id)
            if schedule_type is not None:
                criteria.append(ScheduleTemplateModel.schedule_type == schedule_type)
            if template_status is not None:
                criteria.append(ScheduleTemplateModel.status == template_status)
            if is_active is not None:
                criteria.append(ScheduleTemplateModel.is_active.is_(is_active))
            if effective_from is not None:
                criteria.append(
                    or_(
                        ScheduleTemplateModel.effective_to.is_(None),
                        ScheduleTemplateModel.effective_to >= effective_from,
                    )
                )
            if effective_to is not None:
                criteria.append(ScheduleTemplateModel.effective_from <= effective_to)
            return await repo.find_all(
                *criteria,
                order_by=(ScheduleTemplateModel.company_id, ScheduleTemplateModel.schedule_code),
                offset=offset,
                limit=limit,
            )


class UpdateScheduleTemplateUseCase(BaseUseCase[ScheduleTemplateEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        template_id: UUID,
        payload: dict[str, Any],
    ) -> ScheduleTemplateEntity | None:
        try:
            async with self.uow as uow:
                repo = uow.get_repo(ScheduleTemplateEntity, ScheduleTemplateModel)
                existing = await repo.find_one(ScheduleTemplateModel.id == template_id)
                if existing is None:
                    return None

                merged = {**existing.__dict__, **payload}
                _validate_effective_period(merged["effective_from"], merged["effective_to"])
                entity = GenericMapper.to_entity(merged, ScheduleTemplateEntity)
                changes = {
                    key: value
                    for key, value in entity.__dict__.items()
                    if key not in (
                        "id",
                        "created_at",
                        "created_by",
                        "row_version",
                        "updated_at",
                        "updated_by",
                    )
                }
                updated = replace(
                    existing,
                    **changes,
                    updated_at=entity.updated_at or existing.updated_at,
                    updated_by=entity.updated_by or existing.updated_by,
                    row_version=(existing.row_version or 0) + 1,
                )
                return await repo.update(updated)
        except IntegrityError as error:
            _translate_integrity_error(error)


class CreateScheduleSegmentUseCase(BaseUseCase[ScheduleSegmentEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        template_id: UUID,
        payload: dict[str, Any],
    ) -> ScheduleSegmentEntity | None:
        try:
            async with self.uow as uow:
                template_repo = uow.get_repo(ScheduleTemplateEntity, ScheduleTemplateModel)
                template = await template_repo.find_one(ScheduleTemplateModel.id == template_id)
                if template is None:
                    return None
                segment_repo = uow.get_repo(ScheduleSegmentEntity, ScheduleSegmentModel)
                normalized = await _normalize_break_segment(segment_repo, template_id, payload)
                return await segment_repo.add({**normalized, "schedule_template_id": template_id})
        except IntegrityError as error:
            _translate_segment_integrity_error(error)


class ListScheduleSegmentsUseCase(BaseUseCase[list[ScheduleSegmentEntity] | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, template_id: UUID) -> list[ScheduleSegmentEntity] | None:
        async with self.uow as uow:
            template_repo = uow.get_repo(ScheduleTemplateEntity, ScheduleTemplateModel)
            template = await template_repo.find_one(ScheduleTemplateModel.id == template_id)
            if template is None:
                return None
            segment_repo = uow.get_repo(ScheduleSegmentEntity, ScheduleSegmentModel)
            return await segment_repo.find_all(
                ScheduleSegmentModel.schedule_template_id == template_id,
                order_by=ScheduleSegmentModel.segment_sequence,
            )


class GetScheduleSegmentUseCase(BaseUseCase[ScheduleSegmentEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        template_id: UUID,
        segment_id: UUID,
    ) -> ScheduleSegmentEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(ScheduleSegmentEntity, ScheduleSegmentModel)
            return await repo.find_one(
                ScheduleSegmentModel.id == segment_id,
                ScheduleSegmentModel.schedule_template_id == template_id,
            )


class UpdateScheduleSegmentUseCase(BaseUseCase[ScheduleSegmentEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        template_id: UUID,
        segment_id: UUID,
        payload: dict[str, Any],
    ) -> ScheduleSegmentEntity | None:
        try:
            async with self.uow as uow:
                repo = uow.get_repo(ScheduleSegmentEntity, ScheduleSegmentModel)
                existing = await repo.find_one(
                    ScheduleSegmentModel.id == segment_id,
                    ScheduleSegmentModel.schedule_template_id == template_id,
                )
                if existing is None:
                    return None
                merged = {**existing.__dict__, **payload}
                normalized = await _normalize_break_segment(repo, template_id, merged, segment_id)
                linked = await repo.find_all(
                    ScheduleSegmentModel.schedule_template_id == template_id,
                    ScheduleSegmentModel.work_segment_sequence == existing.segment_sequence,
                ) if existing.segment_type == "WORK" else []
                if linked and normalized["segment_type"] != "WORK":
                    raise ScheduleSegmentReferenceError("Remove linked break rules before changing WORK type.")
                for item in linked:
                    duration = (
                        normalized["end_day_offset"] * 1440
                        + normalized["end_time"].hour * 60 + normalized["end_time"].minute
                        - normalized["start_time"].hour * 60 - normalized["start_time"].minute
                    )
                    if item.break_minutes > duration:
                        raise ScheduleSegmentReferenceError("WORK duration cannot be shorter than a linked break allowance.")
                    await repo.update(replace(
                        item, start_time=normalized["start_time"], end_time=normalized["end_time"],
                        end_day_offset=normalized["end_day_offset"],
                        work_segment_sequence=normalized["segment_sequence"],
                    ))
                entity = GenericMapper.to_entity(
                    normalized,
                    ScheduleSegmentEntity,
                )
                return await repo.update(entity)
        except IntegrityError as error:
            _translate_segment_integrity_error(error)


class DeleteScheduleSegmentUseCase(BaseUseCase[ScheduleSegmentEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        template_id: UUID,
        segment_id: UUID,
    ) -> ScheduleSegmentEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(ScheduleSegmentEntity, ScheduleSegmentModel)
            existing = await repo.find_one(
                ScheduleSegmentModel.id == segment_id,
                ScheduleSegmentModel.schedule_template_id == template_id,
            )
            if existing is None:
                return None
            linked = await repo.find_one(
                ScheduleSegmentModel.schedule_template_id == template_id,
                ScheduleSegmentModel.work_segment_sequence == existing.segment_sequence,
            ) if existing.segment_type == "WORK" else None
            if linked is not None:
                raise ScheduleSegmentReferenceError("Remove linked break segments before deleting their WORK segment.")
            await repo.delete(existing)
            return existing
