from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.attendance.application.punch_use_cases import (
    SubmitBreakPunchInput,
    SubmitBreakPunchUseCase,
    SubmitClockPunchInput,
    SubmitClockPunchUseCase,
)
from app.attendance.application.use_case import (
    GetLastAttendanceInputDTO,
    GetLastAttendanceUseCase,
    LastAttendanceOutputDTO,
)
from app.attendance.infrastructure.clock_policy import AttendanceClockPolicy, resolve_attendance_clock_policy
from app.attendance.infrastructure.dependencies import (
    get_last_attendance_use_case,
    get_submit_break_punch_use_case,
    get_submit_clock_punch_use_case,
)
from app.attendance.infrastructure.punch_exceptions import build_punch_metadata, log_rejected_punches
from app.core.generics.mapper import ResponseEnvelope

router = APIRouter()
MAX_FACE_IMAGE_BYTES = 10 * 1024 * 1024


class ClockPolicySchema(BaseModel):
    channel: str
    geofence_required: bool
    client_ip: str | None


class ClockResponseSchema(BaseModel):
    employee_name: str
    employee_code: str
    action: str
    timestamp: str
    schedule_template_id: UUID | None = None
    approval_required: bool = False
    late_minutes: int = 0
    undertime_minutes: int = 0
    calculated_ot_minutes: int = 0
    overtime_hours: float = 0
    regular_overtime_minutes: int = 0
    regular_overtime_hours: float = 0
    night_differential_overtime_minutes: int = 0
    night_differential_overtime_hours: float = 0
    night_differential_hours: float = 0


class BreakResponseSchema(BaseModel):
    employee_name: str
    employee_code: str
    action_recorded: str
    timestamp: str


class LastAttendanceSchema(BaseModel):
    work_date: str
    schedule_template_id: UUID | None = None
    clock_in_at: str | None = None
    clock_out_at: str | None = None
    first_break_out_at: str | None = None
    first_break_in_at: str | None = None
    second_break_out_at: str | None = None
    second_break_in_at: str | None = None
    meal_break_out_at: str | None = None
    meal_break_in_at: str | None = None
    ot_break_out_at: str | None = None
    ot_break_in_at: str | None = None
    expected_clock_in_at: str | None = None
    expected_clock_out_at: str | None = None
    break_rules: list[dict] = Field(default_factory=list)


