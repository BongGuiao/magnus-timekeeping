from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.attendance.application.authorized_location_use_cases import (
    ListMyAttendanceLocationsInput,
    ListMyAttendanceLocationsUseCase,
)
from app.attendance.domain.entities.authorized_location import AuthorizedLocation
from app.attendance.infrastructure.clock_policy import AttendanceClockPolicy, resolve_attendance_clock_policy
from app.attendance.infrastructure.dependencies import get_list_my_attendance_locations_use_case
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.generics.mapper import ResponseEnvelope

router = APIRouter()


class AuthorizedGeofenceSchema(BaseModel):
    geofence_id: UUID
    geofence_name: str
    shape: Literal["CIRCLE", "POLYGON"]
    latitude: float | None
    longitude: float | None
    radius_meters: float | None
    maximum_gps_accuracy_meters: int


class AuthorizedLocationSchema(BaseModel):
    company_id: UUID
    location_id: UUID
    location_code: str
    location_name: str
    geofences: list[AuthorizedGeofenceSchema]
    location_type: Literal["OFFICE", "WFH"] = "OFFICE"


def _schema(site: AuthorizedLocation) -> AuthorizedLocationSchema:
    return AuthorizedLocationSchema(
        company_id=site.company_id,
        location_id=site.location_id,
        location_code=site.location_code,
        location_name=site.location_name,
        location_type=site.location_type,
        geofences=[
            AuthorizedGeofenceSchema(
                geofence_id=fence.geofence_id,
                geofence_name=fence.geofence_name,
                shape=fence.shape,
                latitude=fence.latitude,
                longitude=fence.longitude,
                radius_meters=fence.radius_meters,
                maximum_gps_accuracy_meters=fence.maximum_gps_accuracy_meters,
            )
            for fence in site.geofences
        ],
    )


@router.get("/my-locations", response_model=ResponseEnvelope[list[AuthorizedLocationSchema]])
async def get_my_attendance_locations(
    claims: dict = Depends(get_current_user_claims),
    policy: AttendanceClockPolicy = Depends(resolve_attendance_clock_policy),
    use_case: ListMyAttendanceLocationsUseCase = Depends(get_list_my_attendance_locations_use_case),
):
    """Sites where the signed-in employee may punch under their active geofence assignments.

    Informational only; the clock endpoint re-validates the GPS point server-side.
    """
    try:
        employee_id = UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to an employee profile.",
        ) from error

    sites = await use_case.execute(
        ListMyAttendanceLocationsInput(employee_id=employee_id, include_wfh=policy.is_native)
    )
    return ResponseEnvelope[list[AuthorizedLocationSchema]](data=[_schema(site) for site in sites])
