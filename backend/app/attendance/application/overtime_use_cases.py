from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Literal, Optional
from uuid import UUID, uuid4

from app.attendance.application.clock import ph_today, utc_now
from app.attendance.application.overtime_ports import OvertimeUnitOfWork
from app.attendance.application.ports import AuditTrail, RecentAttendanceRefresher
from app.filemaintenance.payroll_cutoffs.application.deadline_policy import (
    CutoffDeadlineError,
    DeadlineStage,
    is_cutoff_closed,
    require_cutoff_open,
)
from app.attendance.application.use_case import (
    PH_TIMEZONE,
    calculate_break_policy,
    calculate_attendance_metrics,
    calculate_net_nonpayable_break_minutes,
    calculate_overtime_breakdown,
    calculate_night_differential_minutes,
    to_utc,
)
from app.attendance.domain import overtime_rules as rules
from app.attendance.domain.entities.overtime import (
    OvertimeApplication,
    OvertimeApplicationRecord,
    OvertimeAttendance,
    OvertimeCutoff,
)
from app.attendance.domain.exceptions import ConflictError, PermissionDeniedError, RecordNotFoundError, RuleViolationError
from app.core.generics.uc_base import BaseUseCase
from app.core.rejection_reason import rejection_reason_for_decision


def _minutes_to_hours(minutes: int) -> Decimal:
    return (Decimal(minutes) / Decimal(60)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP,
    )


def _apply_application_totals(
    attendance: OvertimeAttendance,
    applications: list[OvertimeApplication] | tuple[OvertimeApplication, ...],
) -> None:
    rules.apply_application_totals(attendance, applications)
    if attendance.work_type.upper() != "REST":
        return
    application = next((item for item in applications if item.overtime_type == "REST_DAY_WORK"), None)
    if application is None:
        return
    approved = application.final_payable_minutes or 0 if application.status == "APPROVED" else 0
    approved_end = application.requested_start_at + timedelta(minutes=approved)
    night = calculate_night_differential_minutes(
        actual_clock_in_at=application.requested_start_at,
        actual_clock_out_at=approved_end,
    )
    night_ot = calculate_night_differential_minutes(
        actual_clock_in_at=application.requested_start_at + timedelta(minutes=480),
        actual_clock_out_at=approved_end,
    )
    attendance.overtime_request_status = application.status
    attendance.approved_regular_overtime_minutes = max(0, approved - 480 - night_ot)
    attendance.approved_night_differential_overtime_minutes = night_ot
    attendance.approved_night_differential_minutes = night
    attendance.approved_ot_worked = max(0, approved - 480) / 60
    attendance.approved_night_diff = night / 60


@dataclass
class AttendanceBreakCalculationDetail:
    break_slot: str
    punch_out_at: Optional[datetime]
    punch_in_at: Optional[datetime]
    duration_minutes: Optional[int]
    allowance_minutes: Optional[int]
    excess_minutes: int


@dataclass
class OvertimeAttendanceOptions:
    cutoff: OvertimeCutoff
    attendance: list[OvertimeAttendance]


@dataclass
class AttendanceRecalculationItem:
    attendance_id: UUID
    work_date: date
    status: Literal["PREVIEW", "UPDATED", "UNCHANGED", "SKIPPED"]
    reason: Optional[str]
    previous_expected_clock_in_at: Optional[datetime]
    previous_expected_clock_out_at: Optional[datetime]
    actual_clock_in_at: Optional[datetime]
    actual_clock_out_at: Optional[datetime]
    expected_clock_in_at: Optional[datetime]
    expected_clock_out_at: Optional[datetime]
    regular_overtime_minutes: int
    night_differential_overtime_minutes: int
    calculated_ot_minutes: int
    night_differential_minutes: int
    regular_night_differential_minutes: int
    previous_late_minutes: int
    late_minutes: int
    undertime_minutes: int
    excess_minutes_break: int = 0
    minutes_worked: Optional[int] = None
    break_calculation_details: list[AttendanceBreakCalculationDetail] = field(default_factory=list)


