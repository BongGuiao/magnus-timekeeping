import unittest
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.attendance.domain.entities.attendance import AttendanceEntity
from app.attendance.infrastructure.db_model import AttendanceModel
from app.core.database import Base
from app.core.generics.mapper import GenericMapper


class NaiveTimestampModel(Base):
    __tablename__ = "generic_mapper_naive_timestamp_test"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False))


class GenericMapperJsonTests(unittest.TestCase):
    def test_timezone_aware_values_are_preserved_for_timezone_columns(self) -> None:
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
        self.assertEqual(model.meal_break_in_at, break_time)
        self.assertEqual(model.punch_metadata, metadata)

    def test_timezone_is_stripped_for_timezone_naive_columns(self) -> None:
        timestamp = datetime(2026, 10, 6, 7, 55, tzinfo=timezone.utc)
        entity = type("TimestampEntity", (), {"timestamp": timestamp})()

        model = GenericMapper.to_model(entity, NaiveTimestampModel)

        self.assertEqual(model.timestamp, timestamp.replace(tzinfo=None))
