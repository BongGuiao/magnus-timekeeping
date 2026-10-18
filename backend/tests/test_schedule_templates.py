import unittest
from datetime import date
from uuid import uuid4

from pydantic import ValidationError

from app.filemaintenance.schedule.application.use_case import (
    ScheduleTemplateValidationError,
    _validate_effective_period,
)
from app.filemaintenance.schedule.application.rest_day_pattern_use_case import (
    RestDayPatternValidationError,
    validate_pattern_days,
)
from app.filemaintenance.schedule.application.employee_schedule_assignment_use_case import (
    EmployeeScheduleAssignmentValidationError,
    _validate_period as validate_schedule_assignment_period,
)
from app.filemaintenance.schedule.infrastructure.db_model import (
    EmployeeScheduleAssignmentModel,
    RestDayPatternDayModel,
    RestDayPatternModel,
    ScheduleSegmentModel,
    ScheduleTemplateModel,
)
from app.filemaintenance.schedule.infrastructure.router import (
    CreateScheduleSegmentSchema,
    CreateScheduleTemplateSchema,
    UpdateScheduleSegmentSchema,
    UpdateScheduleTemplateSchema,
)
from app.filemaintenance.schedule.infrastructure.rest_day_pattern_router import (
    RestDayPatternInput,
)
from app.filemaintenance.schedule.infrastructure.employee_schedule_assignment_router import (
    CreateEmployeeScheduleAssignmentSchema,
    UpdateEmployeeScheduleAssignmentSchema,
)


class ScheduleTemplateSchemaTests(unittest.TestCase):
    def test_create_schema_applies_table_defaults(self) -> None:
        payload = CreateScheduleTemplateSchema(
            company_id=uuid4(),
            schedule_code="DAY",
            schedule_name="Day Shift",
            schedule_type="FIXED",
            required_minutes=480,
            effective_from=date(2026, 1, 1),
        )

        self.assertEqual(payload.grace_minutes, 0)
        self.assertEqual(payload.grace_method, "NONE")
        self.assertFalse(payload.is_overnight)
        self.assertTrue(payload.ot_eligible)
        self.assertFalse(payload.pre_shift_ot_allowed)
        self.assertEqual(payload.minimum_ot_minutes, 0)
        self.assertEqual(payload.status, "DRAFT")

    def test_create_schema_rejects_invalid_type_and_minute_values(self) -> None:
        base = {
            "company_id": uuid4(),
            "schedule_code": "DAY",
            "schedule_name": "Day Shift",
            "schedule_type": "INVALID",
            "required_minutes": 480,
            "effective_from": date(2026, 1, 1),
        }
        with self.assertRaises(ValidationError):
            CreateScheduleTemplateSchema(**base)

        base["schedule_type"] = "FIXED"
        base["required_minutes"] = 0
        with self.assertRaises(ValidationError):
            CreateScheduleTemplateSchema(**base)

    def test_create_and_merged_update_reject_invalid_effective_period(self) -> None:
        with self.assertRaises(ValidationError):
            CreateScheduleTemplateSchema(
                company_id=uuid4(),
                schedule_code="DAY",
                schedule_name="Day Shift",
                schedule_type="FIXED",
                required_minutes=480,
                effective_from=date(2026, 1, 2),
                effective_to=date(2026, 1, 1),
            )

        with self.assertRaisesRegex(ScheduleTemplateValidationError, "effective_to"):
            _validate_effective_period(date(2026, 1, 2), date(2026, 1, 1))

    def test_update_schema_allows_clearing_optional_fields(self) -> None:
        payload = UpdateScheduleTemplateSchema(
            id=uuid4(),
            holiday_calendar_id=None,
            effective_to=None,
        )

        self.assertIsNone(payload.holiday_calendar_id)
        self.assertIsNone(payload.effective_to)

    def test_update_schema_rejects_null_required_fields_and_extra_fields(self) -> None:
        with self.assertRaises(ValidationError):
            UpdateScheduleTemplateSchema(id=uuid4(), required_minutes=None)
        with self.assertRaises(ValidationError):
            UpdateScheduleTemplateSchema(id=uuid4(), created_by=uuid4())

    def test_model_uses_schedule_schema_and_expected_foreign_keys(self) -> None:
        self.assertEqual(ScheduleTemplateModel.__table__.schema, "schedule")
        targets = {
            element.target_fullname
            for constraint in ScheduleTemplateModel.__table__.foreign_key_constraints
            for element in constraint.elements
        }
        self.assertEqual(
            targets,
            {"core.companies.id", "core.holiday_calendars.id"},
        )