def _break_calculation_details(
    record: OvertimeAttendance,
    break_rules: list[dict],
) -> list[AttendanceBreakCalculationDetail]:
    slot_fields = {
        "FIRST_BREAK": ("first_break_out_at", "first_break_in_at"),
        "MEAL_BREAK": ("meal_break_out_at", "meal_break_in_at"),
        "SECOND_BREAK": ("second_break_out_at", "second_break_in_at"),
        "OT_BREAK": ("ot_break_out_at", "ot_break_in_at"),
    }
    rules_by_slot = {rule.get("break_slot"): rule for rule in break_rules}
    details = []
    for slot, (out_field, in_field) in slot_fields.items():
        rule = rules_by_slot.get(slot)
        punch_out = getattr(record, out_field)
        punch_in = getattr(record, in_field)
        if rule is None and punch_out is None and punch_in is None:
            continue
        duration = None
        if punch_out is not None and punch_in is not None and to_utc(punch_in) > to_utc(punch_out):
            duration = int((to_utc(punch_in) - to_utc(punch_out)).total_seconds() // 60)
        allowance = int(rule["break_minutes"]) if rule is not None else None
        details.append(AttendanceBreakCalculationDetail(
            break_slot=slot,
            punch_out_at=punch_out,
            punch_in_at=punch_in,
            duration_minutes=duration,
            allowance_minutes=allowance,
            excess_minutes=max(0, duration - allowance) if duration is not None and allowance is not None else 0,
        ))
    return details


@dataclass
class AttendanceRangeRecalculation:
    employee_id: UUID
    from_date: date
    to_date: date
    dry_run: bool
    preview_count: int
    updated_count: int
    unchanged_count: int
    skipped_count: int
    records: list[AttendanceRecalculationItem]


class _OvertimeUseCase:
    def __init__(self, uow: OvertimeUnitOfWork, clock: Callable[[], datetime] = utc_now):
        self._uow = uow
        self._clock = clock

    def _today(self):
        return ph_today(self._clock())


@dataclass
class RecalculateAttendanceRangeInput:
    actor_user_id: UUID
    employee_id: UUID
    from_date: date
    to_date: date
    dry_run: bool = True
    deadline_stage: DeadlineStage = "APPROVAL"


class RecalculateAttendanceRangeUseCase(
    _OvertimeUseCase, BaseUseCase[AttendanceRangeRecalculation]
):
    def __init__(
        self,
        uow: OvertimeUnitOfWork,
        refresher: RecentAttendanceRefresher,
        audit: AuditTrail,
        clock: Callable[[], datetime] = utc_now,
    ):
        super().__init__(uow, clock)
        self._refresher = refresher
        self._audit = audit

    async def _execute(
        self, data: RecalculateAttendanceRangeInput
    ) -> AttendanceRangeRecalculation:
        if data.from_date > data.to_date:
            raise ValueError("from_date must be on or before to_date.")

        results: list[AttendanceRecalculationItem] = []
        audit_records: list[dict] = []
        refresh_user_id: Optional[UUID] = None
        async with self._uow as uow:
            records = await uow.overtime.list_employee_attendance_in_range(
                data.employee_id,
                data.from_date,
                data.to_date,
                lock_for_update=not data.dry_run,
            )
            if records:
                refresh_user_id = records[0].user_id
            for record in records:
                actual_start = record.effective_clock_in
                actual_end = record.effective_clock_out
                previous_start = record.expected_clock_in_at
                previous_end = record.expected_clock_out_at
                previous_late = record.late_minutes
                metadata = record.punch_metadata or {}
                saved_baseline_start = metadata.get("recalculation_baseline_expected_clock_in_at")
                saved_baseline_end = metadata.get("recalculation_baseline_expected_clock_out_at")
                try:
                    baseline_start = (
                        datetime.fromisoformat(saved_baseline_start)
                        if isinstance(saved_baseline_start, str)
                        else previous_start
                    )
                except ValueError:
                    results.append(AttendanceRecalculationItem(
                        attendance_id=record.id,
                        work_date=record.work_date,
                        status="SKIPPED",
                        reason="Saved original expected clock-in is invalid.",
                        previous_expected_clock_in_at=previous_start,
                        previous_expected_clock_out_at=previous_end,
                        actual_clock_in_at=actual_start,
                        actual_clock_out_at=actual_end,
                        expected_clock_in_at=previous_start,
                        expected_clock_out_at=previous_end,
                        regular_overtime_minutes=record.regular_overtime_minutes,
                        night_differential_overtime_minutes=record.night_differential_overtime_minutes,
                        calculated_ot_minutes=record.calculated_ot_minutes,
                        night_differential_minutes=record.night_differential_minutes,
                        regular_night_differential_minutes=max(
                            0,
                            record.night_differential_minutes
                            - record.night_differential_overtime_minutes,
                        ),
                        previous_late_minutes=previous_late,
                        late_minutes=previous_late,
                        undertime_minutes=record.undertime_minutes,
                        excess_minutes_break=0,
                        minutes_worked=None,
                    ))
                    continue

                def item(
                    status: Literal["PREVIEW", "UPDATED", "UNCHANGED", "SKIPPED"],
                    reason: Optional[str],
                    expected_start: Optional[datetime] = previous_start,
                    expected_end: Optional[datetime] = previous_end,
                    regular_minutes: int = record.regular_overtime_minutes,
                    night_minutes: int = record.night_differential_overtime_minutes,
                    total_minutes: int = record.calculated_ot_minutes,
                    nd_minutes: int = record.night_differential_minutes,
                    previous_late_minutes: int = previous_late,
                    late: int = record.late_minutes,
                    undertime: int = record.undertime_minutes,
                    excess_break: int = 0,
                    worked_minutes: Optional[int] = None,
                    break_details: Optional[list[AttendanceBreakCalculationDetail]] = None,
                ) -> AttendanceRecalculationItem:
                    return AttendanceRecalculationItem(
                        attendance_id=record.id,
                        work_date=record.work_date,
                        status=status,
                        reason=reason,
                        previous_expected_clock_in_at=previous_start,
                        previous_expected_clock_out_at=previous_end,
                        actual_clock_in_at=actual_start,
                        actual_clock_out_at=actual_end,
                        expected_clock_in_at=expected_start,
                        expected_clock_out_at=expected_end,
                        regular_overtime_minutes=regular_minutes,
                        night_differential_overtime_minutes=night_minutes,
                        calculated_ot_minutes=total_minutes,
                        night_differential_minutes=nd_minutes,
                        regular_night_differential_minutes=max(
                            0,
                            nd_minutes - night_minutes,
                        ),
                        previous_late_minutes=previous_late_minutes,
                        late_minutes=late,
                        undertime_minutes=undertime,
                        excess_minutes_break=excess_break,
                        minutes_worked=worked_minutes,
                        break_calculation_details=break_details or [],
                    )

                if record.is_locked:
                    results.append(item("SKIPPED", "Attendance is locked."))
                    continue
                if not data.dry_run:
                    record_cutoff = await uow.overtime.get_cutoff_for_employee_on_date(
                        data.employee_id, record.work_date
                    )
                    if record_cutoff is not None and is_cutoff_closed(
                        record_cutoff, self._clock(), stage=data.deadline_stage,
                    ):
                        results.append(item(
                            "SKIPPED",
                            f"Payroll cutoff {record_cutoff.cutoff_code} is closed for attendance changes.",
                        ))
                        continue
                if actual_start is None or actual_end is None:
                    results.append(item("SKIPPED", "Attendance does not have complete effective punches."))
                    continue
                if to_utc(actual_end) <= to_utc(actual_start):
                    results.append(item("SKIPPED", "Effective clock-out must be after effective clock-in."))
                    continue
                if previous_start is None or previous_end is None:
                    results.append(item("SKIPPED", "Expected schedule boundaries are missing."))
                    continue
                schedule_duration = to_utc(previous_end) - to_utc(previous_start)
                if schedule_duration <= timedelta(0):
                    results.append(item("SKIPPED", "Expected schedule duration is not positive."))
                    continue

                context = (record.punch_metadata or {}).get("schedule_context") or {}
                if "ot_eligible" not in context:
                    results.append(item("SKIPPED", "The attendance record has no stored overtime policy."))
                    continue
                applications = await uow.overtime.list_applications_for_attendance(record.id)
                if applications:
                    results.append(item("SKIPPED", "Attendance has an OT application; recalculation is skipped to preserve it."))
                    continue

                try:
                    baseline_end = (
                        datetime.fromisoformat(saved_baseline_end)
                        if isinstance(saved_baseline_end, str)
                        else baseline_start + schedule_duration
                    )
                except ValueError:
                    results.append(item("SKIPPED", "Saved original expected clock-out is invalid."))
                    continue
                if to_utc(baseline_end) <= to_utc(baseline_start):
                    results.append(item("SKIPPED", "Original schedule boundaries are not in chronological order."))
                    continue

                expected_start = baseline_start
                expected_end = baseline_end
                break_rules = list(context.get("break_rules") or [])
                template_id = record.schedule_template_id
                if template_id is None and context.get("schedule_template_id"):
                    try:
                        template_id = UUID(str(context["schedule_template_id"]))
                    except ValueError:
                        results.append(item("SKIPPED", "Saved schedule template id is invalid."))
                        continue
                if template_id is not None:
                    template_break_rules = await uow.overtime.list_break_rules_for_template(
                        template_id,
                    )
                    saved_slots = {
                        rule.get("break_slot")
                        for rule in break_rules
                        if isinstance(rule, dict)
                    }
                    break_rules.extend(
                        rule for rule in template_break_rules
                        if rule.get("break_slot") not in saved_slots
                    )
                try:
                    break_excess_minutes, unpaid_break_minutes, break_intervals = calculate_break_policy(
                        record, break_rules, require_complete=False,
                    )
                except (KeyError, TypeError, ValueError) as error:
                    results.append(item("SKIPPED", f"Break policy cannot be recalculated: {error}"))
                    continue
                net_nonpayable_minutes = calculate_net_nonpayable_break_minutes(
                    record,
                    break_rules,
                    break_intervals,
                    actual_start,
                    actual_end,
                )
                break_details = _break_calculation_details(record, break_rules)
                minutes_worked = max(
                    0,
                    int((to_utc(actual_end) - to_utc(actual_start)).total_seconds() // 60)
                    - net_nonpayable_minutes,
                )
                existing_break_calculation = metadata.get("break_calculation") or {}
                recalculated_break_calculation = {
                    **existing_break_calculation,
                    "excess_undertime_minutes": break_excess_minutes,
                    "excess_minutes_break": break_excess_minutes,
                    "unpaid_break_minutes": unpaid_break_minutes,
                    "net_nonpayable_minutes": net_nonpayable_minutes,
                    "undertime_excludes_break_excess": True,
                }
                ot_eligible = bool(context["ot_eligible"])
                minimum_ot_minutes = int(context.get("minimum_ot_minutes", 0))
                pre_shift_ot_allowed = bool(context.get("pre_shift_ot_allowed", False))
                regular_minutes, night_ot_minutes, total_minutes = calculate_overtime_breakdown(
                    expected_clock_in_at=expected_start,
                    expected_clock_out_at=expected_end,
                    actual_clock_in_at=actual_start,
                    actual_clock_out_at=actual_end,
                    ot_eligible=ot_eligible,
                    minimum_ot_minutes=minimum_ot_minutes,
                    pre_shift_ot_allowed=pre_shift_ot_allowed,
                    break_intervals=break_intervals,
                )
                night_minutes = calculate_night_differential_minutes(
                    actual_clock_in_at=actual_start,
                    actual_clock_out_at=actual_end,
                    break_intervals=break_intervals,
                )
                late_minutes, undertime_minutes, _ = calculate_attendance_metrics(
                    expected_clock_in_at=baseline_start,
                    expected_clock_out_at=expected_end,
                    actual_clock_in_at=actual_start,
                    actual_clock_out_at=actual_end,
                    grace_minutes=int(context.get("grace_minutes", 0)),
                    ot_eligible=ot_eligible,
                    minimum_ot_minutes=minimum_ot_minutes,
                    pre_shift_ot_allowed=pre_shift_ot_allowed,
                    break_intervals=break_intervals,
                )
                changed = (
                    previous_start != expected_start
                    or previous_end != expected_end
                    or record.overtime_hours != _minutes_to_hours(total_minutes)
                    or record.regular_overtime_minutes != regular_minutes
                    or record.regular_overtime_hours != _minutes_to_hours(regular_minutes)
                    or record.night_differential_overtime_minutes != night_ot_minutes
                    or record.night_differential_overtime_hours
                    != _minutes_to_hours(night_ot_minutes)
                    or record.calculated_ot_minutes != total_minutes
                    or record.night_differential_minutes != night_minutes
                    or record.night_differential_hours != _minutes_to_hours(night_minutes)
                    or record.approved_night_differential_minutes != night_minutes
                    or record.approved_night_diff != night_minutes / 60
                    or record.late_minutes != late_minutes
                    or record.undertime_minutes != undertime_minutes
                    or any(
                        existing_break_calculation.get(key) != value
                        for key, value in recalculated_break_calculation.items()
                    )
                )
                status: Literal["PREVIEW", "UPDATED", "UNCHANGED", "SKIPPED"]
                if not changed:
                    status = "UNCHANGED"
                elif data.dry_run:
                    status = "PREVIEW"
                else:
                    status = "UPDATED"
                    before = {
                        "expected_clock_in_at": previous_start.isoformat(),
                        "expected_clock_out_at": previous_end.isoformat(),
                        "regular_overtime_minutes": record.regular_overtime_minutes,
                        "night_differential_overtime_minutes": (
                            record.night_differential_overtime_minutes
                        ),
                        "calculated_ot_minutes": record.calculated_ot_minutes,
                        "night_differential_minutes": record.night_differential_minutes,
                        "late_minutes": record.late_minutes,
                        "undertime_minutes": record.undertime_minutes,
                    }
                    record.expected_clock_in_at = expected_start
                    record.expected_clock_out_at = expected_end
                    if (
                        not isinstance(saved_baseline_start, str)
                        or not isinstance(saved_baseline_end, str)
                    ):
                        record.punch_metadata = {
                            **metadata,
                            "recalculation_baseline_expected_clock_in_at": (
                                baseline_start.isoformat()
                            ),
                            "recalculation_baseline_expected_clock_out_at": (
                                baseline_end.isoformat()
                            ),
                        }
                    record.regular_overtime_minutes = regular_minutes
                    record.regular_overtime_hours = _minutes_to_hours(regular_minutes)
                    record.night_differential_overtime_minutes = night_ot_minutes
                    record.night_differential_overtime_hours = _minutes_to_hours(night_ot_minutes)
                    record.calculated_ot_minutes = total_minutes
                    record.overtime_hours = _minutes_to_hours(total_minutes)
                    record.night_differential_minutes = night_minutes
                    record.night_differential_hours = _minutes_to_hours(night_minutes)
                    record.approved_night_differential_minutes = night_minutes
                    record.approved_night_diff = night_minutes / 60
                    record.late_minutes = late_minutes
                    record.undertime_minutes = undertime_minutes
                    record.punch_metadata = {
                        **(record.punch_metadata or {}),
                        "break_calculation": recalculated_break_calculation,
                    }
                    await uow.overtime.save_attendance(record)
                    audit_records.append({
                        "attendance_id": str(record.id),
                        "before": before,
                        "after": {
                            "expected_clock_in_at": expected_start.isoformat(),
                            "expected_clock_out_at": expected_end.isoformat(),
                            "regular_overtime_minutes": regular_minutes,
                            "night_differential_overtime_minutes": night_ot_minutes,
                            "calculated_ot_minutes": total_minutes,
                            "night_differential_minutes": night_minutes,
                            "late_minutes": late_minutes,
                            "undertime_minutes": undertime_minutes,
                            "excess_minutes_break": break_excess_minutes,
                            "minutes_worked": minutes_worked,
                        },
                    })
                results.append(item(
                    status,
                    None,
                    expected_start,
                    expected_end,
                    regular_minutes,
                    night_ot_minutes,
                    total_minutes,
                    night_minutes,
                    previous_late,
                    late_minutes,
                    undertime_minutes,
                    break_excess_minutes,
                    minutes_worked,
                    break_details,
                ))

        if audit_records:
            if refresh_user_id is not None:
                self._refresher.request_refresh(refresh_user_id)
            for audit_record in audit_records:
                await self._audit.record(
                    user_id=data.actor_user_id,
                    action="RECALCULATE",
                    resource="attendance_record",
                    resource_id=audit_record["attendance_id"],
                    after={
                        "employee_id": str(data.employee_id),
                        "from_date": data.from_date.isoformat(),
                        "to_date": data.to_date.isoformat(),
                        "before": audit_record["before"],
                        "after": audit_record["after"],
                    },
                )

        return AttendanceRangeRecalculation(
            employee_id=data.employee_id,
            from_date=data.from_date,
            to_date=data.to_date,
            dry_run=data.dry_run,
            preview_count=sum(record.status == "PREVIEW" for record in results),
            updated_count=sum(record.status == "UPDATED" for record in results),
            unchanged_count=sum(record.status == "UNCHANGED" for record in results),
            skipped_count=sum(record.status == "SKIPPED" for record in results),
            records=results,
        )


@dataclass
class GetOvertimeAttendanceOptionsInput:
    user_id: UUID


class GetRestDayAttendanceOptionsUseCase(_OvertimeUseCase, BaseUseCase[list[OvertimeAttendance]]):
    async def _execute(self, data: GetOvertimeAttendanceOptionsInput) -> list[OvertimeAttendance]:
        async with self._uow as uow:
            employee_id = await uow.overtime.get_active_employee_id_for_user(data.user_id)
            if employee_id is None:
                raise RecordNotFoundError("An active employee linked to your account was not found.")
            records = await uow.overtime.list_rest_day_attendance(data.user_id, employee_id)
            eligible = []
            for record in records:
                cutoff = await uow.overtime.get_cutoff_for_employee_on_date(employee_id, record.work_date)
                if (
                    cutoff is not None
                    and not is_cutoff_closed(cutoff, self._clock(), stage="FILING")
                    and cutoff.export_batch_id is None
                    and rules.calculated_minutes(record, "REST_DAY_WORK") > 0
                ):
                    eligible.append(record)
            return eligible


class GetOvertimeAttendanceOptionsUseCase(_OvertimeUseCase, BaseUseCase[OvertimeAttendanceOptions]):
    def __init__(
        self,
        uow: OvertimeUnitOfWork,
        refresher: RecentAttendanceRefresher,
        audit: AuditTrail,
        clock: Callable[[], datetime] = utc_now,
    ):
        super().__init__(uow, clock)
        self._refresher = refresher
        self._audit = audit

    async def _execute(self, data: GetOvertimeAttendanceOptionsInput) -> OvertimeAttendanceOptions:
        corrections = []
        async with self._uow as uow:
            employee_id = await uow.overtime.get_active_employee_id_for_user(data.user_id)
            if employee_id is None:
                raise RecordNotFoundError("An active employee linked to your account was not found.")
            cutoff = rules.validate_cutoff(
                await uow.overtime.get_current_cutoff(employee_id, self._today())
            )
            attendance = await uow.overtime.list_completed_attendance_in_period(
                data.user_id, cutoff.period_start, cutoff.period_end
            )
            attendance = [record for record in attendance if record.work_type.upper() != "REST"]
            recalculated_attendance = []
            for listed_record in attendance:
                record = listed_record
                schedule_context = (listed_record.punch_metadata or {}).get("schedule_context", {})
                expected_out = listed_record.expected_clock_out_at
                actual_out = listed_record.effective_clock_out
                if (
                    not is_cutoff_closed(cutoff, self._clock(), stage="FILING")
                    and not listed_record.is_locked
                    and listed_record.night_differential_overtime_minutes == 0
                    and listed_record.regular_overtime_minutes > 0
                    and expected_out is not None
                    and actual_out is not None
                    and to_utc(expected_out).astimezone(PH_TIMEZONE).hour < 6
                    and schedule_context.get("ot_eligible")
                    and isinstance(schedule_context.get("break_rules"), list)
                ):
                    locked = await uow.overtime.lock_completed_attendance(
                        listed_record.id, data.user_id,
                    )
                    if locked is not None:
                        record, _ = locked
                        applications = await uow.overtime.list_applications_for_attendance(record.id)
                        if not any(
                            application.status == "APPROVED" or application.payroll_posted
                            for application in applications
                        ):
                            context = (record.punch_metadata or {}).get("schedule_context", {})
                            _, _, break_intervals = calculate_break_policy(
                                record, context["break_rules"], require_complete=False,
                            )
                            regular_minutes, night_minutes, total_minutes = calculate_overtime_breakdown(
                                expected_clock_in_at=record.expected_clock_in_at,
                                expected_clock_out_at=record.expected_clock_out_at,
                                actual_clock_in_at=record.effective_clock_in,
                                actual_clock_out_at=record.effective_clock_out,
                                ot_eligible=bool(context["ot_eligible"]),
                                minimum_ot_minutes=int(context.get("minimum_ot_minutes", 0)),
                                pre_shift_ot_allowed=bool(context.get("pre_shift_ot_allowed", False)),
                                break_intervals=break_intervals,
                            )
                            if (
                                record.regular_overtime_minutes != regular_minutes
                                or record.night_differential_overtime_minutes != night_minutes
                            ):
                                before = {
                                    "regular_overtime_minutes": record.regular_overtime_minutes,
                                    "night_differential_overtime_minutes": (
                                        record.night_differential_overtime_minutes
                                    ),
                                }
                                record.regular_overtime_minutes = regular_minutes
                                record.regular_overtime_hours = Decimal(regular_minutes) / Decimal(60)
                                record.night_differential_overtime_minutes = night_minutes
                                record.night_differential_overtime_hours = (
                                    Decimal(night_minutes) / Decimal(60)
                                )
                                record.calculated_ot_minutes = total_minutes
                                record.overtime_hours = Decimal(total_minutes) / Decimal(60)
                                await uow.overtime.save_attendance(record)
                                corrections.append({
                                    "attendance_id": str(record.id),
                                    "before": before,
                                    "after": {
                                        "regular_overtime_minutes": regular_minutes,
                                        "night_differential_overtime_minutes": night_minutes,
                                        "calculated_ot_minutes": total_minutes,
                                    },
                                })
                recalculated_attendance.append(record)
            attendance = recalculated_attendance
            options = OvertimeAttendanceOptions(cutoff=cutoff, attendance=attendance)

        if corrections:
            self._refresher.request_refresh(data.user_id)
            for correction in corrections:
                await self._audit.record(
                    user_id=data.user_id,
                    action="RECALCULATE",
                    resource="attendance_overtime",
                    resource_id=correction["attendance_id"],
                    after={
                        "before": correction["before"],
                        **correction["after"],
                        "reason": "Corrected overnight night-differential window.",
                    },
                )
        return options


@dataclass
class SubmitOvertimeApplicationInput:
    user_id: UUID
    attendance_id: UUID
    overtime_type: str
    requested_minutes: int
    reason: str
    work_accomplished: Optional[str] = None
    requested_start_at: Optional[datetime] = None
    requested_end_at: Optional[datetime] = None


class SubmitOvertimeApplicationUseCase(_OvertimeUseCase, BaseUseCase[OvertimeApplicationRecord]):
    def __init__(
        self,
        uow: OvertimeUnitOfWork,
        refresher: RecentAttendanceRefresher,
        audit: AuditTrail,
        clock: Callable[[], datetime] = utc_now,
    ):
        super().__init__(uow, clock)
        self._refresher = refresher
        self._audit = audit

    async def _execute(self, data: SubmitOvertimeApplicationInput) -> OvertimeApplicationRecord:
        async with self._uow as uow:
            locked = await uow.overtime.lock_completed_attendance(data.attendance_id, data.user_id)
            if locked is None:
                raise RecordNotFoundError("Completed attendance record was not found for your account.")
            attendance, employee = locked
            if attendance.is_locked:
                raise ConflictError("Locked attendance cannot be used for a new application.")

            cutoff = await uow.overtime.get_cutoff_for_employee_on_date(
                employee.id,
                attendance.work_date,
                lock_for_update=True,
            )
            cutoff = rules.validate_cutoff(cutoff, attendance.work_date)
            if data.overtime_type == "REST_DAY_WORK" and cutoff.export_batch_id is not None:
                raise ConflictError("Rest-day work cannot be filed for an exported payroll cutoff.")
            try:
                require_cutoff_open(cutoff, self._clock(), stage="FILING")
            except CutoffDeadlineError as error:
                raise ConflictError(str(error)) from error

            has_open_application = await uow.overtime.has_open_application(attendance.id)
            if data.overtime_type == "REST_DAY_WORK" and has_open_application:
                raise ConflictError("An active application already exists for this attendance.")
            if data.overtime_type == "REST_DAY_WORK" and await uow.overtime.has_open_rest_day_application(
                employee.id, attendance.work_date
            ):
                raise ConflictError("A rest-day application already exists for this date. Merge attendance records if needed.")
            if (
                attendance.overtime_request_status in rules.OPEN_APPLICATION_STATUSES
                and not has_open_application
            ):
                raise ConflictError("An overtime request already exists for this attendance record.")
            if await uow.overtime.has_open_application(attendance.id, data.overtime_type):
                raise ConflictError("This overtime type already has a pending or approved application.")

            available_minutes = rules.calculated_minutes(attendance, data.overtime_type)
            rules.validate_requested_minutes(available_minutes, data.requested_minutes)
            if data.overtime_type == "REST_DAY_WORK" and data.requested_minutes != available_minutes:
                raise ConflictError("Rest-day work must request the entire punched interval.")

            requested_start_at, requested_end_at = rules.resolve_requested_period(
                attendance, data.overtime_type, data.requested_start_at, data.requested_end_at
            )
            rules.validate_application_period(
                requested_start_at=requested_start_at,
                requested_end_at=requested_end_at,
                actual_start_at=attendance.effective_clock_in,
                actual_end_at=attendance.effective_clock_out,
                requested_minutes=data.requested_minutes,
            )

            application = await uow.overtime.add_application(
                OvertimeApplication(
                    application_no=(
                        f"{'RD' if data.overtime_type == 'REST_DAY_WORK' else 'OT'}-"
                        f"{attendance.work_date:%Y%m%d}-{uuid4().hex[:12].upper()}"
                    ),
                    employee_id=employee.id,
                    attendance_record_id=attendance.id,
                    attendance_date=attendance.work_date,
                    requested_start_at=requested_start_at,
                    requested_end_at=requested_end_at,
                    potential_ot_minutes=available_minutes,
                    requested_minutes=data.requested_minutes,
                    system_validated_minutes=data.requested_minutes,
                    overtime_type=data.overtime_type,
                    reason=data.reason,
                    work_accomplished=data.work_accomplished,
                    validation_status="VALID",
                    status="PENDING",
                    created_by=data.user_id,
                    updated_by=data.user_id,
                )
            )
            if application.id is None:
                raise RuntimeError("The submitted overtime application has no id.")
            await uow.overtime.assign_approver(
                application.id, employee.id, data.user_id, ph_today(self._clock())
            )
            attendance.overtime_requested_at = self._clock()
            _apply_application_totals(
                attendance, list(await uow.overtime.list_applications_for_attendance(attendance.id))
            )
            await uow.overtime.save_attendance(attendance)
            result = OvertimeApplicationRecord(application, attendance, employee)

        self._refresher.request_refresh(data.user_id)
        await self._audit.record(
            user_id=data.user_id,
            action="SUBMIT",
            resource="overtime_application",
            resource_id=str(application.id),
            after={
                "application_no": application.application_no,
                "attendance_record_id": str(data.attendance_id),
                "overtime_type": data.overtime_type,
                "requested_minutes": data.requested_minutes,
                "requested_start_at": application.requested_start_at.isoformat(),
                "requested_end_at": application.requested_end_at.isoformat(),
            },
        )
        return result


@dataclass
class UpdateOvertimeApplicationInput:
    user_id: UUID
    application_id: UUID
    overtime_type: str
    requested_minutes: int
    reason: str
    work_accomplished: Optional[str] = None
    requested_start_at: Optional[datetime] = None
    requested_end_at: Optional[datetime] = None


class UpdateOvertimeApplicationUseCase(_OvertimeUseCase, BaseUseCase[OvertimeApplicationRecord]):
    def __init__(
        self,
        uow: OvertimeUnitOfWork,
        refresher: RecentAttendanceRefresher,
        audit: AuditTrail,
        clock: Callable[[], datetime] = utc_now,
    ):
        super().__init__(uow, clock)
        self._refresher = refresher
        self._audit = audit

    async def _execute(self, data: UpdateOvertimeApplicationInput) -> OvertimeApplicationRecord:
        async with self._uow as uow:
            record = await uow.overtime.lock_owned_application(data.application_id, data.user_id)
            if record is None:
                raise RecordNotFoundError("Overtime application was not found for your account.")
            application, attendance, employee = record.application, record.attendance, record.employee
            if attendance.is_locked:
                raise ConflictError("Locked attendance cannot be changed.")
            if application.status == "APPROVED" or application.payroll_posted:
                raise ConflictError("Approved or payroll-posted overtime applications cannot be edited.")
            if application.status not in ("PENDING", "REJECTED"):
                raise ConflictError("Only pending or rejected overtime applications can be edited.")
            if (application.overtime_type == "REST_DAY_WORK") != (data.overtime_type == "REST_DAY_WORK"):
                raise ConflictError("A rest-day application cannot be changed to another application type.")
            was_rejected = application.status == "REJECTED"

            cutoff = await uow.overtime.get_cutoff_for_employee_on_date(
                employee.id,
                attendance.work_date,
                lock_for_update=True,
            )
            cutoff = rules.validate_cutoff(cutoff, attendance.work_date)
            if data.overtime_type == "REST_DAY_WORK" and cutoff.export_batch_id is not None:
                raise ConflictError("Rest-day work cannot be changed for an exported payroll cutoff.")
            try:
                require_cutoff_open(cutoff, self._clock(), stage="FILING")
            except CutoffDeadlineError as error:
                raise ConflictError(str(error)) from error
            if await uow.overtime.has_open_application(
                attendance.id, None if data.overtime_type == "REST_DAY_WORK" else data.overtime_type,
                exclude_application_id=application.id,
            ):
                raise ConflictError("This overtime type already has a pending or approved application.")
            if data.overtime_type == "REST_DAY_WORK" and await uow.overtime.has_open_rest_day_application(
                employee.id, attendance.work_date, exclude_application_id=application.id
            ):
                raise ConflictError("A rest-day application already exists for this date. Merge attendance records if needed.")

            available_minutes = rules.calculated_minutes(attendance, data.overtime_type)
            rules.validate_requested_minutes(available_minutes, data.requested_minutes)
            if data.overtime_type == "REST_DAY_WORK" and data.requested_minutes != available_minutes:
                raise ConflictError("Rest-day work must request the entire punched interval.")
            requested_start_at, requested_end_at = rules.resolve_requested_period(
                attendance, data.overtime_type, data.requested_start_at, data.requested_end_at
            )
            rules.validate_application_period(
                requested_start_at=requested_start_at,
                requested_end_at=requested_end_at,
                actual_start_at=attendance.effective_clock_in,
                actual_end_at=attendance.effective_clock_out,
                requested_minutes=data.requested_minutes,
            )

            application.requested_start_at = requested_start_at
            application.requested_end_at = requested_end_at
            application.potential_ot_minutes = available_minutes
            application.requested_minutes = data.requested_minutes
            application.system_validated_minutes = data.requested_minutes
            application.supervisor_approved_minutes = None
            application.final_payable_minutes = None
            application.overtime_type = data.overtime_type
            application.reason = data.reason
            application.work_accomplished = data.work_accomplished
            application.validation_status = "VALID"
            application.status = "PENDING"
            application.rejection_reason = None
            application.updated_by = data.user_id
            application.row_version += 1
            if was_rejected:
                if application.id is None:
                    raise RuntimeError("The overtime application has no id.")
                await uow.overtime.assign_approver(
                    application.id, employee.id, data.user_id, ph_today(self._clock())
                )
            await uow.overtime.save_application(application)

            attendance.overtime_requested_at = self._clock()
            _apply_application_totals(
                attendance, list(await uow.overtime.list_applications_for_attendance(attendance.id))
            )
            await uow.overtime.save_attendance(attendance)

        self._refresher.request_refresh(data.user_id)
        await self._audit.record(
            user_id=data.user_id,
            action="UPDATE",
            resource="overtime_application",
            resource_id=str(application.id),
            after={
                "application_no": application.application_no,
                "attendance_record_id": str(attendance.id),
                "overtime_type": application.overtime_type,
                "requested_minutes": application.requested_minutes,
                "requested_start_at": application.requested_start_at.isoformat(),
                "requested_end_at": application.requested_end_at.isoformat(),
                "status": application.status,
            },
        )
        return record


@dataclass
class ListMyOvertimeApplicationsInput:
    user_id: UUID


class ListMyOvertimeApplicationsUseCase(_OvertimeUseCase, BaseUseCase[list[OvertimeApplicationRecord]]):
    async def _execute(self, data: ListMyOvertimeApplicationsInput) -> list[OvertimeApplicationRecord]:
        async with self._uow as uow:
            return await uow.overtime.list_applications_for_user(data.user_id)


@dataclass
class ListPendingOvertimeApplicationsInput:
    """supervisor_employee_id is None for administrators, who see every pending application."""

    supervisor_employee_id: Optional[UUID]
    actor_employee_id: Optional[UUID] = None


class ListPendingOvertimeApplicationsUseCase(
    _OvertimeUseCase, BaseUseCase[list[OvertimeApplicationRecord]]
):
    async def _execute(
        self, data: ListPendingOvertimeApplicationsInput
    ) -> list[OvertimeApplicationRecord]:
        async with self._uow as uow:
            return await uow.overtime.list_pending_applications(
                data.supervisor_employee_id, data.actor_employee_id
            )


@dataclass
class DecideOvertimeApplicationInput:
    application_id: UUID
    actor_id: UUID
    actor_employee_id: Optional[UUID]
    is_admin: bool
    decision: str
    supervisor_approved_minutes: int
    rejection_reason: str | None = None


class DecideOvertimeApplicationUseCase(_OvertimeUseCase, BaseUseCase[OvertimeApplicationRecord]):
    def __init__(
        self,
        uow: OvertimeUnitOfWork,
        refresher: RecentAttendanceRefresher,
        audit: AuditTrail,
        clock: Callable[[], datetime] = utc_now,
    ):
        super().__init__(uow, clock)
        self._refresher = refresher
        self._audit = audit

    async def _execute(self, data: DecideOvertimeApplicationInput) -> OvertimeApplicationRecord:
        try:
            rejection_reason = rejection_reason_for_decision(data.decision, data.rejection_reason)
        except ValueError as error:
            raise RuleViolationError(str(error)) from error
        supervisor_scope = None if data.is_admin else data.actor_employee_id
        async with self._uow as uow:
            record = await uow.overtime.lock_pending_application(
                data.application_id, supervisor_scope, data.actor_employee_id
            )
            if record is None:
                raise RecordNotFoundError(
                    "Pending overtime application was not found for your assigned employees."
                )
            application, attendance, employee = record.application, record.attendance, record.employee
            if attendance.is_locked:
                raise ConflictError("Locked attendance cannot be approved.")
            cutoff = await uow.overtime.get_cutoff_for_employee_on_date(
                employee.id,
                attendance.work_date,
                lock_for_update=True,
            )
            if application.overtime_type == "REST_DAY_WORK":
                cutoff = rules.validate_cutoff(cutoff, attendance.work_date)
                if cutoff.export_batch_id is not None:
                    raise ConflictError("Rest-day work cannot be approved for an exported payroll cutoff.")
            try:
                require_cutoff_open(cutoff, self._clock())
            except CutoffDeadlineError as error:
                raise ConflictError(str(error)) from error
            approved_minutes = data.supervisor_approved_minutes
            if application.overtime_type == "REST_DAY_WORK":
                available = rules.calculated_minutes(attendance, application.overtime_type)
                rules.resolve_requested_period(
                    attendance, application.overtime_type,
                    application.requested_start_at, application.requested_end_at,
                )
                if application.requested_minutes != available:
                    raise ConflictError("Attendance has changed; the employee must update the application.")
            rules.validate_decision(
                application, employee.id, data.actor_employee_id, data.decision, approved_minutes
            )

            application.status = data.decision
            application.rejection_reason = rejection_reason
            application.approved_by_id = data.actor_id if data.decision == "APPROVED" else None
            application.supervisor_approved_minutes = approved_minutes
            application.final_payable_minutes = approved_minutes if data.decision == "APPROVED" else 0
            application.updated_by = data.actor_id
            application.row_version += 1
            await uow.overtime.save_application(application)

            _apply_application_totals(
                attendance, list(await uow.overtime.list_applications_for_attendance(attendance.id))
            )
            attendance.overtime_approved_by_id = data.actor_id
            attendance.overtime_approved_at = self._clock()
            await uow.overtime.save_attendance(attendance)
            employee_user_id = await uow.overtime.get_user_id_for_employee(employee.id)

        if employee_user_id is not None:
            self._refresher.request_refresh(employee_user_id)
        await self._audit.record(
            user_id=data.actor_id,
            action=data.decision,
            resource="overtime_application",
            resource_id=str(data.application_id),
            after={
                "supervisor_approved_minutes": approved_minutes,
                "final_payable_minutes": application.final_payable_minutes,
                "rejection_reason": application.rejection_reason,
            },
        )
        return record


@dataclass
class ReturnOvertimeApprovalInput:
    application_id: UUID
    actor_id: UUID
    actor_employee_id: UUID
    reason: str
    original_approver_only: bool = False


class ReturnOvertimeApprovalUseCase(_OvertimeUseCase, BaseUseCase[OvertimeApplicationRecord]):
    def __init__(
        self, uow: OvertimeUnitOfWork, refresher: RecentAttendanceRefresher,
        clock: Callable[[], datetime] = utc_now,
    ):
        super().__init__(uow, clock)
        self._refresher = refresher

    async def _execute(self, data: ReturnOvertimeApprovalInput) -> OvertimeApplicationRecord:
        reason = data.reason.strip()
        if not reason or len(reason) > 1000:
            raise RuleViolationError("A reason of up to 1000 characters is required.")
        async with self._uow as uow:
            record = await uow.overtime.lock_approved_application(data.application_id)
            if record is None:
                raise RecordNotFoundError("Approved overtime application was not found.")
            application, attendance, employee = record.application, record.attendance, record.employee
            if employee.id == data.actor_employee_id:
                raise PermissionDeniedError("You cannot return your own overtime application.")
            if data.original_approver_only and application.approved_by_id != data.actor_id:
                raise PermissionDeniedError("You can only return overtime applications you personally approved.")
            if application.payroll_posted or attendance.is_locked or attendance.record_status != "VALID":
                raise ConflictError("Posted or locked overtime attendance cannot be returned.")
            cutoff = rules.validate_cutoff(await uow.overtime.get_cutoff_for_employee_on_date(
                employee.id, attendance.work_date, lock_for_update=True,
            ), attendance.work_date)
            if cutoff.export_batch_id is not None:
                raise ConflictError("Overtime for an exported payroll cutoff cannot be returned.")
            try:
                require_cutoff_open(cutoff, self._clock())
            except CutoffDeadlineError as error:
                raise ConflictError(str(error)) from error
            if await uow.overtime.has_open_application(attendance.id, application.overtime_type, application.id):
                raise ConflictError("Another open application exists for this overtime type.")
            if application.overtime_type == "REST_DAY_WORK" and await uow.overtime.has_open_rest_day_application(
                employee.id, attendance.work_date, application.id
            ):
                raise ConflictError("Another open rest-day work application exists for this date.")
            await uow.overtime.assign_return_approver(data.application_id, employee.id, data.actor_id, self._today())
            await uow.overtime.record_approval_return(application, data.actor_id, reason)
            application.status = "PENDING"
            application.approved_by_id = None
            application.supervisor_approved_minutes = None
            application.final_payable_minutes = None
            application.updated_by = data.actor_id
            application.row_version += 1
            await uow.overtime.save_application(application)
            applications = list(await uow.overtime.list_applications_for_attendance(attendance.id))
            _apply_application_totals(attendance, applications)
            # Attendance stores only one approval identity for all overtime types.
            attendance.overtime_approved_by_id = None
            attendance.overtime_approved_at = None
            await uow.overtime.save_attendance(attendance)
            employee_user_id = await uow.overtime.get_user_id_for_employee(employee.id)
        if employee_user_id is not None:
            self._refresher.request_refresh(employee_user_id)
        return record
