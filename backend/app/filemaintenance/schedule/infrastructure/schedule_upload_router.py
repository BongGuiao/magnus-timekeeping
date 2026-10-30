from datetime import date, datetime, time
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field

from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, require_permission
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.schedule.application.schedule_upload_use_cases import (
    ApproveScheduleUploadBatchUseCase,
    CancelScheduleUploadBatchInput,
    CancelScheduleUploadBatchUseCase,
    GetScheduleUploadBatchInput,
    GetScheduleUploadBatchUseCase,
    ListMySchedulesInput,
    ListMySchedulesUseCase,
    ListScheduleUploadBatchesInput,
    ListScheduleUploadBatchesUseCase,
    PreviewScheduleUploadUseCase,
    RejectScheduleUploadBatchUseCase,
    ReviewScheduleUploadBatchInput,
    ScheduleUploadFileInput,
    SubmitScheduleUploadUseCase,
    PreviewHrScheduleUploadUseCase,
    SubmitHrScheduleUploadUseCase,
)
from app.filemaintenance.schedule.domain.entities.schedule_upload import (
    EmployeeScheduleView,
    ScheduleUploadBatch,
    ScheduleUploadBatchStatus,
    ScheduleUploadValidation,
)
from app.filemaintenance.schedule.domain.schedule_upload_rules import MAX_REASON_LENGTH
from app.filemaintenance.schedule.infrastructure.schedule_upload_csv import schedule_upload_csv_template
from app.filemaintenance.schedule.infrastructure.schedule_upload_dependencies import (
    get_approve_schedule_upload_batch_use_case,
    get_cancel_schedule_upload_batch_use_case,
    get_get_schedule_upload_batch_use_case,
    get_list_my_schedules_use_case,
    get_list_schedule_upload_batches_use_case,
    get_preview_schedule_upload_use_case,
    get_reject_schedule_upload_batch_use_case,
    get_submit_schedule_upload_use_case,
    get_preview_hr_schedule_upload_use_case,
    get_submit_hr_schedule_upload_use_case,
)
from app.filemaintenance.schedule.infrastructure.schedule_upload_http_errors import (
    schedule_upload_http_errors,
)

UPLOAD_PERMISSION = "schedule.upload_team"
APPROVE_PERMISSION = "schedule.approve"
READ_OWN_PERMISSION = "schedule.read_own"

MAX_UPLOAD_BYTES = 1024 * 1024
MAX_FILE_NAME_LENGTH = 255
TEMPLATE_FILE_NAME = "schedule_upload_template.csv"
NOT_LINKED_TO_EMPLOYEE = "This account is not linked to an employee profile."

router = APIRouter(prefix="/schedule-uploads", tags=["Schedule Uploads"])
my_schedule_router = APIRouter(prefix="/my-schedule-assignments", tags=["My Schedule"])


class ScheduleUploadRowResultSchema(BaseModel):
    row_no: int
    employee_code: str
    employee_name: str | None
    schedule_code: str
    schedule_name: str | None
    assignment_type: str
    effective_from: date | None
    effective_to: date | None
    rest_day_pattern_code: str | None
    reason: str | None
    is_valid: bool
    errors: list[str]
    effects: list[str]
    supervisor_employee_code: str | None = None


class ScheduleUploadPreviewSchema(BaseModel):
    is_valid: bool
    error_count: int
    file_errors: list[str]
    rows: list[ScheduleUploadRowResultSchema]


class ScheduleUploadBatchRowSchema(BaseModel):
    row_no: int
    employee_id: UUID
    employee_code: str
    employee_name: str
    schedule_code: str
    assignment_type: str
    effective_from: date
    effective_to: date | None
    rest_day_pattern_code: str | None
    reason: str | None
    assignment_id: UUID | None


class ScheduleUploadBatchSummarySchema(BaseModel):
    id: UUID
    batch_no: str
    supervisor_employee_id: UUID
    supervisor_name: str
    uploaded_by: UUID
    file_name: str
    row_count: int
    status: ScheduleUploadBatchStatus
    submitted_at: datetime
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_remarks: str | None


class ScheduleUploadBatchSchema(ScheduleUploadBatchSummarySchema):
    rows: list[ScheduleUploadBatchRowSchema]


class ScheduleUploadReviewRequest(BaseModel):
    remarks: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)


class ScheduleWorkSegmentSchema(BaseModel):
    start_time: time
    end_time: time
    end_day_offset: int


