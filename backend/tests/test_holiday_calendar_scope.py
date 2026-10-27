import unittest

from app.filemaintenance.holidays.calendar.domain.scope import (
    GeographicArea,
    holiday_applies_to_location,
)


class HolidayScopeTests(unittest.TestCase):
    def test_national_holiday_applies_across_locations(self):
        applies = holiday_applies_to_location(
            "REGULAR",
            GeographicArea(province="Albay"),
            GeographicArea(province="Cebu", city="Cebu City"),
        )

        self.assertTrue(applies)

    def test_province_scope_applies_to_locations_in_that_province(self):
        province_scope = GeographicArea(
            region="Region VII",
            province="Cebu",
            psgc_region_code="123456780",
            psgc_province_code="123456789",
        )
        municipality_locations = (
            GeographicArea(
                region="Region VII",
                province="Cebu",
                city="Cebu City",
                psgc_region_code="123456780",
                psgc_province_code="123456789",
                psgc_city_code="987654321",
            ),
            GeographicArea(
                region="Region VII",
                province="Cebu",
                city="Mandaue City",
                psgc_region_code="123456780",
                psgc_province_code="123456789",
                psgc_city_code="987654322",
            ),
        )

        for location in municipality_locations:
            with self.subTest(municipality=location.city):
                self.assertTrue(
                    holiday_applies_to_location(
                        "LOCAL",
                        province_scope,
                        location,
                    )
                )

    def test_municipality_scope_does_not_apply_to_other_municipalities(self):
        applies = holiday_applies_to_location(
            "LOCAL",
            GeographicArea(
                region="Region VII",
                province="Cebu",
                psgc_province_code="123456789",
                psgc_city_code="111111111",
                psgc_region_code="123456780",
            ),
            GeographicArea(
                region="Region VII",
                psgc_province_code="123456789",
                psgc_city_code="222222222",
                psgc_region_code="123456780",
            ),
        )

        self.assertFalse(applies)

    def test_same_province_holiday_can_apply_to_multiple_municipality_records(self):
        locations = (
            GeographicArea(
                region="Central Luzon",
                province="Pampanga",
                city="Porac",
                psgc_region_code="030000000",
                psgc_province_code="035400000",
                psgc_city_code="035416000",
            ),
            GeographicArea(
                region="Central Luzon",
                province="Pampanga",
                city="Arayat",
                psgc_region_code="030000000",
                psgc_province_code="035400000",
                psgc_city_code="035402000",
            ),
        )
        municipality_scopes = (
            GeographicArea(
                region="Central Luzon",
                province="Pampanga",
                city="Porac",
                psgc_region_code="030000000",
                psgc_province_code="035400000",
                psgc_city_code="035416000",
            ),
            GeographicArea(
                region="Central Luzon",
                province="Pampanga",
                city="Arayat",
                psgc_region_code="030000000",
                psgc_province_code="035400000",
                psgc_city_code="035402000",
            ),
        )

        for scope, location in zip(municipality_scopes, locations, strict=True):
            with self.subTest(municipality=scope.city):
                self.assertTrue(
                    holiday_applies_to_location("LOCAL", scope, location)
                )

        self.assertFalse(
            holiday_applies_to_location(
                "LOCAL",
                municipality_scopes[0],
                locations[1],
            )
        )

    def test_code_match_takes_precedence_over_matching_names(self):
        applies = holiday_applies_to_location(
            "LOCAL",
            GeographicArea(
                region="Region VII",
                province="Cebu",
                psgc_region_code="123456780",
                psgc_province_code="123456789",
            ),
            GeographicArea(
                region="Region VII",
                province="Cebu",
                psgc_region_code="123456780",
                psgc_province_code="987654321",
            ),
        )

        self.assertFalse(applies)

    def test_local_holiday_without_province_scope_does_not_apply(self):
        applies = holiday_applies_to_location(
            "LOCAL",
            GeographicArea(),
            GeographicArea(province="Cebu", city="Cebu City"),
        )

        self.assertFalse(applies)

    def test_ncr_district_scope_applies_to_all_cities_in_that_district(self):
        applies = holiday_applies_to_location(
            "LOCAL",
            GeographicArea(
                region="National Capital Region",
                psgc_region_code="130000000",
                ncr_district="NCR_2ND_DISTRICT",
            ),
            GeographicArea(
                region="National Capital Region",
                city="Mandaluyong",
                psgc_region_code="130000000",
                psgc_city_code="138030000",
                ncr_district="NCR_2ND_DISTRICT",
            ),
        )

        self.assertTrue(applies)

    def test_ncr_district_scope_does_not_apply_to_a_different_district(self):
        applies = holiday_applies_to_location(
            "LOCAL",
            GeographicArea(
                region="National Capital Region",
                psgc_region_code="130000000",
                ncr_district="NCR_2ND_DISTRICT",
            ),
            GeographicArea(
                region="National Capital Region",
                psgc_region_code="130000000",
                ncr_district="NCR_4TH_DISTRICT",
            ),
        )

        self.assertFalse(applies)

    def test_ncr_municipality_scope_is_limited_within_its_district(self):
        holiday_scope = GeographicArea(
            region="National Capital Region",
            city="Mandaluyong",
            psgc_region_code="130000000",
            psgc_city_code="138030000",
            ncr_district="NCR_2ND_DISTRICT",
        )
        matching_location = GeographicArea(
            region="National Capital Region",
            city="Mandaluyong",
            psgc_region_code="130000000",
            psgc_city_code="138030000",
            ncr_district="NCR_2ND_DISTRICT",
        )
        different_district = GeographicArea(
            region="National Capital Region",
            city="Mandaluyong",
            psgc_region_code="130000000",
            psgc_city_code="138030000",
            ncr_district="NCR_1ST_DISTRICT",
        )

        self.assertTrue(
            holiday_applies_to_location("LOCAL", holiday_scope, matching_location)
        )
        self.assertFalse(
            holiday_applies_to_location("LOCAL", holiday_scope, different_district)
        )

    def test_legacy_holiday_scope_matches_location_names(self):
        applies = holiday_applies_to_location(
            "LOCAL",
            GeographicArea(region="Central Visayas", province="Cebu", city="Cebu City"),
            GeographicArea(region="central visayas", province=" cebu ", city="CEBU CITY"),
        )

        self.assertTrue(applies)


if __name__ == "__main__":
    unittest.main()
