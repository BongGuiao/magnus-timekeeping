from datetime import date, datetime
from typing import Protocol, Sequence
from uuid import UUID

from app.payroll.application.off_cycle_inputs import (
    NewOffCycleRun,
    OffCycleEmployee,
    OffCycleLineDraft,
    OffCycleRunTransition,
    ThirteenthMonthPayable,
    ThirteenthMonthRunSummary,
)
from app.payroll.domain.entities.benefits import BenefitType
from app.payroll.domain.entities.off_cycle import OffCycleRunStatus, OffCyclePayrollRun
from app.payroll.domain.services.off_cycle_tax import OffCycleTaxContext, OffCycleYtd


class OffCyclePayrollRepository(Protocol):
    async def list_runs(
        self,
        *,
        company_id: UUID | None = None,
        payroll_group_id: UUID | None = None,
        status: OffCycleRunStatus | None = None,
    ) -> list[OffCyclePayrollRun]: ...

    async def get_run(self, run_id: UUID) -> OffCyclePayrollRun: ...

    async def get_payroll_group_company_id(self, payroll_group_id: UUID) -> UUID: ...

    async def get_benefit_type(self, benefit_type_id: UUID) -> BenefitType: ...

    async def find_group_employees(
        self, payroll_group_id: UUID, employee_nos: Sequence[str]
    ) -> dict[str, OffCycleEmployee]: ...

    async def list_thirteenth_month_runs(
        self, company_id: UUID
    ) -> list[ThirteenthMonthRunSummary]: ...

    async def list_thirteenth_month_payables(
        self, thirteenth_month_run_id: UUID, payroll_group_id: UUID
    ) -> list[ThirteenthMonthPayable]: ...

    async def load_tax_context(self, as_of: date) -> OffCycleTaxContext: ...

    async def load_ytd(
        self,
        *,
        company_id: UUID,
        employee_ids: Sequence[UUID],
        as_of: date,
        exclude_run_id: UUID | None = None,
        created_before: datetime | None = None,
    ) -> dict[UUID, OffCycleYtd]: ...

    async def create_run(self, data: NewOffCycleRun) -> OffCyclePayrollRun: ...

    async def replace_lines(
        self,
        run_id: UUID,
        expected_status: OffCycleRunStatus,
        lines: Sequence[OffCycleLineDraft],
    ) -> OffCyclePayrollRun: ...

    async def transition_run(
        self, run_id: UUID, transition: OffCycleRunTransition
    ) -> OffCyclePayrollRun: ...

    async def delete_run(
        self, run_id: UUID, allowed_statuses: frozenset[str]
    ) -> None: ...
