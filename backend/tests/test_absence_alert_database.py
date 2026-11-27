import os
import unittest
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import aiohttp
from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.attendance.application import return_to_work_screening
from app.attendance.infrastructure.absence_alert_models import AbsenceStreakAlertModel
from app.attendance.infrastructure.absence_alert_router import _visible_alerts, dismiss_absence_alert, list_absence_alerts, settings
from app.attendance.infrastructure.absence_push_models import AbsencePushDeliveryModel, MobilePushDeviceModel
from app.attendance.infrastructure.absence_push_router import PushDevice, register_push_device, unregister_push_device
from app.attendance.infrastructure.db_model import AttendanceModel
from app.auth.infrastructure.db_model import RoleModel, UserModel
from app.core.database import init_db_models
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel
from app.filemaintenance.schedule.infrastructure.db_model import (
    EmployeeScheduleAssignmentModel, ScheduleSegmentModel, ScheduleTemplateModel,
)
from app.tasks import absence_alert_tasks, absence_push_tasks

TEST_DATABASE_URL = os.getenv("ABSENCE_ALERT_TEST_DATABASE_URL")
SINCE = date(2020, 1, 1)


class SessionUnitOfWork:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


@unittest.skipUnless(TEST_DATABASE_URL, "Requires a migrated, disposable absence alert test database.")
class AbsenceAlertDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not TEST_DATABASE_URL or not (make_url(TEST_DATABASE_URL).database or "").startswith("absence_alert_test"):
            raise RuntimeError("Tests require an absence_alert_test* database.")
        init_db_models()
        self.engine = create_async_engine(TEST_DATABASE_URL)
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(bind=self.connection, expire_on_commit=False)
        self.addAsyncCleanup(self.cleanup_database)
        self.today = datetime.now(ZoneInfo("Asia/Manila")).date()
        self.now = datetime.combine(self.today, datetime.max.time(), tzinfo=ZoneInfo("Asia/Manila"))
        prefix = uuid4().hex[:8]
        self.company = CompanyModel(id=uuid4(), company_code=f"AL-{prefix}", legal_name="Alert test")
        self.other_company = CompanyModel(id=uuid4(), company_code=f"AO-{prefix}", legal_name="Other test")
        self.session.add_all([self.company, self.other_company])
        names = ("employee", "manager", "supervisor", "hr", "global_hr", "other_hr", "unrelated")
        self.employees = {
            name: EmployeeModel(id=uuid4(), employee_no=f"AL-{prefix}-{name}", first_name=name, last_name="Test")
            for name in names
        }
        self.users = {
            name: UserModel(
                id=uuid4(), employee_id=employee.id, username=f"al-{prefix}-{name}",
                password_hash="unused", account_status="ACTIVE",
            )
            for name, employee in self.employees.items()
        }
        self.session.add_all(self.employees.values())
        await self.session.flush()
        self.session.add_all(self.users.values())
        unit = OrgUnit(
            id=uuid4(), company_id=self.company.id, org_unit_code=f"AL-{prefix}",
            org_unit_name="Test", org_unit_type="DEPARTMENT", effective_from=SINCE,
            manager_employee_id=self.employees["manager"].id,
        )
        self.session.add(unit)
        await self.session.flush()
        self.session.add(EmploymentAssignmentModel(
            employee_id=self.employees["employee"].id, company_id=self.company.id,
            org_unit_id=unit.id, supervisor_employee_id=self.employees["supervisor"].id,
            employment_type="REGULAR", employee_category="REGULAR", hire_date=SINCE, effective_from=SINCE,
        ))
        role = await self.session.scalar(select(RoleModel).where(RoleModel.role_code == "HR_ADMIN"))
        if role is None:
            role = RoleModel(id=uuid4(), role_code="HR_ADMIN", role_name="HR admin", scope_type="ORG")
            self.session.add(role)
            await self.session.flush()
        for name, company_id in (
            ("hr", self.company.id), ("global_hr", None), ("other_hr", self.other_company.id),
        ):
            self.session.add(UserRoleModel(
                user_id=self.users[name].id, role_id=role.id, company_id=company_id, effective_from=SINCE,
            ))
        await self.session.flush()

    async def cleanup_database(self):
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def test_visibility_and_per_user_dismissal(self):
        alert = AbsenceStreakAlertModel(
            employee_id=self.employees["employee"].id, company_id=self.company.id,
            first_absence_date=self.today - timedelta(days=2),
            second_absence_date=self.today - timedelta(days=1), third_absence_date=self.today,
        )
        self.session.add(alert)
        await self.session.flush()
        for name in ("employee", "manager", "supervisor", "hr", "global_hr", "other_hr", "unrelated"):
            visibility = await _visible_alerts(self.session, self.users[name].id, self.today)
            found = await self.session.scalar(select(AbsenceStreakAlertModel.id).where(
                AbsenceStreakAlertModel.id == alert.id, visibility,
            ))
            self.assertEqual(found == alert.id, name not in ("other_hr", "unrelated"), name)

        uow = SessionUnitOfWork(self.session)
        with patch.object(settings, "ABSENCE_STREAK_ALERTS_ENABLED", True):
            with self.assertRaises(HTTPException) as denied:
                await dismiss_absence_alert(alert.id, Response(), {"sub": str(self.users["unrelated"].id)}, uow)
            self.assertEqual(denied.exception.status_code, 404)
            await dismiss_absence_alert(alert.id, Response(), {"sub": str(self.users["employee"].id)}, uow)
            employee_result = await list_absence_alerts(Response(), {"sub": str(self.users["employee"].id)}, uow)
            hr_result = await list_absence_alerts(Response(), {"sub": str(self.users["hr"].id)}, uow)
            unrelated_result = await list_absence_alerts(Response(), {"sub": str(self.users["unrelated"].id)}, uow)
        self.assertEqual(employee_result.data, [])
        self.assertEqual([item.id for item in hr_result.data], [alert.id])
        self.assertEqual(unrelated_result.data, [])
        role_assignment = await self.session.scalar(select(UserRoleModel).where(
            UserRoleModel.user_id == self.users["hr"].id,
        ))
        role_assignment.effective_to = self.today - timedelta(days=1)
        self.employees["manager"].is_active = False
        await self.session.flush()
        for name in ("hr", "manager"):
            visibility = await _visible_alerts(self.session, self.users[name].id, self.today)
            found = await self.session.scalar(select(AbsenceStreakAlertModel.id).where(
                AbsenceStreakAlertModel.id == alert.id, visibility,
            ))
            self.assertIsNone(found, name)

    async def add_schedule(self):
        template = ScheduleTemplateModel(
            id=uuid4(), company_id=self.company.id, schedule_code=f"AL-{uuid4().hex[:8]}",
            schedule_name="Alert test", schedule_type="FIXED", required_minutes=480,
            effective_from=SINCE, status="ACTIVE",
        )
        self.session.add(template)
        await self.session.flush()
        self.session.add_all([
            ScheduleSegmentModel(
                schedule_template_id=template.id, segment_sequence=1, segment_type="WORK",
                start_time=time(9), end_time=time(17), paid_minutes=480,
            ),
            EmployeeScheduleAssignmentModel(
                employee_id=self.employees["employee"].id, schedule_template_id=template.id,
                assignment_type="REGULAR", effective_from=SINCE, status="APPROVED",
            ),
        ])

    async def test_real_schedule_and_attendance_records_are_screened(self):
        await self.add_schedule()
        dates = [self.today - timedelta(days=offset) for offset in (2, 1, 0)]
        self.session.add_all([
            AttendanceModel(user_id=self.users["employee"].id, work_date=work_date, is_absent=True, record_status="VALID")
            for work_date in dates
        ])
        await self.session.flush()
        actual = await return_to_work_screening.load_current_absence_streak(
            self.session, self.users["employee"].id, self.employees["employee"].id,
            dates[0], self.today, self.now,
        )
        self.assertEqual(actual, tuple(dates))

    async def test_alert_is_created_at_eight_hours_after_third_shift_start(self):
        await self.add_schedule()
        dates = [self.today - timedelta(days=offset) for offset in (2, 1, 0)]
        self.session.add_all([
            AttendanceModel(user_id=self.users["employee"].id, work_date=work_date, is_absent=True, record_status="VALID")
            for work_date in dates
        ])
        await self.session.flush()
        threshold = datetime.combine(self.today, time(9), tzinfo=ZoneInfo("Asia/Manila")) + timedelta(hours=8)
        fake_engine = SimpleNamespace(dispose=AsyncMock())
        fake_factory = lambda: AsyncSession(bind=self.connection, expire_on_commit=False)
        with (
            patch.object(absence_alert_tasks, "create_async_engine", return_value=fake_engine),
            patch.object(absence_alert_tasks, "async_sessionmaker", return_value=fake_factory),
            patch.object(absence_alert_tasks.settings, "ABSENCE_STREAK_PUSH_ENABLED", False),
        ):
            before = await absence_alert_tasks.refresh_absence_alerts_at(threshold - timedelta(microseconds=1))
            at_threshold = await absence_alert_tasks.refresh_absence_alerts_at(threshold)
            after = await absence_alert_tasks.refresh_absence_alerts_at(threshold + timedelta(minutes=5))
        self.assertEqual((before["created"], at_threshold["created"], after["created"]), (0, 1, 0))

    async def register_device(self, name):
        token = f"ExponentPushToken[test_{name}]"
        claims = {
            "sub": str(self.users[name].id),
            "exp": int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp()),
        }
        await register_push_device(PushDevice(token=token), Response(), claims, SessionUnitOfWork(self.session))
        return token, claims

    async def test_push_is_enqueued_only_for_current_recipients(self):
        await self.add_schedule()
        with (
            patch.object(settings, "ABSENCE_STREAK_ALERTS_ENABLED", True),
            patch.object(settings, "ABSENCE_STREAK_PUSH_ENABLED", True),
        ):
            for name in ("employee", "manager", "supervisor", "hr", "global_hr", "other_hr", "unrelated"):
                await self.register_device(name)
            dates = [self.today - timedelta(days=offset) for offset in (2, 1, 0)]
            self.session.add_all([
                AttendanceModel(user_id=self.users["employee"].id, work_date=work_date, is_absent=True, record_status="VALID")
                for work_date in dates
            ])
            await self.session.flush()
            fake_engine = SimpleNamespace(dispose=AsyncMock())
            fake_factory = lambda: AsyncSession(bind=self.connection, expire_on_commit=False)
            with (
                patch.object(absence_alert_tasks, "create_async_engine", return_value=fake_engine),
                patch.object(absence_alert_tasks, "async_sessionmaker", return_value=fake_factory),
            ):
                first = await absence_alert_tasks.refresh_absence_alerts_at(self.now)
                second = await absence_alert_tasks.refresh_absence_alerts_at(self.now)
            self.assertEqual((first["created"], second["created"]), (1, 0))
            recipients = set((await self.session.scalars(select(AbsencePushDeliveryModel.user_id))).all())
            self.assertEqual(recipients, {
                self.users[name].id for name in ("employee", "manager", "supervisor", "hr", "global_hr")
            })

    async def test_push_registration_and_delivery_rechecks_authorization(self):
        alert = AbsenceStreakAlertModel(
            employee_id=self.employees["employee"].id, company_id=self.company.id,
            first_absence_date=self.today - timedelta(days=2),
            second_absence_date=self.today - timedelta(days=1), third_absence_date=self.today,
        )
        self.session.add(alert)
        await self.session.flush()
        with (
            patch.object(settings, "ABSENCE_STREAK_ALERTS_ENABLED", True),
            patch.object(settings, "ABSENCE_STREAK_PUSH_ENABLED", True),
        ):
            token, claims = await self.register_device("supervisor")
            await self.register_device("supervisor")
            delivery = await self.session.scalar(select(AbsencePushDeliveryModel).where(
                AbsencePushDeliveryModel.user_id == self.users["supervisor"].id,
            ))
            device = await self.session.scalar(select(MobilePushDeviceModel).where(MobilePushDeviceModel.token == token))
            self.assertEqual(len((await self.session.scalars(select(AbsencePushDeliveryModel))).all()), 1)
            post = AsyncMock(return_value={"data": {"status": "ok", "id": "test-receipt"}})
            with patch.object(absence_push_tasks, "_post", post):
                await absence_push_tasks._process(self.session, None, delivery, device, datetime.now(timezone.utc))
            self.assertEqual(delivery.state, "RECEIPT")
            payload = post.await_args.args[2]
            self.assertNotIn("employee", str(payload).lower())
            self.assertNotIn(str(alert.id), str(payload))
            with patch.object(absence_push_tasks, "_post", AsyncMock(return_value={
                "data": {"test-receipt": {"status": "error", "details": {"error": "DeviceNotRegistered"}}},
            })):
                await absence_push_tasks._process(self.session, None, delivery, device, datetime.now(timezone.utc))
            self.assertEqual(delivery.state, "FAILED")
            self.assertLessEqual(device.session_expires_at, datetime.now(timezone.utc))
            await self.register_device("supervisor")
            await self.session.refresh(device)
            self.assertGreater(device.session_expires_at, datetime.now(timezone.utc))
            delivery.state = "PENDING"
            assignment = await self.session.scalar(select(EmploymentAssignmentModel).where(
                EmploymentAssignmentModel.employee_id == self.employees["employee"].id,
            ))
            assignment.supervisor_employee_id = None
            await self.session.flush()
            post = AsyncMock()
            with patch.object(absence_push_tasks, "_post", post):
                await absence_push_tasks._process(self.session, None, delivery, device, datetime.now(timezone.utc))
            self.assertEqual(delivery.state, "CANCELLED")
            post.assert_not_awaited()
            await unregister_push_device(PushDevice(token=token), Response(), claims, SessionUnitOfWork(self.session))
            await self.session.refresh(device)
            self.assertLessEqual(device.session_expires_at, datetime.now(timezone.utc))

    async def test_push_network_failure_is_retried(self):
        alert = AbsenceStreakAlertModel(
            employee_id=self.employees["employee"].id, company_id=self.company.id,
            first_absence_date=self.today - timedelta(days=2),
            second_absence_date=self.today - timedelta(days=1), third_absence_date=self.today,
        )
        self.session.add(alert)
        await self.session.flush()
        with (
            patch.object(settings, "ABSENCE_STREAK_ALERTS_ENABLED", True),
            patch.object(settings, "ABSENCE_STREAK_PUSH_ENABLED", True),
        ):
            await self.register_device("employee")
            fake_engine = SimpleNamespace(dispose=AsyncMock())
            fake_factory = lambda: AsyncSession(bind=self.connection, expire_on_commit=False)
            now = datetime.now(timezone.utc) + timedelta(seconds=1)
            with (
                patch.object(absence_push_tasks, "create_async_engine", return_value=fake_engine),
                patch.object(absence_push_tasks, "async_sessionmaker", return_value=fake_factory),
                patch.object(absence_push_tasks, "_post", new=AsyncMock(side_effect=aiohttp.ClientConnectionError())),
            ):
                self.assertEqual(await absence_push_tasks.process_absence_push_at(now), 1)
            delivery = await self.session.scalar(select(AbsencePushDeliveryModel).where(
                AbsencePushDeliveryModel.user_id == self.users["employee"].id,
            ))
            await self.session.refresh(delivery)
            self.assertEqual(delivery.state, "PENDING")
            self.assertEqual(delivery.attempts, 1)
            self.assertGreater(delivery.next_attempt_at, now)

    async def test_push_sender_checks_successful_receipt(self):
        alert = AbsenceStreakAlertModel(
            employee_id=self.employees["employee"].id, company_id=self.company.id,
            first_absence_date=self.today - timedelta(days=2),
            second_absence_date=self.today - timedelta(days=1), third_absence_date=self.today,
        )
        self.session.add(alert)
        await self.session.flush()
        with (
            patch.object(settings, "ABSENCE_STREAK_ALERTS_ENABLED", True),
            patch.object(settings, "ABSENCE_STREAK_PUSH_ENABLED", True),
        ):
            await self.register_device("employee")
            fake_engine = SimpleNamespace(dispose=AsyncMock())
            fake_factory = lambda: AsyncSession(bind=self.connection, expire_on_commit=False)
            now = datetime.now(timezone.utc) + timedelta(seconds=1)
            responses = AsyncMock(side_effect=[
                {"data": {"status": "ok", "id": "test-receipt"}},
                {"data": {"test-receipt": {"status": "ok"}}},
            ])
            with (
                patch.object(absence_push_tasks, "create_async_engine", return_value=fake_engine),
                patch.object(absence_push_tasks, "async_sessionmaker", return_value=fake_factory),
                patch.object(absence_push_tasks, "_post", responses),
            ):
                self.assertEqual(await absence_push_tasks.process_absence_push_at(now), 1)
                self.assertEqual(await absence_push_tasks.process_absence_push_at(now + timedelta(minutes=16)), 1)
            delivery = await self.session.scalar(select(AbsencePushDeliveryModel).where(
                AbsencePushDeliveryModel.user_id == self.users["employee"].id,
            ))
            self.assertEqual(delivery.state, "SENT")
            self.assertEqual(responses.await_count, 2)

    async def test_screening_is_idempotent_and_resolves_corrected_absence(self):
        await self.add_schedule()
        dates = [self.today - timedelta(days=offset) for offset in (2, 1, 0)]
        records = [
            AttendanceModel(user_id=self.users["employee"].id, work_date=work_date, is_absent=True, record_status="VALID")
            for work_date in dates
        ]
        self.session.add_all(records)
        await self.session.flush()
        fake_engine = SimpleNamespace(dispose=AsyncMock())
        fake_factory = lambda: AsyncSession(bind=self.connection, expire_on_commit=False)

        with (
            patch.object(absence_alert_tasks, "create_async_engine", return_value=fake_engine),
            patch.object(absence_alert_tasks, "async_sessionmaker", return_value=fake_factory),
        ):
            first = await absence_alert_tasks.refresh_absence_alerts_at(self.now)
            second = await absence_alert_tasks.refresh_absence_alerts_at(self.now)
            self.assertEqual(first["created"], 1)
            self.assertEqual(second["created"], 0)
            self.session.add(AttendanceModel(
                user_id=self.users["employee"].id, work_date=self.today + timedelta(days=1),
                is_absent=True, record_status="VALID",
            ))
            await self.session.flush()
            next_day = self.now + timedelta(days=1)
            extended = await absence_alert_tasks.refresh_absence_alerts_at(next_day)
            self.assertEqual(extended["created"], 0)
            duplicate = AttendanceModel(
                user_id=self.users["employee"].id, work_date=dates[1],
                is_absent=True, record_status="VALID",
            )
            self.session.add(duplicate)
            await self.session.flush()
            ambiguous = await absence_alert_tasks.refresh_absence_alerts_at(next_day)
            self.assertEqual(ambiguous["resolved"], 0)
            records[1].record_status = "VOID"
            await self.session.flush()
            replacement = await absence_alert_tasks.refresh_absence_alerts_at(next_day)
            self.assertEqual(replacement["resolved"], 0)
            await self.session.delete(duplicate)
            await self.session.flush()
            corrected = await absence_alert_tasks.refresh_absence_alerts_at(next_day)
            self.assertEqual(corrected["resolved"], 1)
        alert = await self.session.scalar(select(AbsenceStreakAlertModel).where(
            AbsenceStreakAlertModel.employee_id == self.employees["employee"].id,
        ))
        self.assertIsNotNone(alert)
        self.assertIsNotNone(alert.resolved_at)
