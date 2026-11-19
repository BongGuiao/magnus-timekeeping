import unittest
from datetime import date
from uuid import uuid4

from app.core.generics.mapper import GenericMapper
from app.filemaintenance.holidays.holiday.application.use_case import (
    _normalize_payload,
    _validate_local_holiday_scope,
)
from app.filemaintenance.holidays.holiday.domain.entities.holiday import HolidayEntity
from app.filemaintenance.holidays.holiday.infrastructure.db_model import HolidayModel


class MunicipalityValidationTests(unittest.IsolatedAsyncioTestCase):
    def test_municipality_lists_survive_entity_model_mapping(self):
        selections = [{"code": "111111111", "name": "City"}]
        holiday = HolidayEntity(
            holiday_calendar_id=uuid4(), holiday_date=date(2026, 1, 1),
            holiday_name="Test", holiday_type="LOCAL",
            included_municipalities=selections, excluded_municipalities=selections,
        )
        model = GenericMapper.to_model(holiday, HolidayModel)
        mapped = GenericMapper.to_entity(model, HolidayEntity)
        self.assertEqual(mapped.included_municipalities, selections)
        self.assertEqual(mapped.excluded_municipalities, selections)

    def test_normalizes_and_sorts_lists(self):
        payload = _normalize_payload({
            "included_municipalities": [
                {"code": "222222222", "name": " Second "},
                {"code": "111111111", "name": "First"},
            ],
        })
        self.assertEqual(payload["included_municipalities"], [
            {"code": "111111111", "name": "First"},
            {"code": "222222222", "name": "Second"},
        ])

    def test_rejects_malformed_and_duplicate_selections(self):
        for values in (
            None,
            [{"code": None, "name": None}],
            [{"code": "bad", "name": "City"}],
            [{"code": "111111111", "name": "One"}, {"code": "111111111", "name": "Other"}],
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                _normalize_payload({"included_municipalities": values})

    async def test_lists_are_only_allowed_for_local_holidays(self):
        holiday = HolidayEntity(
            holiday_calendar_id=uuid4(), holiday_date=date(2026, 1, 1),
            holiday_name="Test", holiday_type="REGULAR",
            excluded_municipalities=[{"code": "111111111", "name": "City"}],
        )
        with self.assertRaises(ValueError):
            await _validate_local_holiday_scope(holiday)

    async def test_local_holiday_cannot_mix_legacy_city_and_include_list(self):
        holiday = HolidayEntity(
            holiday_calendar_id=uuid4(), holiday_date=date(2026, 1, 1),
            holiday_name="Test", holiday_type="LOCAL",
            region="Region VII", province="Cebu", city="City",
            included_municipalities=[{"code": "111111111", "name": "City"}],
        )
        with self.assertRaises(ValueError):
            await _validate_local_holiday_scope(holiday)
