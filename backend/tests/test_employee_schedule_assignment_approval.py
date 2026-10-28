import unittest
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.filemaintenance.schedule.application.employee_schedule_assignment_use_case import (
    CreateEmployeeScheduleAssignmentUseCase,
    UpdateEmployeeScheduleAssignmentUseCase,
)
from app.filemaintenance.schedule.infrastructure.db_model import (
    EmployeeScheduleAssignmentModel,
    ScheduleTemplateModel,
)
from app.payroll.infrastructure.db_model import PayrollSystemParametersModel


COMPANY_ID = uuid4()
EMPLOYEE_ID = uuid4()
TEMPLATE_ID = uuid4()
ACTOR_ID = uuid4()


class FakeSession:
    def __init__(self, approval_required, assignment=None):
        self.approval_required = approval_required
        self.assignment = assignment
        self.added = None

    async def get(self, model, _key):
        if model is EmployeeScheduleAssignmentModel:
            return self.assignment
        if model is ScheduleTemplateModel:
            return SimpleNamespace(company_id=COMPANY_ID)
        if model is PayrollSystemParametersModel:
            if self.approval_required is None:
                return None
            return SimpleNamespace(
                schedule_assignment_approval_required=self.approval_required
            )
        return object()

    def add(self, model):
        self.added = model

    async def flush(self):
        return None

    async def refresh(self, _model):
        return None


class FakeUnitOfWork:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
        return None


def _assignment_payload():
    return {
        "employee_id": EMPLOYEE_ID,
        "schedule_template_id": TEMPLATE_ID,
        "rest_day_pattern_id": None,
        "assignment_type": "REGULAR",
        "effective_from": date(2026, 10, 1),
        "effective_to": None,
        "reason": None,
        "created_by": ACTOR_ID,
    }


class EmployeeScheduleAssignmentApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_creation_requires_approval_when_parameter_is_missing(self):
        session = FakeSession(approval_required=None)
        result = await CreateEmployeeScheduleAssignmentUseCase(
            FakeUnitOfWork(session)
        ).execute(_assignment_payload())

        self.assertEqual(result.status, "DRAFT")
        self.assertEqual(result.attendance_mode, "PUNCH_REQUIRED")
        self.assertIsNone(result.approved_by)
        self.assertIsNone(result.approved_at)

    async def test_creation_is_approved_by_creator_when_approval_is_disabled(self):
        session = FakeSession(approval_required=False)
        result = await CreateEmployeeScheduleAssignmentUseCase(
            FakeUnitOfWork(session)
        ).execute(_assignment_payload())

        self.assertEqual(result.status, "APPROVED")
        self.assertEqual(result.attendance_mode, "PUNCH_REQUIRED")
        self.assertEqual(result.approved_by, ACTOR_ID)
        self.assertIsNotNone(result.approved_at)

    async def test_editing_approved_assignment_stays_approved_when_disabled(self):
        assignment = SimpleNamespace(
            id=uuid4(),
            employee_id=EMPLOYEE_ID,
            schedule_template_id=TEMPLATE_ID,
            rest_day_pattern_id=None,
            assignment_type="REGULAR",
            attendance_mode="PUNCH_REQUIRED",
            effective_from=date(2026, 10, 1),
            effective_to=None,
            reason=None,
            status="APPROVED",
            approved_by=ACTOR_ID,
            approved_at=None,
            created_at=None,
            created_by=ACTOR_ID,
            updated_at=None,
            updated_by=ACTOR_ID,
            row_version=1,
            is_active=True,
        )
        session = FakeSession(approval_required=False, assignment=assignment)
        result = await UpdateEmployeeScheduleAssignmentUseCase(
            FakeUnitOfWork(session)
        ).execute(
            assignment.id,
            {
                "reason": "Updated assignment",
                "updated_by": uuid4(),
            },
        )

        self.assertEqual(result.status, "APPROVED")
        self.assertEqual(result.approved_by, result.updated_by)
        self.assertIsNotNone(result.approved_at)

    async def test_changing_attendance_mode_requires_reapproval_when_enabled(self):
        assignment = SimpleNamespace(
            id=uuid4(),
            employee_id=EMPLOYEE_ID,
            schedule_template_id=TEMPLATE_ID,
            rest_day_pattern_id=None,
            assignment_type="REGULAR",
            attendance_mode="PUNCH_REQUIRED",
            effective_from=date(2026, 10, 1),
            effective_to=None,
            reason=None,
            status="APPROVED",
            approved_by=ACTOR_ID,
            approved_at=None,
            created_at=None,
            created_by=ACTOR_ID,
            updated_at=None,
            updated_by=None,
            row_version=1,
            is_active=True,
        )
        session = FakeSession(approval_required=True, assignment=assignment)
        result = await UpdateEmployeeScheduleAssignmentUseCase(
            FakeUnitOfWork(session)
        ).execute(
            assignment.id,
            {
                "attendance_mode": "SCHEDULE_CREDITED",
                "updated_by": uuid4(),
            },
        )

        self.assertEqual(result.attendance_mode, "SCHEDULE_CREDITED")
        self.assertEqual(result.status, "DRAFT")
        self.assertIsNone(result.approved_by)
