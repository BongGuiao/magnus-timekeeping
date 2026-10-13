import unittest
from datetime import date
from uuid import uuid4

from pydantic import ValidationError

from app.filemaintenance.payroll_cutoffs.application.use_case import _validate_period
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_cutoffs.infrastructure.router import (
    CreatePayrollCutoffSchema,
    UpdatePayrollCutoffSchema,
)


class PayrollCutoffSchemaTests(unittest.TestCase):
    def test_create_schema_accepts_valid_cutoff_and_default_status(self) -> None:
        cutoff = CreatePayrollCutoffSchema(
            payroll_group_id=uuid4(),
            cutoff_code="2026-10-A",
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 15),
            pay_date=date(2026, 10, 20),
        )

        self.assertEqual(cutoff.status, "SCHEDULED")

    def test_create_schema_rejects_period_end_before_start(self) -> None:
        with self.assertRaises(ValidationError):
            CreatePayrollCutoffSchema(
                payroll_group_id=uuid4(),
                cutoff_code="INVALID",
                period_start=date(2026, 10, 16),
                period_end=date(2026, 10, 15),
                pay_date=date(2026, 10, 20),
            )

    def test_update_schema_allows_clearing_nullable_deadlines(self) -> None:
        payload = UpdatePayrollCutoffSchema(
            id=uuid4(),
            employee_review_deadline=None,
            supervisor_deadline=None,
            hr_deadline=None,
        )

        self.assertIsNone(payload.hr_deadline)

    def test_lock_metadata_is_not_client_writable(self) -> None:
        with self.assertRaises(ValidationError):
            UpdatePayrollCutoffSchema(
                id=uuid4(),
                locked_at="2026-10-15T10:00:00Z",
            )

    def test_merged_period_validation_rejects_end_before_start(self) -> None:
        with self.assertRaisesRegex(ValueError, "period_end"):
            _validate_period(date(2026, 10, 16), date(2026, 10, 15))

    def test_foreign_keys_reference_payroll_group_and_identity_user(self) -> None:
        targets = {
            element.target_fullname
            for constraint in PayrollCutoffModel.__table__.foreign_key_constraints
            for element in constraint.elements
        }

        self.assertEqual(
            targets,
            {"payroll.payroll_groups.id", "identity.users.id"},
        )
