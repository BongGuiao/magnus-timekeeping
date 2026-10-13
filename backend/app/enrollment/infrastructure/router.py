from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from elasticsearch import AsyncElasticsearch

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import require_role
from app.auth.domain.entities.user import Role
from app.enrollment.application.use_case import EnrollFaceInputDTO, EnrollFaceOutputDTO, EnrollFaceUseCase
from app.enrollment.infrastructure.dependencies import get_enroll_face_use_case
from app.enrollment.infrastructure.image_storage import face_image_path
from app.core.generics.mapper import ResponseEnvelope

router = APIRouter(prefix="/enrollment", tags=["Face Enrollment"])
MAX_ENROLLMENT_IMAGE_BYTES = 10 * 1024 * 1024


class EnrollmentResponseSchema(BaseModel):
    status: str
    enrolled_at: str
    sample_count: int
    photo_reference: str | None = None


@router.get("/photos/{filename}", include_in_schema=False)
async def get_enrollment_photo(
    filename: str,
    claims: dict = Depends(require_role([Role.ADMIN])),
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
    return FileResponse(image_path, media_type="image/jpeg", filename=filename)


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
