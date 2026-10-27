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
        self.assertIsNone(cutoff.cutoff_half)

    def test_cutoff_half_is_explicit_and_rejects_other_values(self) -> None:
        cutoff = CreatePayrollCutoffSchema(
            payroll_group_id=uuid4(),
            cutoff_code="2026-10-A",
            cutoff_half="FIRST_HALF",
            period_start=date(2026, 9, 25),
            period_end=date(2026, 10, 10),
            pay_date=date(2026, 10, 15),
        )
        self.assertEqual(cutoff.cutoff_half, "FIRST_HALF")
        second_cutoff = CreatePayrollCutoffSchema(
            payroll_group_id=cutoff.payroll_group_id,
            cutoff_code="2026-10-B",
            cutoff_half="SECOND_HALF",
            period_start=date(2026, 10, 11),
            period_end=date(2026, 10, 26),
            pay_date=date(2026, 10, 31),
        )
        self.assertEqual(second_cutoff.cutoff_half, "SECOND_HALF")

        with self.assertRaises(ValidationError):
            CreatePayrollCutoffSchema(
                payroll_group_id=uuid4(),
                cutoff_code="2026-10-A",
                cutoff_half="THIRD_HALF",
                period_start=date(2026, 9, 25),
                period_end=date(2026, 10, 10),
                pay_date=date(2026, 10, 15),
            )

    def test_create_schema_rejects_period_end_before_start(self) -> None:
        with self.assertRaises(ValidationError):
            CreatePayrollCutoffSchema(
                payroll_group_id=uuid4(),
                cutoff_code="INVALID",
                period_start=date(2026, 10, 16),
                period_end=date(2026, 10, 15),
                pay_date=date(2026, 10, 20),
            )

    def test_update_schema_allows_clearing_attendance_deadline(self) -> None:
        payload = UpdatePayrollCutoffSchema(
            id=uuid4(),
            attendance_deadline=None,
        )

        self.assertIsNone(payload.attendance_deadline)
        self.assertIn("attendance_deadline", payload.model_fields_set)

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