class ScheduleSegmentSchemaTests(unittest.TestCase):
    def test_create_schema_applies_segment_defaults(self) -> None:
        payload = CreateScheduleSegmentSchema(
            segment_sequence=1,
            segment_type="WORK",
            start_time="08:00",
            end_time="12:00",
        )

        self.assertEqual(payload.end_day_offset, 0)
        self.assertEqual(payload.paid_minutes, 0)
        self.assertFalse(payload.punch_required)
        self.assertFalse(payload.auto_deduct)
        self.assertEqual(payload.flex_start_minutes, 0)

    def test_create_schema_accepts_paid_overtime_break_slot(self) -> None:
        payload = CreateScheduleSegmentSchema(
            segment_sequence=2,
            segment_type="PAID_BREAK",
            start_time="17:00",
            end_time="21:00",
            break_slot="OT_BREAK",
            work_segment_sequence=1,
            break_minutes=15,
        )
        self.assertEqual(payload.break_slot, "OT_BREAK")

    def test_segment_schema_rejects_invalid_values(self) -> None:
        with self.assertRaises(ValidationError):
            CreateScheduleSegmentSchema(
                segment_sequence=1,
                segment_type="REST",
                start_time="08:00",
                end_time="12:00",
            )
        with self.assertRaises(ValidationError):
            CreateScheduleSegmentSchema(
                segment_sequence=1,
                segment_type="WORK",
                start_time="08:00",
                end_time="12:00",
                end_day_offset=3,
            )
        with self.assertRaises(ValidationError):
            UpdateScheduleSegmentSchema(paid_minutes=None)

    def test_segment_model_relates_to_schedule_template_with_cascade(self) -> None:
        self.assertEqual(ScheduleSegmentModel.__table__.schema, "schedule")
        fk = next(iter(ScheduleSegmentModel.__table__.foreign_keys))
        self.assertEqual(fk.target_fullname, "schedule.schedule_templates.id")
        self.assertEqual(fk.ondelete, "CASCADE")
        self.assertIn(
            ("schedule_template_id", "segment_sequence"),
            {
                tuple(column.name for column in constraint.columns)
                for constraint in ScheduleSegmentModel.__table__.constraints
                if getattr(constraint, "name", None) == "uq_schedule_segments_template_sequence"
            },
        )


class RestDayPatternSchemaTests(unittest.TestCase):
    def test_pattern_schema_requires_a_complete_cycle(self) -> None:
        payload = RestDayPatternInput(
            pattern_code="5-2",
            pattern_name="Five workdays, two rest days",
            cycle_length_days=2,
            days=[
                {"cycle_day_no": 1, "is_workday": True},
                {"cycle_day_no": 2, "is_workday": False},
            ],
        )
        self.assertEqual(payload.pattern_code, "5-2")
        self.assertEqual(len(payload.days), 2)

        with self.assertRaises(ValidationError):
            RestDayPatternInput(
                pattern_code=" ",
                pattern_name="Invalid",
                cycle_length_days=2,
                days=[
                    {"cycle_day_no": 1, "is_workday": True},
                    {"cycle_day_no": 2, "is_workday": False},
                ],
            )

    def test_pattern_days_must_cover_cycle_once(self) -> None:
        validate_pattern_days(
            3,
            [
                {"cycle_day_no": 1},
                {"cycle_day_no": 2},
                {"cycle_day_no": 3},
            ],
        )
        with self.assertRaisesRegex(RestDayPatternValidationError, "one day"):
            validate_pattern_days(
                3,
                [
                    {"cycle_day_no": 1},
                    {"cycle_day_no": 1},
                    {"cycle_day_no": 3},
                ],
            )

    def test_models_use_schedule_schema_and_cascading_pattern_reference(self) -> None:
        self.assertEqual(RestDayPatternModel.__table__.schema, "schedule")
        self.assertEqual(RestDayPatternDayModel.__table__.schema, "schedule")
        foreign_keys = {
            (key.target_fullname, key.ondelete)
            for key in RestDayPatternDayModel.__table__.foreign_keys
        }
        self.assertEqual(
            foreign_keys,
            {
                ("schedule.rest_day_patterns.id", "CASCADE"),
                ("schedule.schedule_templates.id", None),
            },
        )


class EmployeeScheduleAssignmentTests(unittest.TestCase):
    def test_create_schema_requires_schedule_and_employee_fields(self) -> None:
        payload = CreateEmployeeScheduleAssignmentSchema(
            employee_id=uuid4(),
            schedule_template_id=uuid4(),
            assignment_type="REGULAR",
            effective_from=date(2026, 1, 1),
        )
        self.assertIsNone(payload.rest_day_pattern_id)
        with self.assertRaises(ValidationError):
            CreateEmployeeScheduleAssignmentSchema(
                employee_id=uuid4(),
                schedule_template_id=uuid4(),
                assignment_type=" ",
                effective_from=date(2026, 1, 1),
            )

    def test_update_rejects_client_controlled_approval_fields(self) -> None:
        with self.assertRaises(ValidationError):
            UpdateEmployeeScheduleAssignmentSchema(status="APPROVED")
        with self.assertRaises(ValidationError):
            UpdateEmployeeScheduleAssignmentSchema(approved_by=uuid4())

    def test_effective_dates_must_be_ordered(self) -> None:
        with self.assertRaisesRegex(EmployeeScheduleAssignmentValidationError, "effective_to"):
            validate_schedule_assignment_period(date(2026, 2, 1), date(2026, 1, 31))

    def test_model_has_expected_relationships_and_date_check(self) -> None:
        model = EmployeeScheduleAssignmentModel
        self.assertEqual(model.__table__.schema, "schedule")
        targets = {
            foreign_key.target_fullname
            for foreign_key in model.__table__.foreign_keys
        }
        self.assertEqual(
            targets,
            {
                "hr.employees.id",
                "schedule.schedule_templates.id",
                "schedule.rest_day_patterns.id",
                "identity.users.id",
            },
        )
        self.assertIn(
            "ck_employee_schedule_assignments_effective_dates",
            {constraint.name for constraint in model.__table__.constraints},
        )
