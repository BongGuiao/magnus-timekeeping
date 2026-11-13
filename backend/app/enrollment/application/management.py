import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.generics.uow import GenUnitOfWork
from app.enrollment.domain.entities.enrollment import EnrollmentStatus
from app.enrollment.infrastructure.db_model import FaceEnrollmentModel, FaceEnrollmentResetModel
from app.enrollment.infrastructure.image_storage import face_reference_path
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel

logger = logging.getLogger(__name__)


class FaceSampleSummary(BaseModel):
    id: UUID
    status: EnrollmentStatus
    enrolled_at: datetime | None
    created_at: datetime
    photo_reference: str | None
    is_profile_photo: bool


class FaceEnrollmentReview(BaseModel):
    employee_id: UUID
    employee_no: str
    enrolled_count: int
    samples: list[FaceSampleSummary]


class ResetFaceEnrollmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_no: str = Field(min_length=1, max_length=30)
    sample_ids: list[UUID] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A reason for resetting face enrollment is required.")
        return value

    @field_validator("sample_ids")
    @classmethod
    def require_unique_samples(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Duplicate face sample IDs are not allowed.")
        return value


class ResetFaceEnrollmentResult(BaseModel):
    removed_count: int
    photo_reference: str | None
    cleanup_warning: str | None = None


async def lock_enrollment_employee(session: AsyncSession, employee_id: UUID) -> EmployeeModel | None:
    # Enrollment and reset must not change the same employee's samples concurrently.
    return await session.scalar(
        select(EmployeeModel)
        .where(EmployeeModel.id == employee_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def review_face_enrollments(session: AsyncSession, employee_id: UUID) -> FaceEnrollmentReview:
    employee = await session.get(EmployeeModel, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    records = (await session.scalars(
        select(FaceEnrollmentModel)
        .where(FaceEnrollmentModel.employee_id == employee_id)
        .order_by(FaceEnrollmentModel.created_at, FaceEnrollmentModel.id)
    )).all()
    samples = []
    for record in records:
        image_path = face_reference_path(record.image_path)
        samples.append(FaceSampleSummary(
            id=record.id,
            status=record.status,
            enrolled_at=record.enrolled_at,
            created_at=record.created_at,
            photo_reference=record.image_path if image_path is not None and image_path.is_file() else None,
            is_profile_photo=bool(record.image_path and record.image_path == employee.photo_reference),
        ))
    return FaceEnrollmentReview(
        employee_id=employee.id,
        employee_no=employee.employee_no,
        enrolled_count=sum(record.status == EnrollmentStatus.ENROLLED for record in records),
        samples=samples,
    )


async def reset_face_enrollments(
    uow: GenUnitOfWork, employee_id: UUID, payload: ResetFaceEnrollmentInput, actor_id: UUID,
) -> ResetFaceEnrollmentResult:
    async with uow:
        session = uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        employee = await lock_enrollment_employee(session, employee_id)
        if employee is None:
            raise HTTPException(status_code=404, detail="Employee not found.")
        if employee.employee_no != payload.employee_no:
            raise HTTPException(status_code=409, detail="Employee number does not match. Review the employee again.")
        records = (await session.scalars(
            select(FaceEnrollmentModel).where(FaceEnrollmentModel.employee_id == employee_id)
        )).all()
        if {record.id for record in records} != set(payload.sample_ids):
            raise HTTPException(
                status_code=409,
                detail="Face samples changed since they were reviewed. Refresh and review them before resetting.",
            )
        references = {record.image_path for record in records if record.image_path}
        profile_photo_cleared = bool(employee.photo_reference and employee.photo_reference in references)
        session.add(FaceEnrollmentResetModel(
            employee_id=employee.id,
            employee_no=employee.employee_no,
            reset_by=actor_id,
            sample_ids=sorted((record.id for record in records), key=str),
            sample_count=len(records),
            reason=payload.reason,
            profile_photo_cleared=profile_photo_cleared,
        ))
        # Audit and reset commit together; an unavailable audit store must block deletion.
        try:
            await session.flush()
        except SQLAlchemyError as error:
            logger.exception("Face enrollment reset audit could not be saved; reset cancelled.")
            raise HTTPException(
                status_code=503,
                detail="Face enrollment was not reset because its audit record could not be saved. "
                       "Ask an administrator to check the reset audit database migration and access.",
            ) from error
        if profile_photo_cleared:
            employee.photo_reference = None
            employee.updated_by = actor_id
            employee.updated_at = datetime.now(timezone.utc)
            employee.row_version = (employee.row_version or 0) + 1
        await session.execute(delete(FaceEnrollmentModel).where(FaceEnrollmentModel.employee_id == employee_id))
        await session.flush()
        # A reference photo can also be used by another profile; never delete a shared file.
        used_references = set((await session.scalars(
            select(EmployeeModel.photo_reference).where(EmployeeModel.photo_reference.in_(references))
        )).all())
        used_references.update((await session.scalars(
            select(FaceEnrollmentModel.image_path).where(FaceEnrollmentModel.image_path.in_(references))
        )).all())
        photo_reference = employee.photo_reference
        unused_references = references - used_references

    result = ResetFaceEnrollmentResult(removed_count=len(records), photo_reference=photo_reference)
    # Delete files only after the database reset commits; rollback must preserve the photos.
    for reference in unused_references:
        image_path = face_reference_path(reference)
        if image_path is None:
            logger.warning("Reset enrollment has an unsupported legacy photo reference; manual cleanup is required.")
            result.cleanup_warning = "Face samples were reset. A legacy reference photo needs administrator cleanup."
            continue
        try:
            image_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Face enrollment was reset, but a reference photo could not be removed.")
            result.cleanup_warning = "Face samples were reset, but photo cleanup failed. Contact an administrator."
    return result
