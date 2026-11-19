from dataclasses import dataclass
from typing import Protocol

from typing_extensions import TypedDict


class Municipality(TypedDict):
    code: str | None
    name: str | None


@dataclass(frozen=True)
class GeographicArea:
    region: str | None = None
    province: str | None = None
    city: str | None = None
    psgc_region_code: str | None = None
    psgc_province_code: str | None = None
    psgc_city_code: str | None = None
    ncr_district: str | None = None


class GeographicScope(Protocol):
    region: str | None
    province: str | None
    city: str | None
    psgc_region_code: str | None
    psgc_province_code: str | None
    psgc_city_code: str | None
    ncr_district: str | None


def _matches(
    calendar_code: str | None,
    calendar_name: str | None,
    location_code: str | None,
    location_name: str | None,
) -> bool:
    if calendar_code:
        return location_code is not None and calendar_code == location_code
    if calendar_name:
        return (
            location_name is not None
            and calendar_name.strip().casefold() == location_name.strip().casefold()
        )
    return True


def holiday_applies_to_location(
    holiday_type: str,
    holiday: GeographicScope,
    location: GeographicScope,
) -> bool:
    if holiday_type != "LOCAL":
        return True

    has_geographic_scope = any(
        (
            holiday.psgc_province_code,
            holiday.province,
            holiday.ncr_district,
        )
    )
    if not has_geographic_scope:
        return False

    if holiday.ncr_district and holiday.ncr_district != location.ncr_district:
        return False

    in_area = (
        _matches(
            holiday.psgc_region_code,
            holiday.region,
            location.psgc_region_code,
            location.region,
        )
        and _matches(
            holiday.psgc_province_code,
            holiday.province,
            location.psgc_province_code,
            location.province,
        )
    )
    if not in_area:
        return False

    included: list[Municipality] = getattr(holiday, "included_municipalities", [])
    excluded: list[Municipality] = getattr(holiday, "excluded_municipalities", [])

    def matches_municipality(municipality: Municipality) -> bool:
        return _matches(
            municipality["code"], municipality["name"],
            location.psgc_city_code, location.city,
        )

    if any(
        (item["code"] and not location.psgc_city_code)
        or (not item["code"] and item["name"] and not location.city)
        for item in excluded
    ):
        return False
    if any(matches_municipality(item) for item in excluded):
        return False
    if included:
        return any(matches_municipality(item) for item in included)
    return _matches(
        holiday.psgc_city_code, holiday.city,
        location.psgc_city_code, location.city,
    )
