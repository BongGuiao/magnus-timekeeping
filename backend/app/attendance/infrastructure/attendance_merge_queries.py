from sqlalchemy import and_, exists, select

from app.attendance.infrastructure.db_model import (
    AttendanceMergeSourceModel,
    AttendanceModel,
)


def not_merged_source(attendance_model=AttendanceModel):
    return and_(
        attendance_model.record_status != "VOID",
        ~exists(
            select(1).where(
                AttendanceMergeSourceModel.source_attendance_id == attendance_model.id,
            )
        ),
    )
