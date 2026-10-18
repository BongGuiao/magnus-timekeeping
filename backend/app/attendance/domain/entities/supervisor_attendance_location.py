from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Any, Literal
from uuid import UUID


@dataclass(frozen=True)
class AttendancePunchLocation:
    attendance_id: UUID
    employee_code: str
    employee_name: str
    work_date: date
    action: Literal["CLOCK_IN", "CLOCK_OUT"]
    punched_at: datetime
    latitude: float
    longitude: float
    accuracy_meters: float | None


@dataclass(frozen=True)
class SupervisorAttendanceLocations:
    company_id: UUID
    employee_code: str
    work_date: date
    punches: list[AttendancePunchLocation]


@dataclass(frozen=True)
class SupervisedTeamEmployee:
    employee_id: UUID
    employee_code: str
    employee_name: str


class EmployeeNotInSupervisorTeamError(ValueError):
    pass


class AmbiguousSupervisorCompanyError(ValueError):
    pass


def attendance_punch_locations(
    *,
    attendance_id: UUID,
    employee_code: str,
    employee_name: str,
    work_date: date,
    clock_in_at: datetime | None,
    clock_out_at: datetime | None,
    punch_metadata: dict[str, Any] | None,
) -> list[AttendancePunchLocation]:
    metadata = punch_metadata or {}
    if not isinstance(metadata, dict):
        return []
    locations: list[AttendancePunchLocation] = []
    for action, punched_at in (("CLOCK_IN", clock_in_at), ("CLOCK_OUT", clock_out_at)):
        if punched_at is None:
            continue
        action_metadata = metadata.get(action.lower(), {})
        if not isinstance(action_metadata, dict):
            continue
        report = action_metadata.get("location_report")
        if not isinstance(report, dict):
            report = action_metadata.get("geofence_validation")
        if not isinstance(report, dict):
            continue

        latitude = report.get("latitude")
        longitude = report.get("longitude")
        if (
            isinstance(latitude, bool)
            or isinstance(longitude, bool)
            or not isinstance(latitude, (int, float))
            or not isinstance(longitude, (int, float))
        ):
            continue
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (OverflowError, ValueError):
            continue
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            continue

        accuracy = report.get("accuracy_meters")
        try:
            accuracy_meters = (
                float(accuracy)
                if isinstance(accuracy, (int, float)) and not isinstance(accuracy, bool)
                else None
            )
        except (OverflowError, ValueError):
            accuracy_meters = None
        if accuracy_meters is not None and (
            not math.isfinite(accuracy_meters) or accuracy_meters <= 0
        ):
            accuracy_meters = None
        locations.append(
            AttendancePunchLocation(
                attendance_id=attendance_id,
                employee_code=employee_code,
                employee_name=employee_name,
                work_date=work_date,
                action=action,
                punched_at=punched_at,
                latitude=latitude,
                longitude=longitude,
                accuracy_meters=accuracy_meters,
            )
        )
    return locations
