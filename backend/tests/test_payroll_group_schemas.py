import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.filemaintenance.payroll_groups.infrastructure.router import (
    CreatePayrollGroupSchema,
    UpdatePayrollGroupSchema,
)


class PayrollGroupSchemaTests(unittest.TestCase):
    def test_create_schema_uses_database_defaults(self) -> None:
        payload = CreatePayrollGroupSchema(
            company_id=uuid4(),
            payroll_group_code="MONTHLY",
            payroll_group_name="Monthly Staff",
            pay_frequency="MONTHLY",
            rate_type="MONTHLY",
        )

        self.assertEqual(payload.standard_minutes_per_day, 480)
        self.assertEqual(payload.rounding_minutes, 1)
        self.assertEqual(payload.status, "ACTIVE")

    def test_create_schema_rejects_nonpositive_rounding(self) -> None:
        with self.assertRaises(ValidationError):
            CreatePayrollGroupSchema(
                company_id=uuid4(),
                payroll_group_code="MONTHLY",
                payroll_group_name="Monthly Staff",
                pay_frequency="MONTHLY",
                rate_type="MONTHLY",
                rounding_minutes=0,
            )

    def test_create_schema_rejects_annual_divisor_outside_numeric_precision(self) -> None:
        with self.assertRaises(ValidationError):
            CreatePayrollGroupSchema(
                company_id=uuid4(),
                payroll_group_code="MONTHLY",
                payroll_group_name="Monthly Staff",
                pay_frequency="MONTHLY",
                rate_type="MONTHLY",
                annual_divisor="100000000",
            )
        with self.assertRaises(ValidationError):
            CreatePayrollGroupSchema(
                company_id=uuid4(),
                payroll_group_code="MONTHLY",
                payroll_group_name="Monthly Staff",
                pay_frequency="MONTHLY",
                rate_type="MONTHLY",
                annual_divisor="260.123",
            )

    def test_update_schema_rejects_null_nonnullable_fields(self) -> None:
        with self.assertRaises(ValidationError):
            UpdatePayrollGroupSchema(id=uuid4(), payroll_group_name=None)

    def test_update_schema_allows_clearing_optional_references(self) -> None:
        payload = UpdatePayrollGroupSchema(
            id=uuid4(),
            annual_divisor=None,
            holiday_calendar_id=None,
        )

        self.assertIsNone(payload.annual_divisor)
        self.assertIsNone(payload.holiday_calendar_id)
