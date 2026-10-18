from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel
from app.enrollment.infrastructure.db_model import FaceEnrollmentModel
from app.enrollment.domain.entities.enrollment import EnrollmentStatus, FaceEnrollmentEntity
from app.enrollment.infrastructure.image_storage import (
    face_image_path,
    face_image_reference,
    prepare_face_reference_image,
)

MAX_SAMPLES_PER_EMPLOYEE = 5
MAX_FACE_COMPARISON_CANDIDATES = 10000


@dataclass(frozen=True)
class EnrollFaceInputDTO:
    employee_id: UUID
    image_bytes: bytes
    acting_user_id: UUID | None = None


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
                repo = uow.get_repo(FaceEnrollmentEntity, FaceEnrollmentModel)
                existing = await repo.find_all(
                    FaceEnrollmentModel.employee_id == input_dto.employee_id,
                    order_by=(FaceEnrollmentModel.created_at.asc(), FaceEnrollmentModel.id.asc()),
                    limit=MAX_SAMPLES_PER_EMPLOYEE + 1,
                )

                if len(existing) >= MAX_SAMPLES_PER_EMPLOYEE:
                    raise ValueError(f"This employee already has the maximum of {MAX_SAMPLES_PER_EMPLOYEE} face samples.")

                await self._ensure_face_belongs_to_employee(uow, repo, input_dto.employee_id, encoding)

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

                employee_repo = uow.get_repo(EmployeeEntity, EmployeeModel)
                employee = await employee_repo.find_one(EmployeeModel.id == input_dto.employee_id)
                if employee is None or not employee.is_active or employee.record_status != "ACTIVE":
                    raise ValueError("An active employee profile is required for face enrollment.")

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

    async def _ensure_face_belongs_to_employee(self, uow, repo, employee_id: UUID, encoding: list[float]) -> None:
        """Rejects a sample that differs from the employee's enrolled face or matches another employee."""
        threshold = self.face_encoding_service.match_threshold()
        enrolled = await repo.find_all(
            FaceEnrollmentModel.status == EnrollmentStatus.ENROLLED,
            limit=MAX_FACE_COMPARISON_CANDIDATES,
        )
        own = [item.face_encoding for item in enrolled if item.employee_id == employee_id and item.face_encoding]
        others = [item for item in enrolled if item.employee_id != employee_id and item.face_encoding]

        if own:
            own_distances = self.face_encoding_service.face_distances(encoding, own)
            if max(own_distances) > threshold:
                raise ValueError(
                    "This face does not match the employee's existing enrolled samples. "
                    "Use a photo of the same person, or remove the existing samples before re-enrolling."
                )

        if others:
            other_distances = self.face_encoding_service.face_distances(
                encoding, [item.face_encoding for item in others]
            )
            closest_index = min(range(len(other_distances)), key=other_distances.__getitem__)
            if other_distances[closest_index] <= threshold:
                employee_repo = uow.get_repo(EmployeeEntity, EmployeeModel)
                other_employee = await employee_repo.find_one(EmployeeModel.id == others[closest_index].employee_id)
                label = other_employee.employee_no if other_employee else "another employee"
                raise ValueError(f"This face is already enrolled for another employee ({label}).")
