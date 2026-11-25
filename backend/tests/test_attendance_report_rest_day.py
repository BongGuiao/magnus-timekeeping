import unittest
from uuid import uuid4

from app.attendance.infrastructure.attendance_report_router import (
    _accumulate_approved_overtime,
    _OrgUnitAttendanceSummaryAccumulator,
)
from app.attendance.infrastructure.db_model import OvertimeApplicationModel


class AttendanceReportRestDayTests(unittest.TestCase):
    def test_summary_counts_only_rest_day_minutes_above_eight_hours_as_overtime(self):
        bucket = _OrgUnitAttendanceSummaryAccumulator(None, "", "")
        for minutes in (300, 480, 600):
            _accumulate_approved_overtime(
                bucket,
                OvertimeApplicationModel(
                    id=uuid4(), overtime_type="REST_DAY_WORK",
                    final_payable_minutes=minutes,
                ),
            )
        self.assertEqual(bucket.approved_overtime_minutes, 120)
        self.assertEqual(len(bucket.overtime_ids), 1)

    def test_normal_overtime_summary_is_unchanged(self):
        bucket = _OrgUnitAttendanceSummaryAccumulator(None, "", "")
        _accumulate_approved_overtime(
            bucket,
            OvertimeApplicationModel(
                id=uuid4(), overtime_type="REGULAR",
                final_payable_minutes=0, supervisor_approved_minutes=60,
            ),
        )
        self.assertEqual(bucket.approved_overtime_minutes, 0)
        self.assertEqual(len(bucket.overtime_ids), 1)
