from fastapi import Depends

from app.core.generics.uow import get_unit_of_work, GenUnitOfWork
from app.attendance.application.use_case import (
    ClockAttendanceUseCase, 
    GetLastAttendanceUseCase, 
    RecordBreakUseCase,
)
from app.core import face_recognition_service

def get_record_break_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> RecordBreakUseCase:
    return RecordBreakUseCase(uow, face_recognition_service)


def get_clock_attendance_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> ClockAttendanceUseCase:
    return ClockAttendanceUseCase(uow, face_recognition_service)


def get_last_attendance_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> GetLastAttendanceUseCase:
    return GetLastAttendanceUseCase(uow)
