from dataclasses import dataclass
from typing import Protocol


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

    return (
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
        and _matches(
            holiday.psgc_city_code,
            holiday.city,
            location.psgc_city_code,
            location.city,
        )
    )
