import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.payroll.application.benefit_inputs import (
    BenefitTypeInput,
    CutoffBenefitInput,
    EmployeeBenefitDeductionInput,
)
from app.payroll.application.benefit_use_cases import BenefitUseCases
from app.payroll.domain.entities.benefits import (
    BenefitType,
    CutoffBenefit,
    is_benefit_due,
    is_employee_deduction_due,
    validate_employee_benefit_entitlement_values,
    validate_employee_benefit_deduction_values,
)


class FakeBenefitRepository:
    def __init__(self) -> None:
        self.types: list[BenefitType] = []
        self.entries: list[CutoffBenefit] = []

    async def list_benefit_types(self, payroll_group_id):
        return [item for item in self.types if item.payroll_group_id == payroll_group_id]

    async def create_benefit_type(self, data):
        now = datetime.now(timezone.utc)
        result = BenefitType(
            id=uuid4(),
            payroll_group_id=data.payroll_group_id,
            code=data.code,
            name=data.name,
            category=data.category,
            tax_treatment=data.tax_treatment,
            is_active=True,
            created_at=now,
            created_by=data.actor_id,
            updated_at=now,
            updated_by=data.actor_id,
            row_version=1,
            attendance_based=data.attendance_based,
            deduct_for_late=data.deduct_for_late,
            deduct_for_undertime=data.deduct_for_undertime,
            posting_schedule=data.posting_schedule,
        )
        self.types.append(result)
        return result

    async def update_benefit_type(self, benefit_type_id, data):
        raise NotImplementedError

    async def set_benefit_type_active(self, benefit_type_id, is_active, actor_id):
        raise NotImplementedError

    async def list_cutoff_benefits(self, cutoff_id):
        return [item for item in self.entries if item.cutoff_id == cutoff_id]

    async def save_cutoff_benefit(self, data, entry_id=None):
        benefit_type = next(item for item in self.types if item.id == data.benefit_type_id)
        result = CutoffBenefit(
            id=entry_id or uuid4(),
            cutoff_id=data.cutoff_id,
            employee_id=data.employee_id,
            benefit_type_id=benefit_type.id,
            benefit_code=benefit_type.code,
            benefit_name=benefit_type.name,
            category=benefit_type.category,
            tax_treatment=benefit_type.tax_treatment,
            amount=data.amount,
            notes=data.notes,
            attendance_based=benefit_type.attendance_based,
            deduct_for_late=benefit_type.deduct_for_late,
            deduct_for_undertime=benefit_type.deduct_for_undertime,
        )
        self.entries.append(result)
        return result

    async def delete_cutoff_benefit(self, entry_id):
        self.entries = [item for item in self.entries if item.id != entry_id]


class BenefitUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repository = FakeBenefitRepository()
        self.use_cases = BenefitUseCases(self.repository)
        self.group_id = uuid4()
        self.actor_id = uuid4()

    async def test_create_benefit_type_normalizes_code_and_name(self) -> None:
        result = await self.use_cases.create_benefit_type(
            BenefitTypeInput(
                payroll_group_id=self.group_id,
                code=" meal ",
                name=" Meal allowance ",
                category="CASH_ALLOWANCE",
                tax_treatment="EXEMPT_LIMITED",
                actor_id=self.actor_id,
            )
        )

        self.assertEqual(result.code, "MEAL")
        self.assertEqual(result.name, "Meal allowance")

    async def test_create_benefit_type_preserves_posting_schedule(self) -> None:
        result = await self.use_cases.create_benefit_type(
            BenefitTypeInput(
                payroll_group_id=self.group_id,
                code="PHONE",
                name="Phone allowance",
                category="CASH_ALLOWANCE",
                tax_treatment="TAXABLE",
                actor_id=self.actor_id,
                posting_schedule="SECOND_HALF",
            )
        )

        self.assertEqual(result.posting_schedule, "SECOND_HALF")

    async def test_employee_deduction_must_be_tax_exempt(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use EXEMPT"):
            await self.use_cases.create_benefit_type(
                BenefitTypeInput(
                    payroll_group_id=self.group_id,
                    code="HMO",
                    name="HMO premium",
                    category="EMPLOYEE_DEDUCTION",
                    tax_treatment="TAXABLE",
                    actor_id=self.actor_id,
                )
            )

    async def test_cutoff_benefit_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            await self.use_cases.save_cutoff_benefit(
                CutoffBenefitInput(
                    cutoff_id=uuid4(),
                    employee_id=uuid4(),
                    benefit_type_id=uuid4(),
                    amount=Decimal("0"),
                    notes=None,
                    actor_id=self.actor_id,
                )
            )

    async def test_cutoff_benefit_uses_benefit_type_tax_snapshot(self) -> None:
        benefit_type = await self.use_cases.create_benefit_type(
            BenefitTypeInput(
                payroll_group_id=self.group_id,
                code="PHONE",
                name="Phone allowance",
                category="CASH_ALLOWANCE",
                tax_treatment="TAXABLE",
                actor_id=self.actor_id,
                attendance_based=True,
                deduct_for_late=True,
                deduct_for_undertime=False,
            )
        )
        cutoff_id = uuid4()
        entry = await self.use_cases.save_cutoff_benefit(
            CutoffBenefitInput(
                cutoff_id=cutoff_id,
                employee_id=uuid4(),
                benefit_type_id=benefit_type.id,
                amount=Decimal("1000.00"),
                notes="April cutoff",
                actor_id=self.actor_id,
            )
        )

        self.assertEqual(entry.tax_treatment, "TAXABLE")
        self.assertEqual(entry.amount, Decimal("1000.00"))
        self.assertTrue(entry.attendance_based)
        self.assertTrue(entry.deduct_for_late)
        self.assertFalse(entry.deduct_for_undertime)
        self.assertEqual(await self.use_cases.list_cutoff_benefits(cutoff_id), [entry])

    async def test_recurring_deduction_amount_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            await self.use_cases.save_employee_deduction(
                EmployeeBenefitDeductionInput(
                    employee_id=uuid4(),
                    benefit_type_id=uuid4(),
                    amount_per_occurrence=Decimal(0),
                    schedule="FIRST_HALF",
                    effective_from=datetime.now(timezone.utc).date(),
                    effective_to=None,
                    actor_id=self.actor_id,
                )
            )


class BenefitScheduleTests(unittest.TestCase):
    def test_benefit_posting_schedule_selects_expected_half_month_cutoff(self) -> None:
        self.assertTrue(is_benefit_due("FIRST_HALF", 1))
        self.assertFalse(is_benefit_due("FIRST_HALF", 2))
        self.assertFalse(is_benefit_due("SECOND_HALF", 1))
        self.assertTrue(is_benefit_due("SECOND_HALF", 2))
        self.assertTrue(is_benefit_due("EVERY_CUTOFF", 1))
        self.assertTrue(is_benefit_due("EVERY_CUTOFF", 2))
        self.assertFalse(is_benefit_due("EVERY_CUTOFF", 0))

    def test_deduction_schedule_selects_expected_half_month_cutoff(self) -> None:
        self.assertTrue(is_employee_deduction_due("FIRST_HALF", 1))
        self.assertFalse(is_employee_deduction_due("FIRST_HALF", 2))
        self.assertFalse(is_employee_deduction_due("SECOND_HALF", 1))
        self.assertTrue(is_employee_deduction_due("SECOND_HALF", 2))
        self.assertTrue(is_employee_deduction_due("EVERY_CUTOFF", 1))
        self.assertTrue(is_employee_deduction_due("EVERY_CUTOFF", 2))
        self.assertFalse(is_employee_deduction_due("EVERY_CUTOFF", 0))

    def test_recurring_deduction_values_require_positive_amount_and_valid_dates(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite amount greater than zero"):
            validate_employee_benefit_deduction_values(
                amount_per_occurrence=Decimal("NaN"),
                schedule="FIRST_HALF",
                effective_from=datetime(2026, 1, 15, tzinfo=timezone.utc).date(),
                effective_to=None,
            )
        with self.assertRaisesRegex(ValueError, "on or after"):
            validate_employee_benefit_deduction_values(
                amount_per_occurrence=Decimal("100"),
                schedule="SECOND_HALF",
                effective_from=datetime(2026, 1, 15, tzinfo=timezone.utc).date(),
                effective_to=datetime(2026, 1, 14, tzinfo=timezone.utc).date(),
            )

    def test_employee_benefit_entitlement_requires_positive_amount_and_valid_dates(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite amount greater than zero"):
            validate_employee_benefit_entitlement_values(
                amount_per_occurrence=Decimal("0"),
                effective_from=datetime(2026, 1, 15, tzinfo=timezone.utc).date(),
                effective_to=None,
            )
        with self.assertRaisesRegex(ValueError, "on or after"):
            validate_employee_benefit_entitlement_values(
                amount_per_occurrence=Decimal("100"),
                effective_from=datetime(2026, 1, 15, tzinfo=timezone.utc).date(),
                effective_to=datetime(2026, 1, 14, tzinfo=timezone.utc).date(),
            )


if __name__ == "__main__":
    unittest.main()
