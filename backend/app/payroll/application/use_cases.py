from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.payroll.application.ports import PayrollRepository
from app.payroll.domain.entities.gross_payroll import (
    PAY_COMPONENT_CODES,
    Compensation,
    EarningRule,
    GrossPayRun,
    PayrollCutoffLockState,
    ThirteenthMonthRun,
    PayrollBenefitLine,
    PayrollContributionLine,
    calculate_gross_pay,
    compensation_period_basis,
    monthly_compensation_basis,
)
from app.payroll.domain.entities.net_payroll import OpeningYtdBalance
from app.payroll.domain.services.net_payroll import calculate_net_pay


class PayrollCutoffNotFoundError(LookupError):
    pass


class PayrollSetupError(ValueError):
    pass


@dataclass(frozen=True)
class CreateCompensationInput:
    employee_id: UUID
    payroll_group_id: UUID
    base_rate: Decimal
    currency: str
    effective_from: date
    effective_to: date | None
    actor_id: UUID


@dataclass(frozen=True)
class UpdateCompensationInput:
    compensation_id: UUID
    base_rate: Decimal
    currency: str
    effective_from: date
    effective_to: date | None
    actor_id: UUID


@dataclass(frozen=True)
class SaveEarningRuleInput:
    payroll_group_id: UUID
    component_code: str
    multiplier: Decimal
    actor_id: UUID
    rule_id: UUID | None = None


@dataclass(frozen=True)
class SaveOpeningYtdBalanceInput:
    employee_id: UUID
    tax_year: int
    taxable_income: Decimal
    tax_withheld: Decimal
    exempt_limited_benefits: Decimal
    actor_id: UUID


