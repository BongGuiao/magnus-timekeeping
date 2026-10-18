from typing import Optional, Sequence
from uuid import UUID

from app.attendance.domain.entities.authorized_location import (
    AssignedLocation,
    AuthorizedGeofence,
    AuthorizedLocation,
    SiteGeofence,
    WfhRegistration,
)


def build_authorized_sites(
    employee_id: UUID,
    locations: Sequence[AssignedLocation],
    geofences: Sequence[SiteGeofence],
    wfh: Optional[WfhRegistration],
) -> list[AuthorizedLocation]:
    """Office sites for each assigned location, plus the registered home site when usable."""
    fences_by_location: dict[UUID, list[AuthorizedGeofence]] = {}
    for fence in geofences:
        if not any(fence.id in location.authorized_geofence_ids for location in locations):
            continue
        fences_by_location.setdefault(fence.location_id, []).append(
            AuthorizedGeofence(
                geofence_id=fence.id,
                geofence_name=fence.geofence_name,
                shape=fence.shape,
                latitude=fence.latitude,
                longitude=fence.longitude,
                radius_meters=fence.radius_meters,
                maximum_gps_accuracy_meters=fence.maximum_gps_accuracy_meters,
            )
        )

    sites = [
        AuthorizedLocation(
            company_id=location.company_id,
            location_id=location.id,
            location_code=location.location_code,
            location_name=location.location_name,
            geofences=fences_by_location.get(location.id, []),
        )
        for location in locations
    ]
    if wfh is not None and wfh.is_active:
        policy = next(
            (
                fence for fence in geofences
                if fence.id == wfh.geofence_id and fence.radius_meters is not None and fence.radius_meters > 0
            ),
            None,
        )
        if policy is not None:
            sites.append(
                AuthorizedLocation(
                    company_id=policy.company_id,
                    location_id=employee_id,
                    location_code="WFH",
                    location_name="Registered WFH location",
                    location_type="WFH",
                    geofences=[
                        AuthorizedGeofence(
                            geofence_id=policy.id,
                            geofence_name=policy.geofence_name,
                            shape="CIRCLE",
                            latitude=wfh.latitude,
                            longitude=wfh.longitude,
                            radius_meters=policy.radius_meters,
                            maximum_gps_accuracy_meters=policy.maximum_gps_accuracy_meters,
                        )
                    ],
                )
            )
    return sites
