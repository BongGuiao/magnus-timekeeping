import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import cast, func, select
from geoalchemy2 import Geography
from starlette.requests import Request

from app.attendance.application.use_case import (
    ClockAttendanceInputDTO, ClockAttendanceUseCase, ScheduleDayConfiguration, circle_contains_gps,
)
from app.attendance.domain.entities.attendance import AttendanceEntity
from app.attendance.infrastructure.clock_policy import AttendanceClockPolicy, resolve_attendance_clock_policy
from app.attendance.infrastructure.router import clock_attendance, get_my_attendance_locations
from app.auth.infrastructure.dependencies import require_role
from app.auth.domain.entities.user import Role
from app.filemaintenance.employees.infrastructure.db_model import EmployeeWfhLocationModel
from app.filemaintenance.employees.infrastructure.router import EmployeeWfhInput, save_employee_wfh


class EmployeeWfhSchemaTests(unittest.TestCase):
    def test_coordinate_ranges_and_nonfinite_values_are_rejected(self):
        for latitude, longitude in ((91, 0), (0, 181), (float("nan"), 0), (0, float("inf"))):
            with self.subTest(latitude=latitude, longitude=longitude):
                with self.assertRaises(ValidationError):
                    EmployeeWfhInput(geofence_id=uuid4(), latitude=latitude, longitude=longitude)

    def test_zero_coordinates_are_valid_and_radius_cannot_be_overridden(self):
        registration = EmployeeWfhInput(geofence_id=uuid4(), latitude=0, longitude=0)
        self.assertEqual(registration.latitude, 0)
        with self.assertRaises(ValidationError):
            EmployeeWfhInput(geofence_id=uuid4(), latitude=0, longitude=0, radius_meters=500)

    def test_registration_has_employee_and_policy_foreign_keys(self):
        targets = {
            key.target_fullname
            for column in EmployeeWfhLocationModel.__table__.c
            for key in column.foreign_keys
        }
        self.assertEqual(targets, {"hr.employees.id", "location.geofences.id"})

    def test_registration_requires_admin(self):
        with self.assertRaises(HTTPException) as error:
            require_role([Role.ADMIN])({"role": "employee"})
        self.assertEqual(error.exception.status_code, 403)

    def test_mobile_browser_is_not_native(self):
        request = Request({"type": "http", "headers": [(b"user-agent", b"Android Mobile")], "client": ("127.0.0.1", 1234)})
        policy = resolve_attendance_clock_policy(request, None)
        self.assertEqual(policy.channel, "mobile")
        self.assertTrue(policy.geofence_required)
        self.assertFalse(policy.is_native)

    def test_native_header_keeps_geofence_required(self):
        request = Request({"type": "http", "headers": [(b"x-attendance-client", b"native")], "client": ("127.0.0.1", 1234)})
        policy = resolve_attendance_clock_policy(request, None)
        self.assertTrue(policy.is_native)
        self.assertTrue(policy.geofence_required)


class WfhGeofenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.employee = SimpleNamespace(id=uuid4())
        self.fence = SimpleNamespace(
            id=uuid4(), company_id=uuid4(), location_id=uuid4(),
            radius_meters=Decimal("100"), maximum_gps_accuracy_meters=20,
            center_point="office-center", boundary_polygon=None,
        )
        self.home = SimpleNamespace(
            geofence_id=self.fence.id, latitude=14.6, longitude=121.1,
            is_active=True, row_version=2,
        )
        self.location = SimpleNamespace(
            id=self.fence.location_id, company_id=self.fence.company_id, location_name="Office",
        )
        self.session = SimpleNamespace(
            scalar=AsyncMock(return_value=self.employee),
            scalars=AsyncMock(side_effect=[
                SimpleNamespace(all=lambda: [SimpleNamespace(primary_location_id=self.fence.location_id, company_id=self.fence.company_id)]),
                SimpleNamespace(all=lambda: [self.location]),
                SimpleNamespace(all=lambda: [self.fence]),
            ]),
            get=AsyncMock(return_value=self.home),
            execute=AsyncMock(),
        )
        self.use_case = ClockAttendanceUseCase(None, None)
        self.uow = SimpleNamespace(session=self.session)
        self.user = SimpleNamespace(employee_id=self.employee.id)

    async def validate(self, allow_wfh=False, accuracy=10, latitude=14.5):
        now = datetime.now(timezone.utc)
        return await self.use_case._validate_clock_in_geofence(
            self.uow, self.user, latitude, 121.0, accuracy, now, now.date(), allow_wfh=allow_wfh,
        )

    def match(self, is_wfh):
        self.session.execute.return_value = SimpleNamespace(first=lambda: SimpleNamespace(
            id=self.fence.id, company_id=self.fence.company_id,
            location_id=self.fence.location_id, is_wfh=is_wfh,
        ))

    async def test_home_match_records_center_and_inherited_policy(self):
        self.match(True)
        metadata = await self.validate(allow_wfh=True)
        self.assertEqual(metadata["work_location_type"], "WFH")
        self.assertEqual(metadata["registered_latitude"], self.home.latitude)
        self.assertEqual(metadata["radius_meters"], 100)
        self.assertEqual(metadata["maximum_gps_accuracy_meters"], 20)
        self.assertEqual(metadata["wfh_registration_version"], 2)
        query = self.session.execute.call_args.args[0].compile()
        self.assertIn("ST_MakePoint", str(query))
        self.assertIn("radius_meters -", str(query))
        self.assertIn(self.home.latitude, query.params.values())

    async def test_web_never_reads_home_registration_and_office_still_matches(self):
        self.match(False)
        result = await self.validate()
        self.session.get.assert_not_called()
        self.assertNotIn("work_location_type", result)

    async def test_disabled_or_different_policy_has_no_home_condition(self):
        for active, same_fence in ((False, True), (True, False)):
            with self.subTest(active=active):
                self.setUp()
                self.home.is_active = active
                self.home.geofence_id = self.fence.id if same_fence else uuid4()
                self.match(False)
                await self.validate(allow_wfh=True)
                query = self.session.execute.call_args.args[0].compile()
                self.assertNotIn(self.home.latitude, query.params.values())

    async def test_clock_in_and_clock_out_both_enforce_the_same_home_check(self):
        now = datetime.now(timezone.utc)
        for clock_out in (False, True):
            with self.subTest(clock_out=clock_out):
                attendance = AttendanceEntity(
                    user_id=uuid4(), work_date=now.date(), clock_in_at=now - timedelta(hours=1),
                )
                user_repo = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
                    employee_id=self.employee.id, is_active=True, account_status="ACTIVE",
                )))
                employee_repo = SimpleNamespace(find_one=AsyncMock(return_value=SimpleNamespace(
                    id=self.employee.id, is_active=True, record_status="ACTIVE",
                )))
                enrollment_repo = SimpleNamespace(find_all=AsyncMock(return_value=[
                    SimpleNamespace(employee_id=self.employee.id, face_encoding=[1]),
                ]))
                attendance_repo = SimpleNamespace(find_all=AsyncMock(return_value=[attendance] if clock_out else []))
                uow = AsyncMock()
                uow.__aenter__.return_value = SimpleNamespace(
                    get_repo=Mock(side_effect=[user_repo, employee_repo, enrollment_repo, attendance_repo]),
                )
                face = SimpleNamespace(
                    extract_face_encoding=lambda image: [1],
                    find_best_match=lambda encoding, known: (self.employee.id, 0),
                )
                use_case = ClockAttendanceUseCase(uow, face)
                use_case._resolve_schedule_day = AsyncMock(return_value=ScheduleDayConfiguration("REG", None, None))
                use_case._validate_clock_in_geofence = AsyncMock(side_effect=ValueError("captured geofence"))
                with self.assertRaisesRegex(ValueError, "captured geofence"):
                    await use_case._execute(ClockAttendanceInputDTO(
                        image_bytes=b"face", user_id=attendance.user_id,
                        enforce_geofence=True, allow_wfh=True,
                        latitude=14.6, longitude=121.1, gps_accuracy_meters=10,
                    ))
                self.assertTrue(use_case._validate_clock_in_geofence.call_args.kwargs["allow_wfh"])

    async def test_allowed_sites_add_home_only_for_native_app(self):
        self.fence.geofence_name = "Office policy"
        self.location.location_code = "HQ"
        for native in (False, True):
            with self.subTest(native=native):
                session = SimpleNamespace(
                    execute=AsyncMock(side_effect=[
                        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [self.location])),
                        SimpleNamespace(all=lambda: [(self.fence, 14.5, 121.0)]),
                    ]),
                    get=AsyncMock(return_value=self.home),
                )
                uow = AsyncMock()
                uow.__aenter__.return_value = SimpleNamespace(session=session)
                result = await get_my_attendance_locations(
                    {"employee_id": str(self.employee.id)}, uow,
                    AttendanceClockPolicy("mobile", True, None, is_native=native),
                )
                self.assertEqual(len(result.data), 2 if native else 1)
                self.assertEqual(result.data[0].location_type, "OFFICE")
                if native:
                    self.assertEqual(result.data[1].location_type, "WFH")
                    self.assertEqual(result.data[1].geofences[0].latitude, self.home.latitude)
                    self.assertEqual(result.data[1].geofences[0].radius_meters, 100)
                else:
                    session.get.assert_not_called()

    async def test_accuracy_limit_is_still_enforced_for_home(self):
        with self.assertRaisesRegex(ValueError, "accuracy is too low"):
            await self.validate(allow_wfh=True, accuracy=21)
        self.session.execute.assert_not_called()

    async def test_invalid_gps_is_rejected_before_queries(self):
        with self.assertRaisesRegex(ValueError, "invalid GPS"):
            await self.validate(allow_wfh=True, latitude=float("nan"))
        self.session.scalar.assert_not_called()

    async def test_registration_rejects_unassigned_or_inactive_geofence(self):
        session = SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(is_active=True, record_status="ACTIVE")),
            scalar=AsyncMock(return_value=None),
        )
        uow = AsyncMock()
        uow.__aenter__.return_value = SimpleNamespace(session=session)
        with self.assertRaisesRegex(ValueError, "assigned office"):
            await save_employee_wfh(
                self.employee.id,
                EmployeeWfhInput(geofence_id=self.fence.id, latitude=14.5, longitude=121),
                {"sub": str(uuid4()), "email": "admin@example.test"}, uow, None,
            )

    async def test_admin_registration_saves_coordinates_and_preserves_policy(self):
        actor = uuid4()
        session = SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(is_active=True, record_status="ACTIVE")),
            scalar=AsyncMock(side_effect=[self.fence, None]),
            add=Mock(), flush=AsyncMock(),
        )
        uow = AsyncMock()
        uow.__aenter__.return_value = SimpleNamespace(session=session)
        with patch("app.filemaintenance.employees.infrastructure.router.log_entity_action", AsyncMock()) as audit:
            response = await save_employee_wfh(
                self.employee.id,
                EmployeeWfhInput(geofence_id=self.fence.id, latitude=14.6, longitude=121.1),
                {"sub": str(actor), "email": "admin@example.test"}, uow, None,
            )
        record = session.add.call_args.args[0]
        self.assertEqual(record.latitude, 14.6)
        self.assertEqual(record.longitude, 121.1)
        self.assertEqual(record.created_by, actor)
        self.assertEqual(response.data.geofence_id, self.fence.id)
        self.assertEqual(self.fence.radius_meters, Decimal("100"))
        self.assertEqual(self.fence.center_point, "office-center")
        audit.assert_awaited_once()

    async def test_admin_can_revoke_registration_even_when_policy_is_inactive(self):
        now = datetime.now(timezone.utc)
        actor = uuid4()
        record = EmployeeWfhLocationModel(
            employee_id=self.employee.id, geofence_id=self.fence.id, latitude=14.6, longitude=121.1,
            is_active=True, created_at=now, updated_at=now, created_by=actor, updated_by=actor, row_version=1,
        )
        session = SimpleNamespace(
            get=AsyncMock(side_effect=[self.employee, self.fence]),
            scalar=AsyncMock(return_value=record), flush=AsyncMock(),
        )
        uow = AsyncMock()
        uow.__aenter__.return_value = SimpleNamespace(session=session)
        with patch("app.filemaintenance.employees.infrastructure.router.log_entity_action", AsyncMock()):
            response = await save_employee_wfh(
                self.employee.id,
                EmployeeWfhInput(geofence_id=self.fence.id, latitude=14.6, longitude=121.1, is_active=False),
                {"sub": str(actor), "email": "admin@example.test"}, uow, None,
            )
        self.assertFalse(response.data.is_active)
        self.assertEqual(response.data.row_version, 2)

    async def test_only_signed_native_platform_can_enable_wfh(self):
        for native, platform, approved, expected in (
            (True, "ANDROID", True, True),
            (True, "IOS", True, True),
            (True, "WEB", True, False),
            (False, "ANDROID", True, False),
            (True, "ANDROID", False, False),
        ):
            with self.subTest(native=native, platform=platform, approved=approved):
                use_case = SimpleNamespace(execute=AsyncMock(side_effect=ValueError("captured")))
                proof = {"device_id": str(uuid4()), "device_uuid": "test", "platform": platform}
                consume = AsyncMock(return_value=proof) if approved else AsyncMock(side_effect=ValueError("unapproved"))
                with patch("app.attendance.infrastructure.router._read_face_image", AsyncMock(return_value=b"face")), patch(
                    "app.attendance.infrastructure.router.consume_device_challenge", consume,
                ):
                    with self.assertRaisesRegex(ValueError, "captured"):
                        await clock_attendance(
                            file=None, user_id=uuid4(), clock_out_confirmed=False,
                            latitude=14.5, longitude=121, gps_accuracy_meters=10,
                            device_challenge_id=uuid4(), device_signature="signature",
                            policy=AttendanceClockPolicy("mobile", True, None, is_native=native),
                            use_case=use_case, proof_uow=None, es_client=None,
                        )
                dto = use_case.execute.call_args.args[0]
                self.assertEqual(dto.allow_wfh, expected)
                self.assertTrue(dto.enforce_geofence)


