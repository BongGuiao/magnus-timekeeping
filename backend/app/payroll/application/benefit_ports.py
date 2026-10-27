from typing import Protocol
from uuid import UUID

from app.payroll.application.benefit_inputs import (
    BenefitTypeInput,
    CutoffBenefitInput,
    CutoffBenefitUploadRow,
    EmployeeBenefitEntitlementInput,
    EmployeeBenefitDeductionInput,
)
from app.payroll.domain.entities.benefits import (
    BenefitType,
    CutoffBenefit,
    EmployeeBenefitEntitlement,
    EmployeeBenefitDeduction,
)


class BenefitRepository(Protocol):
    async def list_benefit_types(self, payroll_group_id: UUID) -> list[BenefitType]: ...

    async def create_benefit_type(self, data: BenefitTypeInput) -> BenefitType: ...

    async def update_benefit_type(
        self, benefit_type_id: UUID, data: BenefitTypeInput
    ) -> BenefitType: ...

    async def set_benefit_type_active(
        self, benefit_type_id: UUID, is_active: bool, actor_id: UUID
    ) -> BenefitType: ...

    async def list_cutoff_benefits(self, cutoff_id: UUID) -> list[CutoffBenefit]: ...

    async def save_cutoff_benefit(
        self, data: CutoffBenefitInput, entry_id: UUID | None = None
    ) -> CutoffBenefit: ...

    async def upload_cutoff_benefits(
        self,
        cutoff_id: UUID,
        rows: tuple[CutoffBenefitUploadRow, ...],
        actor_id: UUID,
    ) -> tuple[int, int]: ...

    async def upload_cutoff_deductions(
        self,
        cutoff_id: UUID,
        rows: tuple[CutoffBenefitUploadRow, ...],
        actor_id: UUID,
    ) -> tuple[int, int]: ...

    async def delete_cutoff_benefit(self, entry_id: UUID) -> None: ...

    async def list_employee_deductions(
        self, payroll_group_id: UUID
    ) -> list[EmployeeBenefitDeduction]: ...

    async def save_employee_deduction(
        self,
        data: EmployeeBenefitDeductionInput,
        deduction_id: UUID | None = None,
    ) -> EmployeeBenefitDeduction: ...

    async def set_employee_deduction_active(
        self, deduction_id: UUID, is_active: bool, actor_id: UUID
    ) -> EmployeeBenefitDeduction: ...

    async def list_employee_benefit_entitlements(
        self, payroll_group_id: UUID
    ) -> list[EmployeeBenefitEntitlement]: ...

    async def save_employee_benefit_entitlement(
        self,
        data: EmployeeBenefitEntitlementInput,
        entitlement_id: UUID | None = None,
    ) -> EmployeeBenefitEntitlement: ...

    async def set_employee_benefit_entitlement_active(
        self, entitlement_id: UUID, is_active: bool, actor_id: UUID
    ) -> EmployeeBenefitEntitlement: ...
