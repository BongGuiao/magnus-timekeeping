from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.payroll.domain.entities.gross_payroll import (
    Compensation,
    CutoffPayrollData,
    EarningRule,
    GrossPayResult,
    GrossPayRun,
    PayrollCutoffLockState,
    ThirteenthMonthRun,
)
from app.payroll.domain.entities.net_payroll import NetPayrollInputs, OpeningYtdBalance


class PayrollRepository(Protocol):
    async def create_compensation(
        self,
        *,
        employee_id: UUID,
        payroll_group_id: UUID,
        base_rate: str,
        currency: str,
        effective_from: date,
        effective_to: date | None,
        actor_id: UUID,
    ) -> Compensation: ...

    async def update_compensation(
        self,
        *,
        compensation_id: UUID,
        base_rate: str,
        currency: str,
        effective_from: date,
        effective_to: date | None,
        actor_id: UUID,
    ) -> Compensation: ...

    async def list_compensations(
        self, employee_id: UUID | None, payroll_group_id: UUID | None
    ) -> list[Compensation]: ...

    async def save_earning_rule(
        self,
        *,
        payroll_group_id: UUID,
        component_code: str,
        multiplier: str,
        actor_id: UUID,
        rule_id: UUID | None = None,
    ) -> EarningRule: ...

    async def list_earning_rules(self, payroll_group_id: UUID) -> list[EarningRule]: ...

    async def load_cutoff_payroll_data(self, cutoff_id: UUID) -> CutoffPayrollData: ...

    async def load_covering_compensations(
        self,
        employee_ids: Sequence[UUID],
        payroll_group_id: UUID,
        period_start: date,
        period_end: date,
    ) -> dict[UUID, Compensation | None]: ...

    async def save_gross_pay_run(
        self,
        *,
        cutoff_id: UUID,
        actor_id: UUID,
        calculated_at: datetime,
        results: list[GrossPayResult],
    ) -> GrossPayRun: ...

    async def approve_payroll_cutoff(
        self, cutoff_id: UUID, actor_id: UUID, approved_at: datetime
    ) -> PayrollCutoffLockState: ...

    async def unlock_payroll_cutoff(
        self, cutoff_id: UUID, actor_id: UUID, unlocked_at: datetime
    ) -> PayrollCutoffLockState: ...

    async def calculate_thirteenth_month_run(
        self,
        *,
        company_id: UUID,
        tax_year: int,
        covered_period_from: date,
        covered_period_to: date,
        actor_id: UUID,
        calculated_at: datetime,
    ) -> ThirteenthMonthRun: ...

    async def get_current_gross_pay_run(self, cutoff_id: UUID) -> GrossPayRun | None: ...

    async def list_my_gross_pay_results(self, user_id: UUID) -> list[GrossPayRun]: ...

    async def load_net_payroll_inputs(
        self, cutoff_id: UUID, employee_ids: Sequence[UUID]
    ) -> dict[UUID, NetPayrollInputs]: ...

    async def get_opening_ytd_balance(
        self, employee_id: UUID, tax_year: int
    ) -> OpeningYtdBalance | None: ...

    async def record_opening_ytd_balance(
        self,
        *,
        employee_id: UUID,
        tax_year: int,
        taxable_income: str,
        tax_withheld: str,
        exempt_limited_benefits: str,
        actor_id: UUID,
    ) -> OpeningYtdBalance: ...
