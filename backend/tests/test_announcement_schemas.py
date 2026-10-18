import unittest
from datetime import date, datetime
from uuid import uuid4

from pydantic import ValidationError

from app.filemaintenance.announcements.infrastructure.router import (
    AnnouncementCreateRequest,
    AnnouncementUpdateRequest,
    PH_TIMEZONE,
)


class AnnouncementSchemaTests(unittest.TestCase):
    def test_create_request_defaults_effective_start_and_open_end(self) -> None:
        today = datetime.now(PH_TIMEZONE).date()
        announcement = AnnouncementCreateRequest(title="Notice", body="Details")

        self.assertEqual(announcement.effective_from, today)
        self.assertIsNone(announcement.effective_to)
        self.assertTrue(announcement.is_active)

    def test_create_request_rejects_end_before_start(self) -> None:
        with self.assertRaises(ValidationError):
            AnnouncementCreateRequest(
                title="Notice",
                body="Details",
                effective_from=date(2026, 10, 19),
                effective_to=date(2026, 10, 18),
            )

    def test_update_request_accepts_clearing_end_date(self) -> None:
        update = AnnouncementUpdateRequest(id=uuid4(), effective_to=None)

        self.assertIsNone(update.effective_to)

    def test_update_request_rejects_null_start_date(self) -> None:
        with self.assertRaises(ValidationError):
            AnnouncementUpdateRequest(id=uuid4(), effective_from=None)

    def test_update_request_rejects_end_before_start(self) -> None:
        with self.assertRaises(ValidationError):
            AnnouncementUpdateRequest(
                id=uuid4(),
                effective_from=date(2026, 10, 19),
                effective_to=date(2026, 10, 18),
            )