class MyScheduleAssignmentSchema(BaseModel):
    assignment_id: UUID
    schedule_code: str
    schedule_name: str
    schedule_type: str
    assignment_type: str
    effective_from: date
    effective_to: date | None
    rest_day_pattern_code: str | None
    rest_day_pattern_name: str | None
    approved_at: datetime | None
    work_segments: list[ScheduleWorkSegmentSchema]


def _preview_schema(validation: ScheduleUploadValidation) -> ScheduleUploadPreviewSchema:
    return ScheduleUploadPreviewSchema(
        is_valid=validation.is_valid,
        error_count=validation.error_count,
        file_errors=list(validation.file_errors),
        rows=[
            ScheduleUploadRowResultSchema(
                row_no=row.row_no,
                employee_code=row.employee_code,
                employee_name=row.employee_name,
                schedule_code=row.schedule_code,
                schedule_name=row.schedule_name,
                assignment_type=row.assignment_type,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                rest_day_pattern_code=row.rest_day_pattern_code,
                reason=row.reason,
                is_valid=row.is_valid,
                errors=list(row.errors),
                effects=list(row.effects),
                supervisor_employee_code=row.supervisor_employee_code,
            )
            for row in validation.rows
        ],
    )


def _summary_fields(batch: ScheduleUploadBatch) -> dict:
    return {
        "id": batch.id,
        "batch_no": batch.batch_no,
        "supervisor_employee_id": batch.supervisor_employee_id,
        "supervisor_name": batch.supervisor_name,
        "uploaded_by": batch.uploaded_by,
        "file_name": batch.file_name,
        "row_count": batch.row_count,
        "status": batch.status,
        "submitted_at": batch.submitted_at,
        "reviewed_by": batch.reviewed_by,
        "reviewed_at": batch.reviewed_at,
        "review_remarks": batch.review_remarks,
    }


def _summary_schema(batch: ScheduleUploadBatch) -> ScheduleUploadBatchSummarySchema:
    return ScheduleUploadBatchSummarySchema(**_summary_fields(batch))


def _batch_schema(batch: ScheduleUploadBatch) -> ScheduleUploadBatchSchema:
    return ScheduleUploadBatchSchema(
        **_summary_fields(batch),
        rows=[
            ScheduleUploadBatchRowSchema(
                row_no=row.row_no,
                employee_id=row.employee_id,
                employee_code=row.employee_code,
                employee_name=row.employee_name,
                schedule_code=row.schedule_code,
                assignment_type=row.assignment_type,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                rest_day_pattern_code=row.rest_day_pattern_code,
                reason=row.reason,
                assignment_id=row.assignment_id,
            )
            for row in batch.rows
        ],
    )


def _my_schedule_schema(view: EmployeeScheduleView) -> MyScheduleAssignmentSchema:
    return MyScheduleAssignmentSchema(
        assignment_id=view.assignment_id,
        schedule_code=view.schedule_code,
        schedule_name=view.schedule_name,
        schedule_type=view.schedule_type,
        assignment_type=view.assignment_type,
        effective_from=view.effective_from,
        effective_to=view.effective_to,
        rest_day_pattern_code=view.rest_day_pattern_code,
        rest_day_pattern_name=view.rest_day_pattern_name,
        approved_at=view.approved_at,
        work_segments=[
            ScheduleWorkSegmentSchema(
                start_time=segment.start_time,
                end_time=segment.end_time,
                end_day_offset=segment.end_day_offset,
            )
            for segment in view.work_segments
        ],
    )


def _claim_uuid(claims: dict, key: str, detail: str) -> UUID:
    try:
        return UUID(str(claims[key]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail) from error


def _user_id(claims: dict) -> UUID:
    return _claim_uuid(claims, "sub", "The session does not identify a user.")


def _employee_id(claims: dict) -> UUID:
    return _claim_uuid(claims, "employee_id", NOT_LINKED_TO_EMPLOYEE)


async def _file_input(claims: dict, file: UploadFile, *, hr_admin: bool = False) -> ScheduleUploadFileInput:
    file_name = (file.filename or "").strip() or "upload.csv"
    if not file_name.lower().endswith(".csv"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a .csv file.")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The file is larger than 1 MB. Split it into smaller uploads.",
        )
    return ScheduleUploadFileInput(
        supervisor_employee_id=None if hr_admin else _employee_id(claims),
        uploaded_by=_user_id(claims),
        file_name=file_name[-MAX_FILE_NAME_LENGTH:],
        content=content,
    )


async def require_hr_upload_mode(
    dashboard_role_code: str = Query(...),
    claims: dict = Depends(require_permission(UPLOAD_PERMISSION)),
    authorization: GetCurrentAuthorizationUseCase = Depends(get_current_authorization_use_case),
) -> dict:
    current = await authorization.execute(_user_id(claims))
    if dashboard_role_code != "HR_ADMIN" or "HR_ADMIN" not in current.role_codes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HR schedule uploads require the HR_ADMIN role and HR_ADMIN dashboard mode.",
        )
    return claims


