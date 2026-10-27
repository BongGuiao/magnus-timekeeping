from uuid import UUID

from app.payroll.application.benefit_inputs import (
    BenefitTypeInput,
    CutoffBenefitInput,
    CutoffBenefitUploadRow,
    EmployeeBenefitEntitlementInput,
    EmployeeBenefitDeductionInput,
)
from app.payroll.application.benefit_ports import BenefitRepository
from app.payroll.domain.entities.benefits import (
    BenefitType,
    CutoffBenefit,
    EmployeeBenefitEntitlement,
    EmployeeBenefitDeduction,
    validate_benefit_type_values,
    validate_cutoff_benefit_amount,
    validate_employee_benefit_deduction_values,
    validate_employee_benefit_entitlement_values,
)


class BenefitUseCases:
    def __init__(self, repository: BenefitRepository):
        self._repository = repository

    async def list_benefit_types(self, payroll_group_id: UUID) -> list[BenefitType]:
        if not payroll_group_id:
            raise ValueError("A payroll group is required.")
        return await self._repository.list_benefit_types(payroll_group_id)

    async def create_benefit_type(self, data: BenefitTypeInput) -> BenefitType:
        self._validate_benefit_type(data)
        return await self._repository.create_benefit_type(
            BenefitTypeInput(
                payroll_group_id=data.payroll_group_id,
                code=data.code.strip().upper(),
                name=data.name.strip(),
                category=data.category,
                tax_treatment=data.tax_treatment,
                actor_id=data.actor_id,
                attendance_based=data.attendance_based,
                deduct_for_late=data.deduct_for_late,
                deduct_for_undertime=data.deduct_for_undertime,
                posting_schedule=data.posting_schedule,
                withholding_timing=data.withholding_timing,
            )
        )

    async def update_benefit_type(
        self, benefit_type_id: UUID, data: BenefitTypeInput
    ) -> BenefitType:
        if not benefit_type_id:
            raise ValueError("A benefit type is required.")
        self._validate_benefit_type(data)
        return await self._repository.update_benefit_type(
            benefit_type_id,
            BenefitTypeInput(
                payroll_group_id=data.payroll_group_id,
                code=data.code.strip().upper(),
                name=data.name.strip(),
                category=data.category,
                tax_treatment=data.tax_treatment,
                actor_id=data.actor_id,
                attendance_based=data.attendance_based,
                deduct_for_late=data.deduct_for_late,
                deduct_for_undertime=data.deduct_for_undertime,
                posting_schedule=data.posting_schedule,
                withholding_timing=data.withholding_timing,
            ),
        )

    async def set_benefit_type_active(
        self, benefit_type_id: UUID, is_active: bool, actor_id: UUID
    ) -> BenefitType:
        if not benefit_type_id:
            raise ValueError("A benefit type is required.")
        return await self._repository.set_benefit_type_active(
            benefit_type_id, is_active, actor_id
        )

    async def list_cutoff_benefits(self, cutoff_id: UUID) -> list[CutoffBenefit]:
        if not cutoff_id:
            raise ValueError("A payroll cutoff is required.")
        return await self._repository.list_cutoff_benefits(cutoff_id)

    async def save_cutoff_benefit(
        self, data: CutoffBenefitInput, entry_id: UUID | None = None
    ) -> CutoffBenefit:
        if not data.cutoff_id or not data.employee_id or not data.benefit_type_id:
            raise ValueError("A cutoff, employee, and benefit type are required.")
        validate_cutoff_benefit_amount(data.amount)
        return await self._repository.save_cutoff_benefit(data, entry_id)

    async def upload_cutoff_benefits(
        self,
        cutoff_id: UUID,
        rows: tuple[CutoffBenefitUploadRow, ...],
        actor_id: UUID,
    ) -> tuple[int, int]:
        self._validate_cutoff_upload(cutoff_id, rows, "benefit")
        return await self._repository.upload_cutoff_benefits(
            cutoff_id, rows, actor_id
        )

    async def upload_cutoff_deductions(
        self,
        cutoff_id: UUID,
        rows: tuple[CutoffBenefitUploadRow, ...],
        actor_id: UUID,
    ) -> tuple[int, int]:
        self._validate_cutoff_upload(cutoff_id, rows, "deduction")
        return await self._repository.upload_cutoff_deductions(
            cutoff_id, rows, actor_id
        )

    @staticmethod
    def _validate_cutoff_upload(
        cutoff_id: UUID,
        rows: tuple[CutoffBenefitUploadRow, ...],
        entry_name: str,
    ) -> None:
        if not cutoff_id:
            raise ValueError(f"Select a cutoff before uploading {entry_name}s.")
        if not rows:
            raise ValueError(f"The upload must contain at least one {entry_name} row.")
        if len(rows) > 1000:
            raise ValueError(f"A {entry_name} upload cannot contain more than 1,000 rows.")
        seen: set[tuple[str, str]] = set()
        for row_number, row in enumerate(rows, start=2):
            employee_no = row.employee_no.strip().upper()
            benefit_code = row.benefit_code.strip().upper()
            if not employee_no or not benefit_code:
                raise ValueError(
                    f"Row {row_number}: employee number and {entry_name} code are required."
                )
            key = (employee_no, benefit_code)
            if key in seen:
                raise ValueError(
                    f"Row {row_number}: duplicate employee number and {entry_name} code in the upload."
                )
            seen.add(key)
            try:
                validate_cutoff_benefit_amount(row.amount)
            except ValueError as error:
                raise ValueError(f"Row {row_number}: {error}") from error
            if row.notes is not None and len(row.notes) > 500:
                raise ValueError(f"Row {row_number}: notes cannot exceed 500 characters.")

    async def delete_cutoff_benefit(self, entry_id: UUID) -> None:
        if not entry_id:
            raise ValueError("A cutoff benefit entry is required.")
        await self._repository.delete_cutoff_benefit(entry_id)

    async def list_employee_deductions(
        self, payroll_group_id: UUID
    ) -> list[EmployeeBenefitDeduction]:
        if not payroll_group_id:
            raise ValueError("A payroll group is required.")
        return await self._repository.list_employee_deductions(payroll_group_id)

    async def save_employee_deduction(
        self,
        data: EmployeeBenefitDeductionInput,
        deduction_id: UUID | None = None,
    ) -> EmployeeBenefitDeduction:
        if not data.employee_id or not data.benefit_type_id:
            raise ValueError("An employee and employee-deduction benefit type are required.")
        validate_employee_benefit_deduction_values(
            amount_per_occurrence=data.amount_per_occurrence,
            schedule=data.schedule,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
        )
        return await self._repository.save_employee_deduction(data, deduction_id)

    async def set_employee_deduction_active(
        self, deduction_id: UUID, is_active: bool, actor_id: UUID
    ) -> EmployeeBenefitDeduction:
        if not deduction_id:
            raise ValueError("An employee benefit deduction is required.")
        return await self._repository.set_employee_deduction_active(
            deduction_id, is_active, actor_id
        )

    async def list_employee_benefit_entitlements(
        self, payroll_group_id: UUID
    ) -> list[EmployeeBenefitEntitlement]:
        if not payroll_group_id:
            raise ValueError("A payroll group is required.")
        return await self._repository.list_employee_benefit_entitlements(payroll_group_id)

    async def save_employee_benefit_entitlement(
        self,
        data: EmployeeBenefitEntitlementInput,
        entitlement_id: UUID | None = None,
    ) -> EmployeeBenefitEntitlement:
        if not data.employee_id or not data.benefit_type_id:
            raise ValueError("An employee and benefit type are required.")
        validate_employee_benefit_entitlement_values(
            amount_per_occurrence=data.amount_per_occurrence,
            schedule=data.schedule,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
        )
        return await self._repository.save_employee_benefit_entitlement(
            data, entitlement_id
        )

    async def set_employee_benefit_entitlement_active(
        self, entitlement_id: UUID, is_active: bool, actor_id: UUID
    ) -> EmployeeBenefitEntitlement:
        if not entitlement_id:
            raise ValueError("An employee benefit entitlement is required.")
        return await self._repository.set_employee_benefit_entitlement_active(
            entitlement_id, is_active, actor_id
        )

    @staticmethod
    def _validate_benefit_type(data: BenefitTypeInput) -> None:
        if not data.payroll_group_id:
            raise ValueError("A payroll group is required.")
        validate_benefit_type_values(
            code=data.code,
            name=data.name,
            category=data.category,
            tax_treatment=data.tax_treatment,
            attendance_based=data.attendance_based,
            deduct_for_late=data.deduct_for_late,
            deduct_for_undertime=data.deduct_for_undertime,
            posting_schedule=data.posting_schedule,
            withholding_timing=data.withholding_timing,
        )
