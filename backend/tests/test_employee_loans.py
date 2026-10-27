from decimal import Decimal
import unittest

from app.payroll.domain.entities.loans import (
    loan_due_this_cutoff,
    loan_installment_due,
    restructured_principal,
)


class EmployeeLoanDomainTests(unittest.TestCase):
    def test_schedule_selects_first_second_or_both_cutoffs(self) -> None:
        self.assertTrue(loan_due_this_cutoff("FIRST_HALF", "FIRST_HALF"))
        self.assertFalse(loan_due_this_cutoff("FIRST_HALF", "SECOND_HALF"))
        self.assertFalse(loan_due_this_cutoff("SECOND_HALF", "FIRST_HALF"))
        self.assertTrue(loan_due_this_cutoff("SECOND_HALF", "SECOND_HALF"))
        self.assertTrue(loan_due_this_cutoff("EVERY_CUTOFF", None))
        with self.assertRaisesRegex(ValueError, "Assign this payroll cutoff"):
            loan_due_this_cutoff("FIRST_HALF", None)

    def test_installment_is_capped_at_remaining_balance(self) -> None:
        self.assertEqual(
            loan_installment_due(Decimal("250.00"), Decimal("75.00")),
            Decimal("75.00"),
        )

    def test_paid_off_loan_has_no_installment(self) -> None:
        self.assertEqual(
            loan_installment_due(Decimal("250.00"), Decimal("0.00")),
            Decimal("0"),
        )

    def test_restructuring_rolls_unpaid_balance_into_new_principal(self) -> None:
        self.assertEqual(
            restructured_principal(Decimal("325.00"), Decimal("1000.00")),
            Decimal("1325.00"),
        )

    def test_restructuring_rejects_zero_unpaid_balance(self) -> None:
        with self.assertRaises(ValueError):
            restructured_principal(Decimal("0.00"), Decimal("100.00"))