class WfhPostgisBoundaryTests(unittest.IsolatedAsyncioTestCase):
    """Spatial and rolled-back migration checks using the project's PostGIS database."""

    async def asyncTearDown(self):
        from app.core.database import engine
        await engine.dispose()

    async def test_migration_executes_without_persisting_changes(self):
        from pathlib import Path
        from sqlalchemy import text
        from app.core.database import AsyncSessionLocal
        migration = Path(__file__).parents[1] / "sql" / "20261011_create_employee_wfh_locations.sql"
        statement = migration.read_text().replace("BEGIN;", "").replace("COMMIT;", "").strip()
        async with AsyncSessionLocal() as session:
            try:
                await session.execute(text(statement))
                exists = await session.scalar(text("SELECT to_regclass('hr.employee_wfh_locations') IS NOT NULL"))
                self.assertTrue(exists)
            finally:
                await session.rollback()

    async def test_circle_requires_gps_uncertainty_to_fit_in_radius(self):
        from app.core.database import AsyncSessionLocal
        center = cast(func.ST_SetSRID(func.ST_MakePoint(121, 14.5), 4326), Geography(srid=4326))
        async with AsyncSessionLocal() as session:
            for distance, accuracy, expected in (
                (0, 10, True), (80, 10, True), (95, 10, False), (0, 101, False), (0, 100, True),
            ):
                with self.subTest(distance=distance, accuracy=accuracy):
                    point = func.ST_Project(center, distance, 0)
                    result = await session.scalar(select(circle_contains_gps(center, point, Decimal("100"), accuracy)))
                    self.assertEqual(result, expected)
                    home_distance = await session.scalar(select(func.ST_Distance(center, point)))
                    self.assertAlmostEqual(float(home_distance), distance, places=3)
