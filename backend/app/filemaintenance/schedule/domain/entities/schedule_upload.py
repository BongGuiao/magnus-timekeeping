from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from enum import Enum
from uuid import UUID

from app.filemaintenance.schedule.domain.schedule_upload_exceptions import (
    ScheduleUploadPermissionError,
    ScheduleUploadStateError,
)


class ScheduleUploadBatchStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class RawScheduleUploadRow:
    """One data row exactly as read from the uploaded file (all values are text)."""

    row_no: int
    employee_code: str = ""
    schedule_code: str = ""
    assignment_type: str = ""
    effective_from: str = ""
    effective_to: str = ""
    rest_day_pattern_code: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ScheduleUploadFile:
    rows: tuple[RawScheduleUploadRow, ...] = ()
    file_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScheduleUploadRow:
    """A row whose individual field values are well-formed."""

    row_no: int
    employee_code: str
    schedule_code: str
    assignment_type: str
    effective_from: date
    effective_to: date | None
    rest_day_pattern_code: str | None
    reason: str | None


@dataclass(frozen=True)
class TeamEmployee:
    employee_id: UUID
    employee_code: str
    employee_name: str
    company_id: UUID


@dataclass(frozen=True)
class ScheduleTemplateRef:
    id: UUID
    company_id: UUID
    schedule_code: str
    schedule_name: str
    status: str
    is_active: bool
    effective_from: date
    effective_to: date | None


@dataclass(frozen=True)
class RestDayPatternRef:
    id: UUID
    pattern_code: str
    pattern_name: str
    is_active: bool


@dataclass(frozen=True)
class ExistingScheduleAssignment:
    """An approved, active schedule assignment already in effect or scheduled."""

    id: UUID
    employee_id: UUID
    schedule_template_id: UUID
    schedule_code: str
    rest_day_pattern_id: UUID | None
    assignment_type: str
    effective_from: date
    effective_to: date | None


@dataclass(frozen=True)
class ResolvedScheduleUploadRow:
    row: ScheduleUploadRow
    employee: TeamEmployee
    template: ScheduleTemplateRef
    rest_day_pattern: RestDayPatternRef | None


@dataclass(frozen=True)
class ScheduleUploadRowResult:
    row_no: int
    employee_code: str
    schedule_code: str
    assignment_type: str
    effective_from: date | None
    effective_to: date | None
    rest_day_pattern_code: str | None
    reason: str | None
    employee_name: str | None = None
    schedule_name: str | None = None
    errors: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ScheduleUploadValidation:
    rows: tuple[ScheduleUploadRowResult, ...] = ()
    file_errors: tuple[str, ...] = ()

    @property
    def error_count(self) -> int:
        return len(self.file_errors) + sum(len(row.errors) for row in self.rows)

    @property
    def is_valid(self) -> bool:
        return bool(self.rows) and self.error_count == 0

    def error_messages(self) -> list[str]:
        return [*self.file_errors] + [
            f"Row {row.row_no}: {error}" for row in self.rows for error in row.errors
        ]


@dataclass(frozen=True)
class NewScheduleAssignment:
    employee_id: UUID
    schedule_template_id: UUID
    rest_day_pattern_id: UUID | None
    assignment_type: str
    effective_from: date
    effective_to: date | None
    reason: str | None
    created_by: UUID
    approved_by: UUID
    approved_at: datetime


@dataclass(frozen=True)
class ScheduleUploadBatchRow:
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
    assignment_id: UUID | None = None

    def to_raw(self) -> RawScheduleUploadRow:
        return RawScheduleUploadRow(
            row_no=self.row_no,
            employee_code=self.employee_code,
            schedule_code=self.schedule_code,
            assignment_type=self.assignment_type,
            effective_from=self.effective_from.isoformat(),
            effective_to=self.effective_to.isoformat() if self.effective_to else "",
            rest_day_pattern_code=self.rest_day_pattern_code or "",
            reason=self.reason or "",
        )


@dataclass(frozen=True)
class NewScheduleUploadBatch:
    batch_no: str
    supervisor_employee_id: UUID
    uploaded_by: UUID
    file_name: str
    rows: tuple[ScheduleUploadBatchRow, ...]


@dataclass(frozen=True)
class ScheduleUploadBatch:
    id: UUID
    batch_no: str
    supervisor_employee_id: UUID
    supervisor_name: str
    uploaded_by: UUID
    file_name: str
    row_count: int
    status: ScheduleUploadBatchStatus
    submitted_at: datetime
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_remarks: str | None = None
    rows: tuple[ScheduleUploadBatchRow, ...] = field(default=())

    def _ensure_pending(self) -> None:
        if self.status is not ScheduleUploadBatchStatus.PENDING_APPROVAL:
            raise ScheduleUploadStateError(
                f"Batch {self.batch_no} is already {self.status.value.replace('_', ' ').lower()}."
            )

    def _ensure_independent_reviewer(self, reviewer_id: UUID) -> None:
        if reviewer_id == self.uploaded_by:
            raise ScheduleUploadPermissionError(
                "You cannot review a schedule batch that you uploaded."
            )

    def approve(self, reviewer_id: UUID, at: datetime, remarks: str | None) -> "ScheduleUploadBatch":
        self._ensure_pending()
        self._ensure_independent_reviewer(reviewer_id)
        return replace(
            self,
            status=ScheduleUploadBatchStatus.APPROVED,
            reviewed_by=reviewer_id,
            reviewed_at=at,
            review_remarks=remarks,
        )

    def reject(self, reviewer_id: UUID, at: datetime, remarks: str) -> "ScheduleUploadBatch":
        self._ensure_pending()
        self._ensure_independent_reviewer(reviewer_id)
        if not remarks.strip():
            raise ScheduleUploadStateError("Provide a reason when rejecting a schedule batch.")
        return replace(
            self,
            status=ScheduleUploadBatchStatus.REJECTED,
            reviewed_by=reviewer_id,
            reviewed_at=at,
            review_remarks=remarks.strip(),
        )

    def cancel(self, user_id: UUID, at: datetime) -> "ScheduleUploadBatch":
        if user_id != self.uploaded_by:
            raise ScheduleUploadPermissionError("Only the uploader can cancel this schedule batch.")
        self._ensure_pending()
        return replace(
            self,
            status=ScheduleUploadBatchStatus.CANCELLED,
            reviewed_by=user_id,
            reviewed_at=at,
        )


@dataclass(frozen=True)
class ScheduleWorkSegment:
    start_time: time
    end_time: time
    end_day_offset: int


@dataclass(frozen=True)
class EmployeeScheduleView:
    """An approved schedule assignment as presented to the employee it belongs to."""

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
    work_segments: tuple[ScheduleWorkSegment, ...] = ()
