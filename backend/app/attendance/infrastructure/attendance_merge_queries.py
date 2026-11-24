from sqlalchemy import exists, select

from app.attendance.infrastructure.db_model import (
    AttendanceMergeSourceModel,
    AttendanceModel,
)


def not_merged_source(attendance_model=AttendanceModel):
    return ~exists(
        select(1).where(
            AttendanceMergeSourceModel.source_attendance_id == attendance_model.id,
        )
    )
