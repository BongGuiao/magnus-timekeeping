from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.payroll.application.off_cycle_inputs import (
    CreateOffCycleBenefitRunInput,
    CreateThirteenthMonthOffCycleRunInput,
    NewOffCycleRun,
    OffCycleLineDraft,
    OffCycleRunTransition,
    ThirteenthMonthRunSummary,
)
from app.payroll.application.off_cycle_ports import OffCyclePayrollRepository
from app.payroll.domain.entities.benefits import (
    BenefitTaxTreatment,
    BenefitWithholdingTiming,
)
from app.payroll.domain.entities.off_cycle import (
    OFF_CYCLE_ALLOWED_STATUSES,
    OffCyclePayrollRun,
    OffCycleRunStatus,
    OffCycleRunType,
    ensure_off_cycle_action_allowed,
    ensure_off_cycle_approver,
    validate_off_cycle_amount,
    validate_off_cycle_benefit_type,
    validate_off_cycle_payment_dates,
)
from app.payroll.domain.services.off_cycle_tax import calculate_off_cycle_line


MAX_OFF_CYCLE_UPLOAD_ROWS = 5000


@dataclass(frozen=True)
class _PayableItem:
    employee_id: UUID
    employee_no: str
    amount: Decimal
    notes: str | None
    thirteenth_month_result_id: UUID | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_notes(value: str | None, *, limit: int = 500) -> str | None:
    cleaned = (value or "").strip()
    if len(cleaned) > limit:
        raise ValueError(f"Notes cannot exceed {limit} characters.")
    return cleaned or None


