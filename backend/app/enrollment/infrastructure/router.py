from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from elasticsearch import AsyncElasticsearch
from sqlalchemy import exists, or_, select

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, require_role
from app.auth.domain.entities.user import Role
from app.enrollment.application.use_case import EnrollFaceInputDTO, EnrollFaceOutputDTO, EnrollFaceUseCase
from app.enrollment.application.management import (
    FaceEnrollmentReview, ResetFaceEnrollmentInput, ResetFaceEnrollmentResult,
    reset_face_enrollments, review_face_enrollments,
)
from app.enrollment.infrastructure.dependencies import get_enroll_face_use_case
from app.enrollment.infrastructure.db_model import FaceEnrollmentModel
from app.enrollment.infrastructure.image_storage import face_image_path, face_image_reference
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel

router = APIRouter(prefix="/enrollment", tags=["Face Enrollment"])
MAX_ENROLLMENT_IMAGE_BYTES = 10 * 1024 * 1024


class EnrollmentResponseSchema(BaseModel):
    status: str
    enrolled_at: str
    sample_count: int
    photo_reference: str | None = None


async def require_face_management_access(
    claims: dict = Depends(require_role([Role.ADMIN])),
    use_case: GetCurrentAuthorizationUseCase = Depends(get_current_authorization_use_case),
) -> dict:
    try:
        user_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=401, detail="Invalid user identity in authentication token.") from error
    authorization = await use_case.execute(user_id)
    if "HR_ADMIN" not in authorization.role_codes or "employees.manage" not in authorization.permission_codes:
        raise HTTPException(status_code=403, detail="Reviewing and resetting face samples requires HR_ADMIN and employee management access.")
    return claims


@router.get("/employees/{employee_id}/samples", response_model=ResponseEnvelope[FaceEnrollmentReview])
async def review_employee_face_samples(
    employee_id: UUID,
    response: Response,
    claims: dict = Depends(require_face_management_access),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        result = await review_face_enrollments(uow.session, employee_id)
    response.headers["Cache-Control"] = "no-store"
    return ResponseEnvelope(data=result)


@router.post("/employees/{employee_id}/reset", response_model=ResponseEnvelope[ResetFaceEnrollmentResult])
async def reset_employee_face_samples(
    employee_id: UUID,
    payload: ResetFaceEnrollmentInput,
    response: Response,
    claims: dict = Depends(require_face_management_access),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = UUID(str(claims["sub"]))
    result = await reset_face_enrollments(uow, employee_id, payload, actor_id)
    await log_entity_action(
        es_client, user_id=actor_id, action="DELETE", resource="face_enrollment", resource_id=employee_id,
        before={"sample_count": result.removed_count, "sample_ids": [str(value) for value in payload.sample_ids]},
        after={"sample_count": 0, "reason": payload.reason},
    )
    response.headers["Cache-Control"] = "no-store"
    return ResponseEnvelope(data=result)


@router.get("/photos/{filename}", include_in_schema=False)
async def get_enrollment_photo(
    filename: str,
    claims: dict = Depends(require_role([Role.ADMIN])),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    if not filename.endswith(".jpg"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment photo not found.")
    try:
        image_id = UUID(filename[:-4])
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment photo not found.") from error
    image_path = face_image_path(image_id)
    if not image_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment photo not found.")
    reference = face_image_reference(image_id)
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        referenced = await uow.session.scalar(select(or_(
            exists().where(FaceEnrollmentModel.image_path == reference),
            exists().where(EmployeeModel.photo_reference == reference),
        )))
    if not referenced:
        raise HTTPException(status_code=404, detail="Enrollment photo not found.")
    return FileResponse(
        image_path, media_type="image/jpeg", filename=filename, headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/face",
    response_model=ResponseEnvelope[EnrollmentResponseSchema],
    status_code=status.HTTP_201_CREATED,
)
async def enroll_face(
    file: UploadFile = File(...),
    employee_id: UUID = Form(...),
    claims: dict = Depends(require_role([Role.ADMIN])),
    use_case: EnrollFaceUseCase = Depends(get_enroll_face_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    image_bytes = await file.read(MAX_ENROLLMENT_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enrollment photo is empty.")
    if len(image_bytes) > MAX_ENROLLMENT_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Enrollment photo exceeds the 10 MB limit.",
        )
    try:
        acting_user_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in authentication token.",
        ) from error
    input_dto = EnrollFaceInputDTO(
        employee_id=employee_id,
        image_bytes=image_bytes,
        acting_user_id=acting_user_id,
    )
    result: EnrollFaceOutputDTO = await use_case.execute(input_dto)
    await log_entity_action(
        es_client,
        user_id=acting_user_id,
        action="CREATE",
        resource="face_enrollment",
        resource_id=input_dto.employee_id,
        after={
            "status": result.status,
            "enrolled_at": result.enrolled_at,
            "sample_count": result.sample_count,
        },
    )

    return ResponseEnvelope[EnrollmentResponseSchema](
        data=EnrollmentResponseSchema(
            status=result.status,
            enrolled_at=result.enrolled_at,
            sample_count=result.sample_count,
            photo_reference=result.photo_reference,
        )
    )
