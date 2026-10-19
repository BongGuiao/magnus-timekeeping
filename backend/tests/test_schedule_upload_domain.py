import unittest
from datetime import date, datetime, timezone
from uuid import uuid4

from app.filemaintenance.schedule.domain.entities.schedule_upload import (
    ExistingScheduleAssignment,
    RawScheduleUploadRow,
    ScheduleTemplateRef,
    ScheduleUploadBatch,
    ScheduleUploadBatchStatus,
)
from app.filemaintenance.schedule.domain.schedule_timeline import ScheduleOverride, plan_schedule_overrides
from app.filemaintenance.schedule.domain.schedule_upload_exceptions import (
    ScheduleUploadPermissionError,
    ScheduleUploadStateError,
)
from app.filemaintenance.schedule.domain.schedule_upload_rules import (
    find_overlapping_rows,
    format_batch_no,
    parse_row,
    template_errors,
)

TODAY = date(2026, 10, 20)
EMPLOYEE_ID = uuid4()


def _raw(**values) -> RawScheduleUploadRow:
    defaults = {
        "row_no": 2,
        "employee_code": "E001",
        "schedule_code": "DAY",
        "assignment_type": "regular",
        "effective_from": "2026-11-01",
    }
    return RawScheduleUploadRow(**{**defaults, **values})


