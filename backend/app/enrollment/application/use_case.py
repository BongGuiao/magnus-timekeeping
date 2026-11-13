import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.face_recognition_service import face_encoding_norm
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel
from app.enrollment.infrastructure.db_model import FaceEnrollmentModel, FaceEnrollmentOverrideModel
from app.enrollment.domain.entities.enrollment import EnrollmentStatus, FaceEnrollmentEntity
from app.enrollment.application.management import lock_enrollment_employee
from app.enrollment.infrastructure.image_storage import (
    face_image_path,
    face_image_reference,
    prepare_face_reference_image,
)

MAX_SAMPLES_PER_EMPLOYEE = 5
MAX_FACE_COMPARISON_CANDIDATES = 10000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SimilarityOverride:
    """HR Admin confirmation that the capture is not any of the listed similar employees."""
    conflicting_employee_nos: frozenset[str]
    reason: str


@dataclass(frozen=True)
class SimilarEmployee:
    employee_id: UUID
    employee_no: str
    distance: float


class FaceSimilarityConflict(ValueError):
    def __init__(self, message: str, conflicts: list[SimilarEmployee], threshold: float):
        super().__init__(message)
        self.conflicts = conflicts
        self.threshold = threshold


class EnrollmentAuditUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class EnrollFaceInputDTO:
    employee_id: UUID
    image_bytes: bytes
    acting_user_id: UUID | None = None
    similarity_override: SimilarityOverride | None = field(default=None)


@dataclass(frozen=True)
class EnrollFaceOutputDTO:
    status: str
    enrolled_at: str
    sample_count: int
    photo_reference: str | None = None