class PayrollUseCases:
    def __init__(self, repository: PayrollRepository):
        self._repository = repository

    async def create_compensation(self, data: CreateCompensationInput) -> Compensation:
        if data.base_rate <= 0:
            raise PayrollSetupError("base_rate must be greater than zero.")
        if data.effective_to is not None and data.effective_to < data.effective_from:
            raise PayrollSetupError("effective_to must be on or after effective_from.")
        return await self._repository.create_compensation(
            employee_id=data.employee_id,
            payroll_group_id=data.payroll_group_id,
            base_rate=str(data.base_rate),
            currency=data.currency,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
            actor_id=data.actor_id,
        )

    async def update_compensation(self, data: UpdateCompensationInput) -> Compensation:
        if data.base_rate <= 0:
            raise PayrollSetupError("base_rate must be greater than zero.")
        if data.effective_to is not None and data.effective_to < data.effective_from:
            raise PayrollSetupError("effective_to must be on or after effective_from.")
        return await self._repository.update_compensation(
            compensation_id=data.compensation_id,
            base_rate=str(data.base_rate),
            currency=data.currency,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
            actor_id=data.actor_id,
        )

    async def list_compensations(
        self,
        employee_id: UUID | None = None,
        payroll_group_id: UUID | None = None,
    ) -> list[Compensation]:
        return await self._repository.list_compensations(employee_id, payroll_group_id)

    async def save_earning_rule(self, data: SaveEarningRuleInput) -> EarningRule:
        if data.component_code not in PAY_COMPONENT_CODES:
            raise PayrollSetupError("Unsupported payroll earning component.")
        if data.multiplier < 0:
            raise PayrollSetupError("multiplier cannot be negative.")
        return await self._repository.save_earning_rule(
            payroll_group_id=data.payroll_group_id,
            component_code=data.component_code,
            multiplier=str(data.multiplier),
            actor_id=data.actor_id,
            rule_id=data.rule_id,
        )

    async def list_earning_rules(self, payroll_group_id: UUID) -> list[EarningRule]:
        return await self._repository.list_earning_rules(payroll_group_id)

    async def calculate_payroll(self, cutoff_id: UUID, actor_id: UUID) -> GrossPayRun:
        try:
            cutoff = await self._repository.load_cutoff_payroll_data(cutoff_id)
        except LookupError as error:
            raise PayrollCutoffNotFoundError(str(error)) from error

        if cutoff.is_locked:
            raise PayrollSetupError("A locked payroll cutoff cannot be recalculated.")
        if not cutoff.is_attendance_finalized:
            raise PayrollSetupError(
                "Finalize attendance for this cutoff before calculating payroll."
            )
        if not cutoff.employees:
            raise PayrollSetupError(
                "The payroll cutoff has no employee time results. Recalculate the attendance cutoff first."
            )
        rules = {
            rule.component_code: rule
            for rule in await self._repository.list_earning_rules(
                cutoff.payroll_group.payroll_group_id
            )
        }
        results = []
        employee_ids = [employee.employee_id for employee in cutoff.employees]
        compensations = await self._repository.load_covering_compensations(
            employee_ids,
            cutoff.payroll_group.payroll_group_id,
            cutoff.period_start,
            cutoff.period_end,
        )
        try:
            net_inputs = await self._repository.load_net_payroll_inputs(
                cutoff_id, employee_ids
            )
        except LookupError as error:
            raise PayrollCutoffNotFoundError(str(error)) from error
        for employee in cutoff.employees:
            compensation = compensations.get(employee.employee_id)
            gross_result = calculate_gross_pay(
                time=employee,
                compensation=compensation,
                policy=cutoff.payroll_group,
                earning_rules=rules,
                cutoff_period_start=cutoff.period_start,
                cutoff_period_end=cutoff.period_end,
            )
            payroll_inputs = net_inputs[employee.employee_id]
            if gross_result.gross_amount is None:
                results.append(
                    replace(
                        gross_result,
                        gross_status=gross_result.status,
                        benefit_lines=tuple(
                            PayrollBenefitLine(
                                benefit_code=benefit.benefit_code,
                                benefit_name=benefit.benefit_name,
                                category=benefit.category,
                                tax_treatment=benefit.tax_treatment,
                                amount=benefit.amount,
                                withholding_timing=benefit.withholding_timing,
                                loan_id=benefit.loan_id,
                            )
                            for benefit in payroll_inputs.benefits
                        ),
                    )
                )
                continue
            net_result = calculate_net_pay(
                gross_amount=gross_result.gross_amount,
                benefits=payroll_inputs.benefits,
                monthly_compensation=monthly_compensation_basis(
                    cutoff.payroll_group,
                    compensation,
                ),
                semimonthly_compensation=compensation_period_basis(
                    cutoff.payroll_group,
                    compensation,
                    periods_per_year=24,
                ),
                contribution_brackets=payroll_inputs.contribution_brackets,
                tax_schedule=payroll_inputs.tax_schedule,
                tax_brackets=payroll_inputs.tax_brackets,
                monthly_cutoff_count=payroll_inputs.monthly_cutoff_count,
                cutoff_number_in_month=payroll_inputs.cutoff_number_in_month,
                contribution_timing=payroll_inputs.statutory_contribution_timing,
                pay_frequency=payroll_inputs.pay_frequency,
                cutoff_half=payroll_inputs.cutoff_half,
                prior_month_employee_contributions=payroll_inputs.prior_month_employee_contributions,
                prior_month_employer_contributions=payroll_inputs.prior_month_employer_contributions,
                prior_ytd_taxable_income=payroll_inputs.prior_ytd_taxable_income,
                prior_ytd_withholding_tax=payroll_inputs.prior_ytd_withholding_tax,
                prior_ytd_limited_exempt_benefits=payroll_inputs.prior_ytd_limited_exempt_benefits,
                year_end_wtax_reconciliation_enabled=(
                    cutoff.year_end_wtax_reconciliation_enabled
                ),
                is_final_december_cutoff=payroll_inputs.is_final_december_cutoff,
                opening_ytd_balance_missing=payroll_inputs.opening_ytd_balance_missing,
                scheduled_days=payroll_inputs.scheduled_days,
                paid_days=payroll_inputs.paid_days,
                required_work_minutes=payroll_inputs.required_work_minutes,
                late_minutes=payroll_inputs.late_minutes,
                undertime_minutes=payroll_inputs.undertime_minutes,
            )
            results.append(
                replace(
                    gross_result,
                    status=(
                        "READY"
                        if gross_result.status == "READY" and net_result.status == "READY"
                        else "HOLD"
                    ),
                    gross_status=gross_result.status,
                    hold_reason=(
                        "; ".join(
                            reason
                            for reason in (
                                gross_result.hold_reason
                                if gross_result.status == "HOLD"
                                else None,
                                net_result.hold_reason
                                if net_result.status == "HOLD"
                                else None,
                            )
                            if reason
                        )
                        or None
                    ),
                    cash_benefit_amount=net_result.cash_benefit_amount,
                    non_cash_benefit_amount=net_result.non_cash_benefit_amount,
                    employee_benefit_deductions=net_result.employee_benefit_deductions,
                    exempt_limited_benefit_amount=net_result.exempt_limited_benefit_amount,
                    taxable_income=net_result.taxable_income,
                    employee_contributions=net_result.employee_contributions,
                    employer_contributions=net_result.employer_contributions,
                    withholding_tax=net_result.withholding_tax,
                    net_amount=net_result.net_amount,
                    benefit_lines=net_result.benefit_lines,
                    contribution_lines=tuple(
                        PayrollContributionLine(
                            program_code=line.program_code,
                            employee_amount=line.employee_amount,
                            employer_amount=line.employer_amount,
                        )
                        for line in net_result.contribution_lines
                    ),
                )
            )
        try:
            return await self._repository.save_gross_pay_run(
                cutoff_id=cutoff_id,
                actor_id=actor_id,
                calculated_at=datetime.now(timezone.utc),
                results=results,
            )
        except LookupError as error:
            raise PayrollCutoffNotFoundError(str(error)) from error

    async def calculate_thirteenth_month(
        self,
        company_id: UUID,
        tax_year: int,
        covered_period_from: date,
        covered_period_to: date,
        actor_id: UUID,
    ) -> ThirteenthMonthRun:
        if tax_year < 1900 or tax_year > 9999:
            raise PayrollSetupError("Tax year must be between 1900 and 9999.")
        if covered_period_from > covered_period_to:
            raise PayrollSetupError("The covered cutoff start date must be on or before its end date.")
        if covered_period_from.year != tax_year or covered_period_to.year != tax_year:
            raise PayrollSetupError("The covered cutoff dates must be within the selected tax year.")
        try:
            return await self._repository.calculate_thirteenth_month_run(
                company_id=company_id,
                tax_year=tax_year,
                covered_period_from=covered_period_from,
                covered_period_to=covered_period_to,
                actor_id=actor_id,
                calculated_at=datetime.now(timezone.utc),
            )
        except LookupError as error:
            raise PayrollCutoffNotFoundError(str(error)) from error

    async def calculate_gross_pay(self, cutoff_id: UUID, actor_id: UUID) -> GrossPayRun:
        """Compatibility name for callers of the former gross-only calculation use case."""
        return await self.calculate_payroll(cutoff_id, actor_id)

    async def approve_payroll_cutoff(
        self, cutoff_id: UUID, actor_id: UUID
    ) -> PayrollCutoffLockState:
        return await self._repository.approve_payroll_cutoff(
            cutoff_id,
            actor_id,
            datetime.now(timezone.utc),
        )

    async def unlock_payroll_cutoff(
        self, cutoff_id: UUID, actor_id: UUID
    ) -> PayrollCutoffLockState:
        return await self._repository.unlock_payroll_cutoff(
            cutoff_id,
            actor_id,
            datetime.now(timezone.utc),
        )

    async def list_my_gross_pay_results(self, user_id: UUID) -> list[GrossPayRun]:
        return await self._repository.list_my_gross_pay_results(user_id)

    async def get_current_gross_pay_run(self, cutoff_id: UUID) -> GrossPayRun | None:
        return await self._repository.get_current_gross_pay_run(cutoff_id)

    async def get_opening_ytd_balance(
        self, employee_id: UUID, tax_year: int
    ) -> OpeningYtdBalance | None:
        if not employee_id or tax_year < 1900 or tax_year > 9999:
            raise PayrollSetupError("A valid employee and tax year are required.")
        return await self._repository.get_opening_ytd_balance(employee_id, tax_year)

    async def save_opening_ytd_balance(
        self, data: SaveOpeningYtdBalanceInput
    ) -> OpeningYtdBalance:
        if not data.employee_id or data.tax_year < 1900 or data.tax_year > 9999:
            raise PayrollSetupError("A valid employee and tax year are required.")
        amounts = (
            data.taxable_income,
            data.tax_withheld,
            data.exempt_limited_benefits,
        )
        if any(not amount.is_finite() or amount < 0 for amount in amounts):
            raise PayrollSetupError("Opening YTD balances must be finite, nonnegative amounts.")
        return await self._repository.record_opening_ytd_balance(
            employee_id=data.employee_id,
            tax_year=data.tax_year,
            taxable_income=str(data.taxable_income),
            tax_withheld=str(data.tax_withheld),
            exempt_limited_benefits=str(data.exempt_limited_benefits),
            actor_id=data.actor_id,
        )