def _existing(effective_from: date, effective_to: date | None, code: str = "OLD") -> ExistingScheduleAssignment:
    return ExistingScheduleAssignment(
        id=uuid4(),
        employee_id=EMPLOYEE_ID,
        schedule_template_id=uuid4(),
        schedule_code=code,
        rest_day_pattern_id=None,
        assignment_type="REGULAR",
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _override(row_no: int, effective_from: date, effective_to: date | None) -> ScheduleOverride:
    return ScheduleOverride(row_no, EMPLOYEE_ID, effective_from, effective_to)


class ParseRowTests(unittest.TestCase):
    def test_valid_row_is_normalized(self):
        parsed = parse_row(_raw(employee_code=" E001 ", effective_to="2026-11-30", reason="  "), TODAY)

        self.assertEqual(parsed.errors, ())
        self.assertEqual(parsed.row.employee_code, "E001")
        self.assertEqual(parsed.row.assignment_type, "REGULAR")
        self.assertEqual(parsed.row.effective_to, date(2026, 11, 30))
        self.assertIsNone(parsed.row.reason)
        self.assertIsNone(parsed.row.rest_day_pattern_code)

    def test_required_fields_are_reported(self):
        parsed = parse_row(_raw(employee_code="", schedule_code="", assignment_type="", effective_from=""), TODAY)

        self.assertIsNone(parsed.row)
        self.assertEqual(len(parsed.errors), 4)

    def test_start_date_must_be_after_today(self):
        for value in ("2026-10-20", "2026-10-19"):
            with self.subTest(value=value):
                parsed = parse_row(_raw(effective_from=value), TODAY)
                self.assertIsNone(parsed.row)
                self.assertIn("on or after 2026-10-21", parsed.errors[0])
        self.assertEqual(parse_row(_raw(effective_from="2026-10-21"), TODAY).errors, ())

    def test_invalid_dates_and_ranges(self):
        self.assertIn("YYYY-MM-DD", parse_row(_raw(effective_from="11/01/2026"), TODAY).errors[0])
        self.assertIn("not a valid calendar date", parse_row(_raw(effective_from="2026-02-30"), TODAY).errors[0])
        self.assertIn(
            "effective_to must be on or after",
            parse_row(_raw(effective_to="2026-10-31"), TODAY).errors[0],
        )

    def test_assignment_type_characters(self):
        self.assertIn("letters, digits", parse_row(_raw(assignment_type="re gular"), TODAY).errors[0])


class FileRuleTests(unittest.TestCase):
    def test_overlapping_rows_for_same_employee_are_flagged(self):
        rows = [
            parse_row(_raw(row_no=2, effective_to="2026-11-10"), TODAY).row,
            parse_row(_raw(row_no=3, effective_from="2026-11-10"), TODAY).row,
            parse_row(_raw(row_no=4, employee_code="E002"), TODAY).row,
        ]

        errors = find_overlapping_rows(rows)

        self.assertEqual(set(errors), {2, 3})

    def test_adjacent_rows_do_not_overlap(self):
        rows = [
            parse_row(_raw(row_no=2, effective_to="2026-11-10"), TODAY).row,
            parse_row(_raw(row_no=3, effective_from="2026-11-11"), TODAY).row,
        ]

        self.assertEqual(find_overlapping_rows(rows), {})

    def test_template_must_be_active_and_cover_the_period(self):
        template = ScheduleTemplateRef(
            id=uuid4(),
            company_id=uuid4(),
            schedule_code="DAY",
            schedule_name="Day shift",
            status="ACTIVE",
            is_active=True,
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        )
        bounded = parse_row(_raw(effective_to="2026-12-31"), TODAY).row
        open_ended = parse_row(_raw(), TODAY).row

        self.assertEqual(template_errors(template, bounded), [])
        self.assertIn("only effective", template_errors(template, open_ended)[0])
        inactive = ScheduleTemplateRef(**{**template.__dict__, "status": "DRAFT"})
        self.assertIn("not active", template_errors(inactive, bounded)[0])

    def test_batch_number_format(self):
        self.assertEqual(format_batch_no(2026, 42), "SCH-2026-000042")


class SchedulePlanTests(unittest.TestCase):
    def test_open_ended_assignment_is_closed_the_day_before(self):
        current = _existing(date(2026, 1, 1), None)

        plan = plan_schedule_overrides([current], [_override(2, date(2026, 11, 1), None)])

        self.assertEqual(len(plan.revisions), 1)
        revision = plan.revisions[0]
        self.assertFalse(revision.retire)
        self.assertEqual((revision.effective_from, revision.effective_to), (date(2026, 1, 1), date(2026, 10, 31)))
        self.assertEqual(plan.continuations, ())
        self.assertIn("Ends schedule OLD", plan.effects_for(2)[0])

    def test_bounded_override_pauses_and_resumes_open_ended_assignment(self):
        current = _existing(date(2026, 1, 1), None)

        plan = plan_schedule_overrides([current], [_override(2, date(2026, 11, 1), date(2026, 11, 15))])

        self.assertEqual(plan.revisions[0].effective_to, date(2026, 10, 31))
        self.assertEqual(len(plan.continuations), 1)
        continuation = plan.continuations[0]
        self.assertIs(continuation.source, current)
        self.assertEqual((continuation.effective_from, continuation.effective_to), (date(2026, 11, 16), None))
        self.assertIn("resumes on 2026-11-16", plan.effects_for(2)[0])

    def test_future_assignment_inside_window_is_retired(self):
        future = _existing(date(2026, 11, 5), date(2026, 11, 10))

        plan = plan_schedule_overrides([future], [_override(2, date(2026, 11, 1), date(2026, 11, 30))])

        self.assertEqual(len(plan.revisions), 1)
        self.assertTrue(plan.revisions[0].retire)
        self.assertIn("Replaces schedule OLD", plan.effects_for(2)[0])

    def test_future_assignment_start_is_moved_after_window(self):
        future = _existing(date(2026, 11, 5), None)

        plan = plan_schedule_overrides([future], [_override(2, date(2026, 11, 1), date(2026, 11, 10))])

        revision = plan.revisions[0]
        self.assertEqual((revision.effective_from, revision.effective_to), (date(2026, 11, 11), None))
        self.assertEqual(plan.continuations, ())

    def test_multiple_rows_split_one_assignment_into_several_segments(self):
        current = _existing(date(2026, 1, 1), None)

        plan = plan_schedule_overrides(
            [current],
            [
                _override(3, date(2026, 12, 1), date(2026, 12, 5)),
                _override(2, date(2026, 11, 1), date(2026, 11, 5)),
            ],
        )

        self.assertEqual(plan.revisions[0].effective_to, date(2026, 10, 31))
        self.assertEqual(
            [(item.effective_from, item.effective_to) for item in plan.continuations],
            [(date(2026, 11, 6), date(2026, 11, 30)), (date(2026, 12, 6), None)],
        )

    def test_untouched_assignments_are_not_revised(self):
        past = _existing(date(2026, 1, 1), date(2026, 6, 30))

        plan = plan_schedule_overrides([past], [_override(2, date(2026, 11, 1), None)])

        self.assertEqual(plan.revisions, ())
        self.assertEqual(plan.effects_for(2), ())


class ScheduleUploadBatchTests(unittest.TestCase):
    def setUp(self):
        self.uploader = uuid4()
        self.batch = ScheduleUploadBatch(
            id=uuid4(),
            batch_no="SCH-2026-000001",
            supervisor_employee_id=uuid4(),
            supervisor_name="Sup",
            uploaded_by=self.uploader,
            file_name="team.csv",
            row_count=1,
            status=ScheduleUploadBatchStatus.PENDING_APPROVAL,
            submitted_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        )
        self.now = datetime(2026, 10, 20, 5, tzinfo=timezone.utc)

    def test_uploader_cannot_approve_or_reject(self):
        with self.assertRaises(ScheduleUploadPermissionError):
            self.batch.approve(self.uploader, self.now, None)
        with self.assertRaises(ScheduleUploadPermissionError):
            self.batch.reject(self.uploader, self.now, "no")

    def test_reject_requires_remarks(self):
        with self.assertRaises(ScheduleUploadStateError):
            self.batch.reject(uuid4(), self.now, "  ")

    def test_only_pending_batches_can_be_reviewed(self):
        approved = self.batch.approve(uuid4(), self.now, None)

        self.assertEqual(approved.status, ScheduleUploadBatchStatus.APPROVED)
        with self.assertRaises(ScheduleUploadStateError):
            approved.reject(uuid4(), self.now, "late")
        with self.assertRaises(ScheduleUploadStateError):
            approved.cancel(self.uploader, self.now)

    def test_only_uploader_can_cancel(self):
        with self.assertRaises(ScheduleUploadPermissionError):
            self.batch.cancel(uuid4(), self.now)
        self.assertEqual(
            self.batch.cancel(self.uploader, self.now).status, ScheduleUploadBatchStatus.CANCELLED
        )


if __name__ == "__main__":
    unittest.main()