class EnrollFaceUseCase(BaseUseCase[EnrollFaceOutputDTO]):
    def __init__(self, uow: GenUnitOfWork, face_encoding_service):
        self.uow = uow
        self.face_encoding_service = face_encoding_service

    async def _execute(self, input_dto: EnrollFaceInputDTO) -> EnrollFaceOutputDTO:
        # Run outside the DB transaction since this is CPU-bound, not I/O-bound
        encoding = self.face_encoding_service.extract_face_encoding(input_dto.image_bytes)
        reference_image = prepare_face_reference_image(input_dto.image_bytes)
        enrolled_at = datetime.now(timezone.utc)
        image_id = uuid4()
        image_path = face_image_path(image_id)
        image_reference = face_image_reference(image_id)
        image_saved = False

        try:
            async with self.uow as uow:
                if uow.session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                await lock_enrollment_employee(uow.session, input_dto.employee_id)
                employee_repo = uow.get_repo(EmployeeEntity, EmployeeModel)
                employee = await employee_repo.find_one(EmployeeModel.id == input_dto.employee_id)
                if employee is None or not employee.is_active or employee.record_status != "ACTIVE":
                    raise ValueError("An active employee profile is required for face enrollment.")

                repo = uow.get_repo(FaceEnrollmentEntity, FaceEnrollmentModel)
                existing = await repo.find_all(
                    FaceEnrollmentModel.employee_id == input_dto.employee_id,
                    order_by=(FaceEnrollmentModel.created_at.asc(), FaceEnrollmentModel.id.asc()),
                    limit=MAX_SAMPLES_PER_EMPLOYEE + 1,
                )

                if len(existing) >= MAX_SAMPLES_PER_EMPLOYEE:
                    raise ValueError(f"This employee already has the maximum of {MAX_SAMPLES_PER_EMPLOYEE} face samples.")

                conflicts, source_approval = await self._ensure_face_belongs_to_employee(
                    uow, repo, input_dto.employee_id, encoding, input_dto.similarity_override,
                )

                image_path.parent.mkdir(parents=True, exist_ok=True)
                with image_path.open("xb") as image_file:
                    image_saved = True
                    image_file.write(reference_image)

                saved = await repo.add(
                    FaceEnrollmentEntity(
                        employee_id=input_dto.employee_id,
                        face_encoding=encoding,
                        status=EnrollmentStatus.ENROLLED,
                        image_path=image_reference,
                        enrolled_at=enrolled_at,
                        created_by=input_dto.acting_user_id,
                        updated_by=input_dto.acting_user_id,
                    )
                )

                if conflicts:
                    await self._record_override(uow, saved.id, employee, conflicts, input_dto, source_approval)

                employee_photo_reference = employee.photo_reference
                if not existing:
                    await employee_repo.update(
                        replace(
                            employee,
                            photo_reference=image_reference,
                            updated_by=input_dto.acting_user_id,
                            updated_at=enrolled_at,
                            row_version=(employee.row_version or 0) + 1,
                        )
                    )
                    employee_photo_reference = image_reference

                return EnrollFaceOutputDTO(
                    status=saved.status.value,
                    enrolled_at=saved.enrolled_at.isoformat() if saved.enrolled_at else enrolled_at.isoformat(),
                    sample_count=len(existing) + 1,
                    photo_reference=employee_photo_reference,
                )
        except Exception:
            if image_saved:
                image_path.unlink(missing_ok=True)
            raise

    async def _ensure_face_belongs_to_employee(
        self, uow, repo, employee_id: UUID, encoding: list[float],
        similarity_override: SimilarityOverride | None = None,
    ) -> tuple[list[SimilarEmployee], FaceEnrollmentOverrideModel | None]:
        """Rejects a sample that differs from the employee's enrolled face or resembles another employee.

        Own-sample consistency uses match_threshold(); similarity to other employees is flagged at the
        stricter enrollment_conflict_threshold(). Returns conflicts and the original approval when a
        clear own-face match can continue it.
        """
        candidate_norm = face_encoding_norm(encoding)
        threshold = self.face_encoding_service.match_threshold()
        conflict_threshold = self.face_encoding_service.enrollment_conflict_threshold()
        enrolled = await repo.find_all(
            FaceEnrollmentModel.status == EnrollmentStatus.ENROLLED,
            limit=MAX_FACE_COMPARISON_CANDIDATES,
        )
        own_samples = [item for item in enrolled if item.employee_id == employee_id and item.face_encoding]
        own = [item.face_encoding for item in own_samples]
        others = [item for item in enrolled if item.employee_id != employee_id and item.face_encoding]

        own_distances = self.face_encoding_service.face_distances(encoding, own) if own else []
        if own:
            if max(own_distances) > threshold:
                raise ValueError(
                    "This face does not match the employee's existing enrolled samples. "
                    "Use a photo of the same person, or remove the existing samples before re-enrolling."
                )

        if not others:
            return [], None
        other_distances = self.face_encoding_service.face_distances(
            encoding, [item.face_encoding for item in others]
        )
        nearest: dict[UUID, tuple[FaceEnrollmentEntity, float]] = {}
        for item, distance in zip(others, other_distances):
            previous = nearest.get(item.employee_id)
            if previous is None or distance < previous[1]:
                nearest[item.employee_id] = (item, distance)
        similar = sorted(
            (pair for pair in nearest.values() if pair[1] <= conflict_threshold),
            key=lambda pair: pair[1],
        )
        if not similar:
            return [], None

        source_approval = None
        if own_samples and similarity_override is None:
            match = self.face_encoding_service.find_best_match(
                encoding, [(item.employee_id, item.face_encoding) for item in own_samples + others],
                threshold=threshold,
            )
            # Even with a zero configured margin, a tie is not a clear own-face match.
            if match is not None and match[0] == employee_id and match[1] < min(other_distances):
                source_approval = await self._find_active_hr_approval(uow, employee_id, own_samples)

        employee_repo = uow.get_repo(EmployeeEntity, EmployeeModel)
        conflicts = []
        for sample, distance in similar:
            other_employee = await employee_repo.find_one(EmployeeModel.id == sample.employee_id)
            conflict = SimilarEmployee(
                sample.employee_id, other_employee.employee_no if other_employee else str(sample.employee_id),
                float(distance),
            )
            conflicts.append(conflict)
            if source_approval is None:
                logger.warning(
                    "FACE_ENROLLMENT_CONFLICT requested_employee_id=%s matched_employee_id=%s "
                    "matched_employee_no=%s matched_sample_id=%s distance=%r threshold=%r "
                    "candidate_norm=%r matched_norm=%r override_requested=%s",
                    employee_id, conflict.employee_id, conflict.employee_no, sample.id, conflict.distance,
                    conflict_threshold,
                    candidate_norm, face_encoding_norm(sample.face_encoding, source="Stored face"),
                    similarity_override is not None,
                )
        if source_approval is not None:
            logger.info(
                "FACE_ENROLLMENT_CONTINUATION employee_id=%s source_override_id=%s "
                "own_distance=%r nearest_other_distance=%r",
                employee_id, source_approval.id, min(own_distances), min(other_distances),
            )
            return conflicts, source_approval
        numbers = ", ".join(conflict.employee_no for conflict in conflicts)
        label = f"another employee ({numbers})" if len(conflicts) == 1 else f"other employees ({numbers})"
        detail = f"Closest distance {conflicts[0].distance:.3f}; limit {conflict_threshold:.3f}."
        if similarity_override is None:
            raise FaceSimilarityConflict(
                f"This capture is too similar to an enrolled face for {label}. "
                f"No sample was saved. {detail} An HR Admin can confirm in person that they are "
                "different people and approve the enrollment. Similarity does not confirm that they are the same person.",
                conflicts, conflict_threshold,
            )
        if similarity_override.conflicting_employee_nos != {conflict.employee_no for conflict in conflicts}:
            raise FaceSimilarityConflict(
                f"The similar employees changed; this capture now resembles {label}. No sample was saved. "
                f"{detail} Review and approve the current list.",
                conflicts, conflict_threshold,
            )
        return conflicts, None

    async def _find_active_hr_approval(
        self, uow: GenUnitOfWork, employee_id: UUID, own_samples: list[FaceEnrollmentEntity],
    ) -> FaceEnrollmentOverrideModel | None:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        try:
            # The employee lock protects these compared samples from reset until the save commits.
            return await uow.session.scalar(
                select(FaceEnrollmentOverrideModel).where(
                    FaceEnrollmentOverrideModel.employee_id == employee_id,
                    FaceEnrollmentOverrideModel.enrollment_id.in_([sample.id for sample in own_samples]),
                    FaceEnrollmentOverrideModel.source_override_id.is_(None),
                ).order_by(
                    FaceEnrollmentOverrideModel.approved_at.desc(), FaceEnrollmentOverrideModel.id.asc(),
                ).limit(1)
            )
        except SQLAlchemyError as error:
            logger.exception("Could not verify an active HR face approval for employee %s.", employee_id)
            raise EnrollmentAuditUnavailable(
                "The saved HR approval could not be verified. No sample was saved. "
                "Ask an administrator to apply the face enrollment approval continuation database migration."
            ) from error

    async def _record_override(
        self, uow, enrollment_id: UUID, employee: EmployeeEntity,
        conflicts: list[SimilarEmployee], input_dto: EnrollFaceInputDTO,
        source_approval: FaceEnrollmentOverrideModel | None = None,
    ) -> None:
        override = input_dto.similarity_override
        if input_dto.acting_user_id is None:
            raise ValueError("An HR Admin approval is required to save a similar face.")
        if source_approval is not None:
            reason = (
                f"Automatically verified using HR approval {source_approval.id}: the capture matched existing "
                "samples and the employee's own identity won by the required margin. No new in-person approval."
            )
            approved_by = source_approval.approved_by
        elif override is not None:
            reason = override.reason
            approved_by = input_dto.acting_user_id
        else:
            raise ValueError("An HR Admin approval is required to save a similar face.")
        uow.session.add(FaceEnrollmentOverrideModel(
            enrollment_id=enrollment_id,
            source_override_id=source_approval.id if source_approval is not None else None,
            employee_id=employee.id,
            employee_no=employee.employee_no,
            conflicting_employee_ids=[conflict.employee_id for conflict in conflicts],
            conflicting_employee_nos=[conflict.employee_no for conflict in conflicts],
            closest_distance=conflicts[0].distance,
            threshold=self.face_encoding_service.enrollment_conflict_threshold(),
            reason=reason,
            approved_by=approved_by,
        ))
        # The approval audit commits with the sample; without it nothing is saved.
        try:
            await uow.session.flush()
        except SQLAlchemyError as error:
            raise EnrollmentAuditUnavailable(
                "The face was not saved because the approval audit could not be recorded. "
                "Ask an administrator to apply the face enrollment approval database migrations."
            ) from error
