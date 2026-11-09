from typing import Literal

from app.attendance.infrastructure.correction_db_model import AttendanceCorrectionModel
from app.attendance.infrastructure.db_model import AttendanceModel, OfficialBusinessRequestModel, OvertimeApplicationModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import LeaveApplicationModel
from app.filemaintenance.schedule.infrastructure.emergency_schedule_db_model import EmergencyScheduleRequestModel
from app.filemaintenance.schedule.infrastructure.schedule_upload_db_model import ScheduleUploadBatchModel


ResourceType = Literal[
    "overtime_application", "leave_application", "official_business_request",
    "attendance_correction", "invalid_attendance", "emergency_schedule_request", "schedule_upload_batch",
]
ResourceModel = (
    OvertimeApplicationModel | LeaveApplicationModel | OfficialBusinessRequestModel |
    AttendanceCorrectionModel | AttendanceModel | EmergencyScheduleRequestModel | ScheduleUploadBatchModel
)
RESOURCE_MODELS: dict[ResourceType, tuple[type[ResourceModel], str, str, str]] = {
    "overtime_application": (OvertimeApplicationModel, "status", "PENDING", "overtime.approve_team"),
    "leave_application": (LeaveApplicationModel, "status", "PENDING", "leave.approve_team"),
    "official_business_request": (OfficialBusinessRequestModel, "status", "PENDING", "official_business.approve_team"),
    "attendance_correction": (AttendanceCorrectionModel, "status", "PENDING", "attendance.approve_corrections_team"),
    "invalid_attendance": (AttendanceModel, "record_status", "INVALID", "attendance.read_team"),
    "emergency_schedule_request": (EmergencyScheduleRequestModel, "status", "PENDING_APPROVAL", "schedule.approve_emergency"),
    "schedule_upload_batch": (ScheduleUploadBatchModel, "status", "PENDING_APPROVAL", "schedule.approve"),
}