async def _read_face_image(file: UploadFile) -> bytes:
    image_bytes = await file.read(MAX_FACE_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Face image is empty.")
    if len(image_bytes) > MAX_FACE_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Face image exceeds the 10 MB limit.")
    return image_bytes


@router.get("/clock-policy", response_model=ResponseEnvelope[ClockPolicySchema])
async def get_clock_policy(policy: AttendanceClockPolicy = Depends(resolve_attendance_clock_policy)):
    """Tells the client whether GPS is required for clock-in from this device/network."""
    return ResponseEnvelope[ClockPolicySchema](
        data=ClockPolicySchema(
            channel=policy.channel,
            geofence_required=policy.geofence_required,
            client_ip=policy.client_ip,
        )
    )


@router.post(
    "/clock",
    response_model=ResponseEnvelope[ClockResponseSchema],
    status_code=status.HTTP_201_CREATED,
)
@log_rejected_punches("CLOCK")
async def clock_attendance(
    file: UploadFile = File(...),
    user_id: UUID = Form(...),
    clock_out_confirmed: bool = Form(default=False),
    latitude: float | None = Form(default=None, ge=-90, le=90),
    longitude: float | None = Form(default=None, ge=-180, le=180),
    gps_accuracy_meters: float | None = Form(default=None, gt=0),
    device_challenge_id: UUID | None = Form(default=None),
    device_signature: str | None = Form(default=None, min_length=86, max_length=86),
    policy: AttendanceClockPolicy = Depends(resolve_attendance_clock_policy),
    use_case: SubmitClockPunchUseCase = Depends(get_submit_clock_punch_use_case),
):
    """Records attendance after matching the captured face to the selected employee."""
    result = await use_case.execute(
        SubmitClockPunchInput(
            user_id=user_id,
            image_bytes=await _read_face_image(file),
            clock_channel=policy.as_metadata(),
            enforce_geofence=policy.geofence_required,
            is_native=policy.is_native,
            clock_out_confirmed=clock_out_confirmed,
            device_challenge_id=device_challenge_id,
            device_signature=device_signature,
            latitude=latitude,
            longitude=longitude,
            gps_accuracy_meters=gps_accuracy_meters,
        )
    )
    return ResponseEnvelope[ClockResponseSchema](
        data=ClockResponseSchema(
            employee_name=result.employee_name,
            employee_code=result.employee_code,
            action=result.action,
            timestamp=result.timestamp,
            schedule_template_id=result.schedule_template_id,
            approval_required=result.approval_required,
            late_minutes=result.late_minutes,
            undertime_minutes=result.undertime_minutes,
            calculated_ot_minutes=result.calculated_ot_minutes,
            overtime_hours=result.overtime_hours,
            regular_overtime_minutes=result.regular_overtime_minutes,
            regular_overtime_hours=result.regular_overtime_hours,
            night_differential_overtime_minutes=result.night_differential_overtime_minutes,
            night_differential_overtime_hours=result.night_differential_overtime_hours,
            night_differential_hours=result.night_differential_hours,
        )
    )


@router.post(
    "/clock-break",
    response_model=ResponseEnvelope[BreakResponseSchema],
    status_code=status.HTTP_201_CREATED,
)
@log_rejected_punches("BREAK")
async def clock_break_attendance(
    break_type: str = Form(...),
    user_id: UUID = Form(...),
    file: UploadFile = File(...),
    device_challenge_id: UUID = Form(...),
    device_signature: str = Form(..., min_length=86, max_length=86),
    latitude: float | None = Form(default=None, ge=-90, le=90),
    longitude: float | None = Form(default=None, ge=-180, le=180),
    gps_accuracy_meters: float | None = Form(default=None, gt=0),
    policy: AttendanceClockPolicy = Depends(resolve_attendance_clock_policy),
    use_case: SubmitBreakPunchUseCase = Depends(get_submit_break_punch_use_case),
):
    """Records a break after matching the captured face to the selected employee."""
    result = await use_case.execute(
        SubmitBreakPunchInput(
            user_id=user_id,
            break_type=break_type,
            image_bytes=await _read_face_image(file),
            device_challenge_id=device_challenge_id,
            device_signature=device_signature,
            punch_metadata=build_punch_metadata(
                latitude, longitude, gps_accuracy_meters, policy, datetime.now(timezone.utc),
            ),
        )
    )
    return ResponseEnvelope[BreakResponseSchema](
        data=BreakResponseSchema(
            employee_name=result.employee_name,
            employee_code=result.employee_code,
            action_recorded=result.action_recorded,
            timestamp=result.timestamp,
        )
    )


@router.get("/last", response_model=ResponseEnvelope[LastAttendanceSchema | None])
async def get_last_attendance(
    user_id: UUID,
    use_case: GetLastAttendanceUseCase = Depends(get_last_attendance_use_case),
):
    """Most recent attendance record for an employee; null when they have never clocked in."""
    result: LastAttendanceOutputDTO | None = await use_case.execute(GetLastAttendanceInputDTO(user_id=user_id))

    if result is None:
        return ResponseEnvelope[LastAttendanceSchema | None](data=None)

    return ResponseEnvelope[LastAttendanceSchema | None](
        data=LastAttendanceSchema(
            work_date=result.work_date,
            schedule_template_id=result.schedule_template_id,
            clock_in_at=result.clock_in_at,
            clock_out_at=result.clock_out_at,
            first_break_out_at=result.first_break_out_at,
            first_break_in_at=result.first_break_in_at,
            second_break_out_at=result.second_break_out_at,
            second_break_in_at=result.second_break_in_at,
            meal_break_out_at=result.meal_break_out_at,
            meal_break_in_at=result.meal_break_in_at,
            ot_break_out_at=result.ot_break_out_at,
            ot_break_in_at=result.ot_break_in_at,
            expected_clock_in_at=result.expected_clock_in_at,
            expected_clock_out_at=result.expected_clock_out_at,
            break_rules=result.break_rules,
        )
    )