@router.get("/hr-admin/template")
async def download_hr_schedule_upload_template(
    _claims: dict = Depends(require_hr_upload_mode),
):
    return Response(
        content=schedule_upload_csv_template(include_supervisor=True),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{TEMPLATE_FILE_NAME}"'},
    )


@router.post("/hr-admin/preview", response_model=ResponseEnvelope[ScheduleUploadPreviewSchema])
async def preview_hr_schedule_upload(
    file: UploadFile = File(...),
    claims: dict = Depends(require_hr_upload_mode),
    use_case: PreviewHrScheduleUploadUseCase = Depends(get_preview_hr_schedule_upload_use_case),
):
    data = await _file_input(claims, file, hr_admin=True)
    with schedule_upload_http_errors():
        validation = await use_case.execute(data)
    return ResponseEnvelope(status="success", data=_preview_schema(validation))


@router.post(
    "/hr-admin", response_model=ResponseEnvelope[list[ScheduleUploadBatchSchema]],
    status_code=status.HTTP_201_CREATED,
)
async def submit_hr_schedule_upload(
    file: UploadFile = File(...),
    claims: dict = Depends(require_hr_upload_mode),
    use_case: SubmitHrScheduleUploadUseCase = Depends(get_submit_hr_schedule_upload_use_case),
):
    data = await _file_input(claims, file, hr_admin=True)
    with schedule_upload_http_errors():
        batches = await use_case.execute(data)
    return ResponseEnvelope(status="success", data=[_batch_schema(batch) for batch in batches])


