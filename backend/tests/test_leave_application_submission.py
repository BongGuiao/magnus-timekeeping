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
            status="DRAFT",
            is_active=True,
            submitted_at=None,
            updated_by=None,
            updated_at=None,
            row_version=2,
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: application)),
            flush=AsyncMock(),
            refresh=AsyncMock(),
        )
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(session))
        actor_id = uuid4()

        with patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._to_entity",
            side_effect=lambda model, entity_type: model,
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
