import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import HTTPException

from app.attendance.application.authorized_location_use_cases import (
    ListMyAttendanceLocationsInput,
    ListMyAttendanceLocationsUseCase,
)
from app.attendance.domain.authorized_sites import build_authorized_sites
from app.attendance.domain.entities.authorized_location import (
    AssignedLocation,
    SiteGeofence,
    WfhRegistration,
)
from app.attendance.infrastructure.authorized_location_router import get_my_attendance_locations
from app.attendance.infrastructure.clock_policy import AttendanceClockPolicy

# 2026-10-12 17:00 UTC is already 2026-10-13 in Manila.
NOW = datetime(2026, 10, 12, 17, tzinfo=timezone.utc)


def make_site():
    company_id = uuid4()
    location = AssignedLocation(id=uuid4(), company_id=company_id, location_code="HQ", location_name="Head office")
    fence = SiteGeofence(
        id=uuid4(), company_id=company_id, location_id=location.id, geofence_name="Office policy",
        shape="CIRCLE", latitude=14.5, longitude=121.0, radius_meters=100.0, maximum_gps_accuracy_meters=20,
    )
    return location, fence


class FakeLocationRepository:
    def __init__(self, locations, geofences, wfh=None):
        self.locations, self.geofences, self.wfh = locations, geofences, wfh
        self.calls = []

    async def list_assigned_locations(self, employee_id, today):
        self.calls.append(("locations", employee_id, today))
        return self.locations

    async def list_active_geofences(self, locations, now):
        self.calls.append(("geofences", now))
        return self.geofences

    async def get_wfh_registration(self, employee_id):
        self.calls.append(("wfh", employee_id))
        return self.wfh


class FakeUnitOfWork:
    def __init__(self, repository):
        self.locations = repository

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


class BuildAuthorizedSitesTests(unittest.TestCase):
    def setUp(self):
        self.employee_id = uuid4()
        self.location, self.fence = make_site()
        self.home = WfhRegistration(geofence_id=self.fence.id, latitude=14.6, longitude=121.1, is_active=True)

    def test_office_sites_carry_their_active_geofences(self):
        sites = build_authorized_sites(self.employee_id, [self.location], [self.fence], None)
        self.assertEqual(len(sites), 1)
        self.assertEqual((sites[0].location_type, sites[0].location_code), ("OFFICE", "HQ"))
        self.assertEqual([fence.geofence_id for fence in sites[0].geofences], [self.fence.id])

    def test_location_without_geofences_is_still_listed(self):
        sites = build_authorized_sites(self.employee_id, [self.location], [], None)
        self.assertEqual(sites[0].geofences, [])

    def test_registered_home_is_added_as_a_circle_around_the_employees_own_coordinates(self):
        sites = build_authorized_sites(self.employee_id, [self.location], [self.fence], self.home)
        home = sites[1]
        self.assertEqual((home.location_type, home.location_code, home.location_id), ("WFH", "WFH", self.employee_id))
        geofence = home.geofences[0]
        self.assertEqual((geofence.shape, geofence.latitude, geofence.longitude), ("CIRCLE", 14.6, 121.1))
        self.assertEqual((geofence.radius_meters, geofence.maximum_gps_accuracy_meters), (100.0, 20))

    def test_inactive_or_unmatched_or_zero_radius_home_is_ignored(self):
        inactive = WfhRegistration(self.fence.id, 14.6, 121.1, is_active=False)
        other_policy = WfhRegistration(uuid4(), 14.6, 121.1, is_active=True)
        no_radius = SiteGeofence(**{**self.fence.__dict__, "radius_meters": 0.0})
        for wfh, fences in ((inactive, [self.fence]), (other_policy, [self.fence]), (self.home, [no_radius])):
            with self.subTest(wfh=wfh):
                sites = build_authorized_sites(self.employee_id, [self.location], fences, wfh)
                self.assertEqual(len(sites), 1)


class ListMyAttendanceLocationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.location, self.fence = make_site()
        self.home = WfhRegistration(self.fence.id, 14.6, 121.1, True)
        self.employee_id = uuid4()

    def use_case(self, repository):
        return ListMyAttendanceLocationsUseCase(FakeUnitOfWork(repository), clock=lambda: NOW)

    async def test_home_is_only_looked_up_and_returned_for_native_clients(self):
        for native in (False, True):
            with self.subTest(native=native):
                repository = FakeLocationRepository([self.location], [self.fence], self.home)
                sites = await self.use_case(repository).execute(
                    ListMyAttendanceLocationsInput(self.employee_id, include_wfh=native)
                )
                self.assertEqual([site.location_type for site in sites], ["OFFICE", "WFH"] if native else ["OFFICE"])
                self.assertEqual(any(call[0] == "wfh" for call in repository.calls), native)

    async def test_uses_the_philippine_date_for_assignments(self):
        repository = FakeLocationRepository([self.location], [self.fence])
        await self.use_case(repository).execute(ListMyAttendanceLocationsInput(self.employee_id, False))
        self.assertEqual(repository.calls[0], ("locations", self.employee_id, date(2026, 10, 13)))
        self.assertEqual(repository.calls[1], ("geofences", NOW))

    async def test_no_assigned_location_returns_nothing_without_further_lookups(self):
        repository = FakeLocationRepository([], [self.fence], self.home)
        sites = await self.use_case(repository).execute(ListMyAttendanceLocationsInput(self.employee_id, True))
        self.assertEqual(sites, [])
        self.assertEqual([call[0] for call in repository.calls], ["locations"])


class MyLocationsRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_policy_requests_home_and_response_maps_all_fields(self):
        location, fence = make_site()
        repository = FakeLocationRepository([location], [fence], WfhRegistration(fence.id, 14.6, 121.1, True))
        employee_id = uuid4()
        spy = MagicMock(wraps=ListMyAttendanceLocationsUseCase(FakeUnitOfWork(repository), clock=lambda: NOW))
        spy.execute = AsyncMock(wraps=spy._mock_wraps.execute)

        response = await get_my_attendance_locations(
            {"employee_id": str(employee_id)}, AttendanceClockPolicy("mobile", True, None, is_native=True), spy,
        )

        self.assertTrue(spy.execute.await_args.args[0].include_wfh)
        office, home = response.data
        self.assertEqual((office.location_type, office.geofences[0].radius_meters), ("OFFICE", 100.0))
        self.assertEqual((home.location_type, home.geofences[0].latitude), ("WFH", 14.6))

    async def test_account_without_employee_profile_is_forbidden(self):
        use_case = MagicMock(execute=AsyncMock())
        with self.assertRaises(HTTPException) as error:
            await get_my_attendance_locations({}, AttendanceClockPolicy("web", False, None), use_case)
        self.assertEqual(error.exception.status_code, 403)
        use_case.execute.assert_not_awaited()