class OffCyclePayrollUseCases:
    def __init__(
        self,
        repository: OffCyclePayrollRepository,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self._repository = repository
        self._clock = clock

    async def list_runs(
        self,
        *,
        company_id: UUID | None = None,
        payroll_group_id: UUID | None = None,
        status: OffCycleRunStatus | None = None,
    ) -> list[OffCyclePayrollRun]:
        return await self._repository.list_runs(
            company_id=company_id, payroll_group_id=payroll_group_id, status=status
        )

    async def get_run(self, run_id: UUID) -> OffCyclePayrollRun:
        return await self._repository.get_run(run_id)

    async def get_payroll_group_company_id(self, payroll_group_id: UUID) -> UUID:
        return await self._repository.get_payroll_group_company_id(payroll_group_id)

    async def list_thirteenth_month_runs(
        self, payroll_group_id: UUID
    ) -> list[ThirteenthMonthRunSummary]:
        company_id = await self._repository.get_payroll_group_company_id(payroll_group_id)
        return await self._repository.list_thirteenth_month_runs(company_id)

    async def create_benefit_run(
        self, data: CreateOffCycleBenefitRunInput
    ) -> OffCyclePayrollRun:
        validate_off_cycle_payment_dates(data.proposed_payment_date)
        rows = data.rows
        if not rows:
            raise ValueError("Upload at least one employee row.")
        if len(rows) > MAX_OFF_CYCLE_UPLOAD_ROWS:
            raise ValueError(
                f"An off-cycle upload can contain at most {MAX_OFF_CYCLE_UPLOAD_ROWS} rows."
            )
        errors: list[str] = []
        seen: set[str] = set()
        for index, row in enumerate(rows, start=2):
            employee_no = row.employee_no.strip().upper()
            if not employee_no:
                errors.append(f"Row {index}: employee number is required.")
            elif employee_no in seen:
                errors.append(f"Row {index}: employee {employee_no} appears more than once.")
            seen.add(employee_no)
            try:
                validate_off_cycle_amount(row.amount)
            except ValueError as error:
                errors.append(f"Row {index}: {error}")
            try:
                _clean_notes(row.notes)
            except ValueError as error:
                errors.append(f"Row {index}: {error}")
        if errors:
            raise ValueError(" ".join(errors[:20]))

        company_id, tax_treatment, withholding_timing = await self._validated_benefit_type(
            data.payroll_group_id, data.benefit_type_id, "BENEFIT"
        )
        employees = await self._repository.find_group_employees(
            data.payroll_group_id, [row.employee_no.strip().upper() for row in rows]
        )
        missing = [
            row.employee_no.strip().upper()
            for row in rows
            if row.employee_no.strip().upper() not in employees
        ]
        if missing:
            raise ValueError(
                "These employee numbers are not assigned to the selected payroll group: "
                + ", ".join(missing[:20])
            )
        items = [
            _PayableItem(
                employee_id=employees[row.employee_no.strip().upper()].employee_id,
                employee_no=employees[row.employee_no.strip().upper()].employee_no,
                amount=row.amount,
                notes=_clean_notes(row.notes),
            )
            for row in rows
        ]
        lines = await self._calculate_lines(
            company_id=company_id,
            run_type="BENEFIT",
            tax_treatment=tax_treatment,
            withholding_timing=withholding_timing,
            payment_date=data.proposed_payment_date,
            items=items,
        )
        return await self._repository.create_run(
            NewOffCycleRun(
                company_id=company_id,
                payroll_group_id=data.payroll_group_id,
                benefit_type_id=data.benefit_type_id,
                run_type="BENEFIT",
                proposed_payment_date=data.proposed_payment_date,
                created_by=data.actor_id,
                lines=lines,
                notes=_clean_notes(data.notes),
            )
        )

    async def create_thirteenth_month_run(
        self, data: CreateThirteenthMonthOffCycleRunInput
    ) -> OffCyclePayrollRun:
        validate_off_cycle_payment_dates(data.proposed_payment_date)
        company_id, tax_treatment, withholding_timing = await self._validated_benefit_type(
            data.payroll_group_id, data.benefit_type_id, "THIRTEENTH_MONTH"
        )
        payables = await self._repository.list_thirteenth_month_payables(
            data.thirteenth_month_run_id, data.payroll_group_id
        )
        items = [
            _PayableItem(
                employee_id=item.employee_id,
                employee_no=item.employee_no,
                amount=item.amount,
                notes=None,
                thirteenth_month_result_id=item.result_id,
            )
            for item in payables
            if item.amount > 0
        ]
        if not items:
            raise ValueError(
                "The selected 13th-month run has no unpaid results for this payroll group."
            )
        lines = await self._calculate_lines(
            company_id=company_id,
            run_type="THIRTEENTH_MONTH",
            tax_treatment=tax_treatment,
            withholding_timing=withholding_timing,
            payment_date=data.proposed_payment_date,
            items=items,
        )
        return await self._repository.create_run(
            NewOffCycleRun(
                company_id=company_id,
                payroll_group_id=data.payroll_group_id,
                benefit_type_id=data.benefit_type_id,
                run_type="THIRTEENTH_MONTH",
                proposed_payment_date=data.proposed_payment_date,
                created_by=data.actor_id,
                lines=lines,
                notes=_clean_notes(data.notes),
                thirteenth_month_run_id=data.thirteenth_month_run_id,
            )
        )

    async def recalculate_run(self, run_id: UUID) -> OffCyclePayrollRun:
        run = await self._repository.get_run(run_id)
        ensure_off_cycle_action_allowed(run.status, "RECALCULATE")
        lines = await self._recalculate_existing(run)
        return await self._repository.replace_lines(run.id, run.status, lines)

    async def submit_run(self, run_id: UUID, actor_id: UUID) -> OffCyclePayrollRun:
        run = await self._repository.get_run(run_id)
        ensure_off_cycle_action_allowed(run.status, "SUBMIT")
        if not run.lines:
            raise ValueError("Add at least one employee before submitting.")
        lines = await self._recalculate_existing(run)
        await self._repository.replace_lines(run.id, "DRAFT", lines)
        return await self._repository.transition_run(
            run.id,
            OffCycleRunTransition(
                expected_status="DRAFT",
                new_status="PENDING",
                occurred_at=self._clock(),
                actor_id=actor_id,
            ),
        )

    async def approve_run(self, run_id: UUID, actor_id: UUID) -> OffCyclePayrollRun:
        run = await self._repository.get_run(run_id)
        ensure_off_cycle_action_allowed(run.status, "APPROVE")
        ensure_off_cycle_approver(run.created_by, actor_id)
        lines = await self._recalculate_existing(run)
        if self._amounts_changed(run, lines):
            await self._repository.replace_lines(run.id, "PENDING", lines)
            raise ValueError(
                "Year-to-date tax totals changed after submission, so this run was "
                "recalculated. Review the updated amounts and approve again."
            )
        return await self._repository.transition_run(
            run.id,
            OffCycleRunTransition(
                expected_status="PENDING",
                new_status="APPROVED",
                occurred_at=self._clock(),
                actor_id=actor_id,
            ),
        )

    async def reject_run(
        self, run_id: UUID, actor_id: UUID, reason: str
    ) -> OffCyclePayrollRun:
        run = await self._repository.get_run(run_id)
        ensure_off_cycle_action_allowed(run.status, "REJECT")
        cleaned_reason = _clean_notes(reason)
        if cleaned_reason is None:
            raise ValueError("Enter a reason for rejecting this off-cycle run.")
        return await self._repository.transition_run(
            run.id,
            OffCycleRunTransition(
                expected_status=run.status,
                new_status="REJECTED",
                occurred_at=self._clock(),
                actor_id=actor_id,
                rejection_reason=cleaned_reason,
            ),
        )

    async def mark_run_paid(
        self, run_id: UUID, actor_id: UUID, actual_payment_date: date
    ) -> OffCyclePayrollRun:
        run = await self._repository.get_run(run_id)
        ensure_off_cycle_action_allowed(run.status, "MARK_PAID")
        validate_off_cycle_payment_dates(run.proposed_payment_date, actual_payment_date)
        return await self._repository.transition_run(
            run.id,
            OffCycleRunTransition(
                expected_status="APPROVED",
                new_status="PAID",
                occurred_at=self._clock(),
                actor_id=actor_id,
                actual_payment_date=actual_payment_date,
            ),
        )

    async def delete_run(self, run_id: UUID) -> OffCyclePayrollRun:
        run = await self._repository.get_run(run_id)
        ensure_off_cycle_action_allowed(run.status, "DELETE")
        await self._repository.delete_run(run.id, OFF_CYCLE_ALLOWED_STATUSES["DELETE"])
        return run

    async def _validated_benefit_type(
        self,
        payroll_group_id: UUID,
        benefit_type_id: UUID,
        run_type: OffCycleRunType,
    ) -> tuple[UUID, BenefitTaxTreatment, BenefitWithholdingTiming]:
        company_id = await self._repository.get_payroll_group_company_id(payroll_group_id)
        benefit_type = await self._repository.get_benefit_type(benefit_type_id)
        if benefit_type.payroll_group_id != payroll_group_id:
            raise ValueError("The selected benefit type belongs to a different payroll group.")
        validate_off_cycle_benefit_type(benefit_type, run_type)
        return company_id, benefit_type.tax_treatment, benefit_type.withholding_timing

    async def _recalculate_existing(
        self, run: OffCyclePayrollRun
    ) -> tuple[OffCycleLineDraft, ...]:
        if not run.lines:
            return ()
        first = run.lines[0]
        return await self._calculate_lines(
            company_id=run.company_id,
            run_type=run.run_type,
            tax_treatment=first.tax_treatment,
            withholding_timing=first.withholding_timing,
            payment_date=run.proposed_payment_date,
            items=[
                _PayableItem(
                    employee_id=line.employee_id,
                    employee_no=line.employee_no,
                    amount=line.amount,
                    notes=line.notes,
                    thirteenth_month_result_id=line.thirteenth_month_result_id,
                )
                for line in run.lines
            ],
            exclude_run_id=run.id,
            created_before=run.created_at,
        )

    async def _calculate_lines(
        self,
        *,
        company_id: UUID,
        run_type: OffCycleRunType,
        tax_treatment: BenefitTaxTreatment,
        withholding_timing: BenefitWithholdingTiming,
        payment_date: date,
        items: Sequence[_PayableItem],
        exclude_run_id: UUID | None = None,
        created_before: datetime | None = None,
    ) -> tuple[OffCycleLineDraft, ...]:
        tax_context = await self._repository.load_tax_context(payment_date)
        ytd_by_employee = await self._repository.load_ytd(
            company_id=company_id,
            employee_ids=[item.employee_id for item in items],
            as_of=payment_date,
            exclude_run_id=exclude_run_id,
            created_before=created_before,
        )
        lines: list[OffCycleLineDraft] = []
        for item in items:
            try:
                amounts = calculate_off_cycle_line(
                    amount=item.amount,
                    tax_treatment=tax_treatment,
                    withholding_timing=withholding_timing,
                    ytd=ytd_by_employee[item.employee_id],
                    tax=tax_context,
                    method="CUMULATIVE" if run_type == "THIRTEENTH_MONTH" else "INCREMENTAL",
                )
            except ValueError as error:
                raise ValueError(f"Employee {item.employee_no}: {error}") from error
            lines.append(
                OffCycleLineDraft(
                    employee_id=item.employee_id,
                    employee_no=item.employee_no,
                    amount=amounts.amount,
                    taxable_amount=amounts.taxable_amount,
                    exempt_limited_amount=amounts.exempt_limited_amount,
                    withholding_tax=amounts.withholding_tax,
                    net_amount=amounts.net_amount,
                    notes=item.notes,
                    thirteenth_month_result_id=item.thirteenth_month_result_id,
                )
            )
        return tuple(lines)

    @staticmethod
    def _amounts_changed(
        run: OffCyclePayrollRun, lines: Sequence[OffCycleLineDraft]
    ) -> bool:
        current = {
            line.employee_id: (
                line.taxable_amount,
                line.exempt_limited_amount,
                line.withholding_tax,
                line.net_amount,
            )
            for line in run.lines
        }
        recalculated = {
            line.employee_id: (
                line.taxable_amount,
                line.exempt_limited_amount,
                line.withholding_tax,
                line.net_amount,
            )
            for line in lines
        }
        return current != recalculated
