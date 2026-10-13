import unittest
from datetime import date, datetime, timezone
from uuid import uuid4

from app.attendance.domain.entities.attendance import AttendanceEntity
from app.attendance.infrastructure.db_model import AttendanceModel
from app.core.generics.mapper import GenericMapper


class GenericMapperJsonTests(unittest.TestCase):
    def test_json_metadata_does_not_overwrite_datetime_columns(self) -> None:
        break_time = datetime(2026, 10, 6, 7, 55, tzinfo=timezone.utc)
        metadata = {
            "clock_in": {"clock_policy": {"channel": "desktop"}},
            "device_proofs": {
                "meal_break_in_at": {
                    "device_proof": {"device_id": "device-id"},
                },
            },
        }
        entity = AttendanceEntity(
            user_id=uuid4(),
            work_date=date(2026, 10, 6),
            meal_break_in_at=break_time,
            punch_metadata=metadata,
        )

        model = GenericMapper.to_model(entity, AttendanceModel)

        self.assertEqual(model.meal_break_in_at, break_time.replace(tzinfo=None))
        self.assertEqual(model.punch_metadata, metadata)
