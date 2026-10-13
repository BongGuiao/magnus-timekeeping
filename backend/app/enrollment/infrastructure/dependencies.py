from fastapi import Depends

from app.core.generics.uow import get_unit_of_work, GenUnitOfWork
from app.enrollment.application.use_case import EnrollFaceUseCase
from app.core import face_recognition_service


def get_enroll_face_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> EnrollFaceUseCase:
    return EnrollFaceUseCase(uow, face_recognition_service)
