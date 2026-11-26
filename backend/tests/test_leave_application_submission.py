import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.filemaintenance.leaves.application.leave_records_use_case import LeaveApplicationUseCase
from app.filemaintenance.leaves.infrastructure.leave_records_router import (
    LeaveApplicationCreateSchema,
    applications_router,
    check_leave_rest_days,
    create_leave_application,
    submit_leave_application,
    update_leave_application,
    review_holiday_leave,
)


class SessionUnitOfWork:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class LeaveApplicationSubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_leave_writes_reject_a_stale_employee_link(self):
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            permission_codes=["leave.submit"], role_codes=["EMPLOYEE"], employee_id=uuid4(),
        )))
        claims = {"sub": str(uuid4()), "employee_id": str(uuid4())}
        for endpoint in (create_leave_application, update_leave_application, submit_leave_application, check_leave_rest_days):
            route = next(route for route in applications_router.routes if route.endpoint is endpoint)
            checker = next(dependency.call for dependency in route.dependant.dependencies if dependency.name == "claims")
            with self.subTest(endpoint=endpoint.__name__), self.assertRaises(HTTPException) as error:
                await checker(claims, authorization)
            self.assertEqual(error.exception.status_code, 403)

    async def test_rest_day_check_uses_own_schedule_and_exclusive_end(self):
        employee_id = uuid4()
        claims = {"sub": str(uuid4()), "employee_id": str(employee_id), "email": "test@example.invalid"}
        session = object()
        tz = ZoneInfo("Asia/Manila")
        schedules = [
            SimpleNamespace(work_type="REG", schedule_context={"schedule_assignment_id": "normal"}),
            SimpleNamespace(work_type="REST", schedule_context={"schedule_assignment_id": "normal"}),
            SimpleNamespace(work_type="REG", schedule_context=None),
            SimpleNamespace(work_type="REG", schedule_context={"emergency_schedule_request_id": "approved"}),
        ]
        with patch(
            "app.filemaintenance.leaves.infrastructure.leave_records_router.resolve_schedule_day",
            new=AsyncMock(side_effect=schedules),
        ) as resolve:
            response = await check_leave_rest_days(
                datetime(2026, 12, 4, 9, tzinfo=tz), datetime(2026, 12, 8, 0, tzinfo=tz),
                claims, SessionUnitOfWork(session),
            )
        self.assertEqual(response.data.rest_days, [date(2026, 12, 5)])
        self.assertEqual(response.data.unchecked_dates, [date(2026, 12, 6)])
        self.assertEqual([call.args for call in resolve.await_args_list], [
            (session, employee_id, date(2026, 12, day)) for day in (4, 5, 6, 7)
        ])

    async def test_rest_day_check_rejects_invalid_or_excessive_ranges(self):
        claims = {"sub": str(uuid4()), "employee_id": str(uuid4()), "email": "test@example.invalid"}
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for end in (start, start + timedelta(days=94)):
            with self.subTest(end=end), self.assertRaises(HTTPException) as error:
                await check_leave_rest_days(start, end, claims, SessionUnitOfWork(object()))
            self.assertEqual(error.exception.status_code, 422)

    async def test_stale_admin_claim_cannot_create_leave_for_another_employee(self):
        employee_id = uuid4()
        claims = {
            "sub": str(uuid4()), "employee_id": str(employee_id), "role": "admin", "email": "test@example.invalid",
        }
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            permission_codes=["leave.submit"], role_codes=["EMPLOYEE"], employee_id=employee_id,
        )))
        route = next(route for route in applications_router.routes if route.endpoint is create_leave_application)
        checker = next(dependency.call for dependency in route.dependant.dependencies if dependency.name == "claims")
        verified_claims = await checker(claims, authorization)
        start = datetime(2026, 11, 5, 1, tzinfo=timezone.utc)
        payload = LeaveApplicationCreateSchema(
            application_no="IT-LEAVE", employee_id=uuid4(), leave_type_id=uuid4(),
            start_at=start, end_at=start.replace(hour=9), duration_type="FULL_DAY",
            requested_minutes=480, reason="Synthetic",
        )
        use_case = SimpleNamespace(create=AsyncMock())
        with self.assertRaises(HTTPException) as error:
            await create_leave_application(payload, verified_claims, use_case, es_client=None)
        self.assertEqual(error.exception.status_code, 403)
        use_case.create.assert_not_awaited()

    async def test_locked_leave_write_rechecks_employee_and_draft_status(self):
        employee_id = uuid4()
        application = SimpleNamespace(id=uuid4(), employee_id=uuid4(), status="DRAFT", is_active=True)
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: application)),
            flush=AsyncMock(),
        )
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(session))
        with self.assertRaisesRegex(ValueError, "own leave application"):
            await use_case.submit_draft_for_approval(
                application.id, uuid4(), expected_employee_id=employee_id,
            )
        with self.assertRaisesRegex(ValueError, "own draft leave application"):
            await use_case.update_with_approval_posting(
                application.id, {"reason": "Changed"}, uuid4(), expected_employee_id=employee_id,
            )
        application.employee_id = employee_id
        application.status = "PENDING"
        with self.assertRaisesRegex(ValueError, "own draft leave application"):
            await use_case.update_with_approval_posting(
                application.id, {"reason": "Changed"}, uuid4(), expected_employee_id=employee_id,
            )
        session.flush.assert_not_awaited()

    async def test_submit_draft_moves_application_to_pending(self):
        application = SimpleNamespace(
            id=uuid4(),
            employee_id=uuid4(),
            leave_type_id=uuid4(),
            start_at=datetime(2026, 10, 12, 9, tzinfo=timezone.utc),
            end_at=datetime(2026, 10, 12, 10, tzinfo=timezone.utc),
            requested_minutes=60,
            status="DRAFT",
            is_active=True,
            submitted_at=None,
            updated_by=None,
            updated_at=None,
            row_version=2,
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(
                scalar_one_or_none=lambda: application,
                all=lambda: [],
            )),
            flush=AsyncMock(),
            refresh=AsyncMock(),
        )
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(session))
        actor_id = uuid4()

        with patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._to_entity",
            side_effect=lambda model, entity_type: model,
        ), patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._validate_leave_type_company",
            new=AsyncMock(),
        ), patch(
            "app.filemaintenance.leaves.application.leave_records_use_case.assign_org_approval",
            new=AsyncMock(),
        ) as assign_approval, patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._validated_duration",
            new=AsyncMock(),
        ), patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._verify_saved_days",
            new=AsyncMock(),
        ), patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._require_duration_open",
            new=AsyncMock(),
        ):
            result = await use_case.submit_draft_for_approval(uuid4(), actor_id)

        self.assertIs(result, application)
        self.assertEqual(application.status, "PENDING")
        self.assertEqual(application.updated_by, actor_id)
        self.assertEqual(application.row_version, 3)
        self.assertIsInstance(application.submitted_at, datetime)
        self.assertEqual(application.submitted_at.tzinfo, timezone.utc)
        assign_approval.assert_awaited_once()
        self.assertEqual(assign_approval.await_args.kwargs["resource_id"], application.id)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(application)
        self.assertEqual(session.execute.await_count, 2)

    async def test_rejection_does_not_post_a_leave_charge(self):
        application = SimpleNamespace(
            id=uuid4(), employee_id=uuid4(), start_at=datetime(2026, 10, 12, 9, tzinfo=timezone.utc),
            end_at=datetime(2026, 10, 12, 18, tzinfo=timezone.utc), status="PENDING", row_version=1,
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: application))),
            flush=AsyncMock(), refresh=AsyncMock(),
        )
        with patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._require_leave_open", new=AsyncMock(),
        ), patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._post_approved_leave_charge", new=AsyncMock(),
        ) as post, patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._to_entity", side_effect=lambda model, _: model,
        ):
            result = await LeaveApplicationUseCase(SessionUnitOfWork(session)).decide_pending_for_supervisor(
                uuid4(), application.id, "REJECTED", uuid4(), date(2026, 10, 12),
            )
        self.assertEqual(result.status, "REJECTED")
        post.assert_not_awaited()

    async def test_holiday_review_flags_legacy_applications_but_not_correct_daily_allocations(self):
        holiday = date(2026, 12, 25)
        employee_id = uuid4()
        common = dict(
            employee_id=employee_id, start_at=datetime(2026, 12, 24, tzinfo=timezone.utc),
            end_at=datetime(2026, 12, 27, tzinfo=timezone.utc), requested_minutes=480, paid_minutes=480,
        )
        legacy = SimpleNamespace(id=uuid4(), application_no="LEGACY", **common)
        correct = SimpleNamespace(id=uuid4(), application_no="CORRECT", **common)
        employee = SimpleNamespace(employee_no="E001", first_name="Test", last_name="Employee")
        leave_type = SimpleNamespace(leave_name="Vacation")
        daily = SimpleNamespace(
            leave_application_id=correct.id, leave_date=date(2026, 12, 24), approved_paid_minutes=480,
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [
                (legacy, employee, leave_type), (correct, employee, leave_type),
            ])),
            scalars=AsyncMock(side_effect=[
                SimpleNamespace(all=lambda: [holiday]),
                SimpleNamespace(all=lambda: [daily]),
            ]),
        )
        claims = {"sub": str(uuid4()), "email": "test@example.invalid"}
        with patch(
            "app.filemaintenance.leaves.infrastructure.leave_records_router.resolve_attendance_day_type",
            new=AsyncMock(return_value="RH"),
        ):
            response = await review_holiday_leave(
                date(2026, 12, 1), date(2026, 12, 31), 0, claims, SessionUnitOfWork(session),
            )
        self.assertEqual([item.application_no for item in response.data.items], ["LEGACY"])
        self.assertEqual(response.data.items[0].holiday_dates, [holiday])
        self.assertIsNone(response.data.next_offset)

    async def test_submit_rejects_non_draft_application(self):
        application = SimpleNamespace(status="PENDING", is_active=True)
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: application)),
            flush=AsyncMock(),
            refresh=AsyncMock(),
        )
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(session))

        with self.assertRaisesRegex(ValueError, "Only draft leave applications"):
            await use_case.submit_draft_for_approval(uuid4(), uuid4())

        session.flush.assert_not_awaited()

    async def test_approval_updates_an_expired_updated_at_without_reading_it(self):
        class ApplicationWithExpiredUpdatedAt:
            def __init__(self):
                self.id = uuid4()
                self.employee_id = uuid4()
                self.leave_type_id = uuid4()
                self.start_at = datetime(2026, 11, 5, 9, tzinfo=timezone.utc)
                self.end_at = datetime(2026, 11, 5, 18, tzinfo=timezone.utc)
                self.status = "PENDING"
                self.row_version = 2

            @property
            def updated_at(self):
                raise RuntimeError("Expired ORM field must not be read.")

            @updated_at.setter
            def updated_at(self, value):
                self._updated_at = value

        application = ApplicationWithExpiredUpdatedAt()
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(
                scalar_one_or_none=lambda: application,
                all=lambda: [],
            )),
            scalar=AsyncMock(return_value="LEGACY"),
            flush=AsyncMock(),
            refresh=AsyncMock(),
        )
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(session))

        with patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._validate_leave_type_company",
            new=AsyncMock(),
        ), patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._post_approved_leave_charge",
            new=AsyncMock(),
        ), patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._to_entity",
            side_effect=lambda model, entity_type: model,
        ):
            result = await use_case.update_with_approval_posting(
                application.id,
                {"status": "APPROVED"},
                uuid4(),
            )

        self.assertIs(result, application)
        self.assertEqual(application.status, "APPROVED")
        self.assertEqual(application.row_version, 3)
        self.assertIsInstance(application._updated_at, datetime)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(application)

    async def test_admin_update_cannot_bypass_org_approval_or_change_pending_employee(self):
        application = SimpleNamespace(
            id=uuid4(), employee_id=uuid4(), leave_type_id=uuid4(), status="PENDING",
            start_at=datetime(2026, 11, 5, 9, tzinfo=timezone.utc),
            end_at=datetime(2026, 11, 5, 18, tzinfo=timezone.utc),
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: application)),
            scalar=AsyncMock(return_value="ORG_UNIT"),
            flush=AsyncMock(),
        )
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(session))
        for values in ({"status": "APPROVED"}, {"status": "REJECTED"}, {"employee_id": uuid4()}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                await use_case.update_with_approval_posting(application.id, values, uuid4())
        self.assertEqual(application.status, "PENDING")
        session.flush.assert_not_awaited()

    async def test_approved_leave_cannot_be_created_without_approval(self):
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(None))
        for status in ("APPROVED", "REJECTED"):
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "approval workflow"):
                await use_case.create({"status": status})
