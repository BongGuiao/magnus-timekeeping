import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.filemaintenance.leaves.application.leave_records_use_case import LeaveApplicationUseCase


class SessionUnitOfWork:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class LeaveApplicationSubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_draft_moves_application_to_pending(self):
        application = SimpleNamespace(
            employee_id=uuid4(),
            leave_type_id=uuid4(),
            start_at=datetime(2026, 10, 12, 9, tzinfo=timezone.utc),
            end_at=datetime(2026, 10, 12, 10, tzinfo=timezone.utc),
            status="DRAFT",
            is_active=True,
            submitted_at=None,
            updated_by=None,
            updated_at=None,
            row_version=2,
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(
                scalar_one_or_none=lambda: application,
                all=lambda: [],
            )),
            flush=AsyncMock(),
            refresh=AsyncMock(),
        )
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(session))
        actor_id = uuid4()

        with patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._to_entity",
            side_effect=lambda model, entity_type: model,
        ), patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._validate_leave_type_company",
            new=AsyncMock(),
        ):
            result = await use_case.submit_draft_for_approval(uuid4(), actor_id)

        self.assertIs(result, application)
        self.assertEqual(application.status, "PENDING")
        self.assertEqual(application.updated_by, actor_id)
        self.assertEqual(application.row_version, 3)
        self.assertIsInstance(application.submitted_at, datetime)
        self.assertEqual(application.submitted_at.tzinfo, timezone.utc)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(application)
        session.execute.assert_awaited_once()

    async def test_submit_rejects_non_draft_application(self):
        application = SimpleNamespace(status="PENDING", is_active=True)
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: application)),
            flush=AsyncMock(),
            refresh=AsyncMock(),
        )
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(session))

        with self.assertRaisesRegex(ValueError, "Only draft leave applications"):
            await use_case.submit_draft_for_approval(uuid4(), uuid4())

        session.flush.assert_not_awaited()

    async def test_approval_updates_an_expired_updated_at_without_reading_it(self):
        class ApplicationWithExpiredUpdatedAt:
            def __init__(self):
                self.id = uuid4()
                self.employee_id = uuid4()
                self.leave_type_id = uuid4()
                self.start_at = datetime(2026, 11, 5, 9, tzinfo=timezone.utc)
                self.end_at = datetime(2026, 11, 5, 18, tzinfo=timezone.utc)
                self.status = "PENDING"
                self.row_version = 2

            @property
            def updated_at(self):
                raise RuntimeError("Expired ORM field must not be read.")

            @updated_at.setter
            def updated_at(self, value):
                self._updated_at = value

        application = ApplicationWithExpiredUpdatedAt()
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(
                scalar_one_or_none=lambda: application,
                all=lambda: [],
            )),
            flush=AsyncMock(),
            refresh=AsyncMock(),
        )
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(session))

        with patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._validate_leave_type_company",
            new=AsyncMock(),
        ), patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._post_approved_leave_charge",
            new=AsyncMock(),
        ), patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._to_entity",
            side_effect=lambda model, entity_type: model,
        ):
            result = await use_case.update_with_approval_posting(
                application.id,
                {"status": "APPROVED"},
                uuid4(),
            )

        self.assertIs(result, application)
        self.assertEqual(application.status, "APPROVED")
        self.assertEqual(application.row_version, 3)
        self.assertIsInstance(application._updated_at, datetime)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(application)
