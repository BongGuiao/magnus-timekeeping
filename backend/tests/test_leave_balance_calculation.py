import unittest

from app.filemaintenance.leaves.application.leave_records_use_case import (
    approved_leave_charge_minutes,
    calculate_available_minutes,
)


class AvailableLeaveBalanceTests(unittest.TestCase):
    def test_approved_paid_minutes_are_charged_when_provided(self) -> None:
        self.assertEqual(approved_leave_charge_minutes(requested_minutes=480, paid_minutes=360), 360)

    def test_approved_request_minutes_are_charged_when_paid_minutes_are_unspecified(self) -> None:
        self.assertEqual(approved_leave_charge_minutes(requested_minutes=480, paid_minutes=None), 480)

    def test_adds_credits_and_subtracts_charges(self) -> None:
        self.assertEqual(
            calculate_available_minutes(
                {
                    "opening_minutes": 480,
                    "granted_minutes": 960,
                    "accrued_minutes": 120,
                    "carryover_minutes": 240,
                    "adjustment_minutes": -60,
                    "used_minutes": 300,
                    "reserved_minutes": 60,
                    "expired_minutes": 120,
                    "converted_minutes": 30,
                }
            ),
            1230,
        )

    def test_balance_can_be_negative(self) -> None:
        self.assertEqual(
            calculate_available_minutes(
                {
                    "opening_minutes": 0,
                    "granted_minutes": 0,
                    "used_minutes": 60,
                }
            ),
            -60,
        )

    def test_missing_amounts_default_to_zero(self) -> None:
        self.assertEqual(calculate_available_minutes({}), 0)

    def test_client_supplied_available_balance_is_ignored(self) -> None:
        self.assertEqual(
            calculate_available_minutes(
                {
                    "opening_minutes": 480,
                    "granted_minutes": 960,
                    "used_minutes": 120,
                    "available_minutes": 999999,
                }
            ),
            1320,
        )