@router.get("/template")
async def download_schedule_upload_template(
    _claims: dict = Depends(require_permission(UPLOAD_PERMISSION)),
):
    return Response(
        content=schedule_upload_csv_template(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{TEMPLATE_FILE_NAME}"'},
    )


@router.post("/preview", response_model=ResponseEnvelope[ScheduleUploadPreviewSchema])
async def preview_schedule_upload(
    file: UploadFile = File(...),
    claims: dict = Depends(require_permission(UPLOAD_PERMISSION)),
    use_case: PreviewScheduleUploadUseCase = Depends(get_preview_schedule_upload_use_case),
):
    data = await _file_input(claims, file)
    with schedule_upload_http_errors():
        validation = await use_case.execute(data)
    return ResponseEnvelope(status="success", data=_preview_schema(validation))


@router.post(
    "",
    response_model=ResponseEnvelope[ScheduleUploadBatchSchema],
    status_code=status.HTTP_201_CREATED,
)
async def submit_schedule_upload(
    file: UploadFile = File(...),
    claims: dict = Depends(require_permission(UPLOAD_PERMISSION)),
    use_case: SubmitScheduleUploadUseCase = Depends(get_submit_schedule_upload_use_case),
):
    data = await _file_input(claims, file)
    with schedule_upload_http_errors():
        batch = await use_case.execute(data)
    return ResponseEnvelope(status="success", data=_batch_schema(batch))


@router.get("/mine", response_model=ResponseEnvelope[list[ScheduleUploadBatchSummarySchema]])
async def list_my_schedule_uploads(
    batch_status: ScheduleUploadBatchStatus | None = Query(default=None, alias="status"),
    claims: dict = Depends(require_permission(UPLOAD_PERMISSION)),
    use_case: ListScheduleUploadBatchesUseCase = Depends(get_list_schedule_upload_batches_use_case),
):
    batches = await use_case.execute(
        ListScheduleUploadBatchesInput(uploaded_by=_user_id(claims), status=batch_status)
    )
    return ResponseEnvelope(status="success", data=[_summary_schema(batch) for batch in batches])


@router.get("/mine/{batch_id}", response_model=ResponseEnvelope[ScheduleUploadBatchSchema])
async def get_my_schedule_upload(
    batch_id: UUID,
    claims: dict = Depends(require_permission(UPLOAD_PERMISSION)),
    use_case: GetScheduleUploadBatchUseCase = Depends(get_get_schedule_upload_batch_use_case),
):
    with schedule_upload_http_errors():
        batch = await use_case.execute(
            GetScheduleUploadBatchInput(batch_id=batch_id, uploaded_by=_user_id(claims))
        )
    return ResponseEnvelope(status="success", data=_batch_schema(batch))


@router.post("/mine/{batch_id}/cancel", response_model=ResponseEnvelope[ScheduleUploadBatchSummarySchema])
async def cancel_my_schedule_upload(
    batch_id: UUID,
    claims: dict = Depends(require_permission(UPLOAD_PERMISSION)),
    use_case: CancelScheduleUploadBatchUseCase = Depends(get_cancel_schedule_upload_batch_use_case),
):
    with schedule_upload_http_errors():
        batch = await use_case.execute(
            CancelScheduleUploadBatchInput(batch_id=batch_id, user_id=_user_id(claims))
        )
    return ResponseEnvelope(status="success", data=_summary_schema(batch))


@router.get("/review", response_model=ResponseEnvelope[list[ScheduleUploadBatchSummarySchema]])
async def list_schedule_uploads_for_review(
    batch_status: ScheduleUploadBatchStatus | None = Query(
        default=ScheduleUploadBatchStatus.PENDING_APPROVAL, alias="status"
    ),
    _claims: dict = Depends(require_permission(APPROVE_PERMISSION)),
    use_case: ListScheduleUploadBatchesUseCase = Depends(get_list_schedule_upload_batches_use_case),
):
    batches = await use_case.execute(ListScheduleUploadBatchesInput(status=batch_status))
    return ResponseEnvelope(status="success", data=[_summary_schema(batch) for batch in batches])


@router.get("/review/{batch_id}", response_model=ResponseEnvelope[ScheduleUploadBatchSchema])
async def get_schedule_upload_for_review(
    batch_id: UUID,
    _claims: dict = Depends(require_permission(APPROVE_PERMISSION)),
    use_case: GetScheduleUploadBatchUseCase = Depends(get_get_schedule_upload_batch_use_case),
):
    with schedule_upload_http_errors():
        batch = await use_case.execute(GetScheduleUploadBatchInput(batch_id=batch_id))
    return ResponseEnvelope(status="success", data=_batch_schema(batch))


@router.post("/review/{batch_id}/approve", response_model=ResponseEnvelope[ScheduleUploadBatchSchema])
async def approve_schedule_upload(
    batch_id: UUID,
    payload: ScheduleUploadReviewRequest | None = None,
    claims: dict = Depends(require_permission(APPROVE_PERMISSION)),
    use_case: ApproveScheduleUploadBatchUseCase = Depends(get_approve_schedule_upload_batch_use_case),
):
    with schedule_upload_http_errors():
        batch = await use_case.execute(
            ReviewScheduleUploadBatchInput(
                batch_id=batch_id,
                reviewer_id=_user_id(claims),
                remarks=payload.remarks if payload else None,
            )
        )
    return ResponseEnvelope(status="success", data=_batch_schema(batch))


@router.post("/review/{batch_id}/reject", response_model=ResponseEnvelope[ScheduleUploadBatchSummarySchema])
async def reject_schedule_upload(
    batch_id: UUID,
    payload: ScheduleUploadReviewRequest,
    claims: dict = Depends(require_permission(APPROVE_PERMISSION)),
    use_case: RejectScheduleUploadBatchUseCase = Depends(get_reject_schedule_upload_batch_use_case),
):
    with schedule_upload_http_errors():
        batch = await use_case.execute(
            ReviewScheduleUploadBatchInput(
                batch_id=batch_id, reviewer_id=_user_id(claims), remarks=payload.remarks
            )
        )
    return ResponseEnvelope(status="success", data=_summary_schema(batch))


@my_schedule_router.get("", response_model=ResponseEnvelope[list[MyScheduleAssignmentSchema]])
async def list_my_schedule_assignments(
    claims: dict = Depends(require_permission(READ_OWN_PERMISSION)),
    use_case: ListMySchedulesUseCase = Depends(get_list_my_schedules_use_case),
):
    views = await use_case.execute(ListMySchedulesInput(employee_id=_employee_id(claims)))
    return ResponseEnvelope(status="success", data=[_my_schedule_schema(view) for view in views])
