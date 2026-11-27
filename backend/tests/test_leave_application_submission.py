import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import ValidationError

from app.filemaintenance.leaves.application.leave_records_use_case import LeaveApplicationUseCase
from app.filemaintenance.leaves.domain.entities.leave_records import LeaveApplicationEntity
from app.filemaintenance.leaves.infrastructure.leave_records_router import (
    LeaveApplicationCreateSchema,
    SupervisorLeaveDecisionSchema,
    decide_supervisor_pending_leave_application,
    applications_router,
    check_leave_rest_days,
    create_leave_application,
    submit_leave_application,
    update_leave_application,
    review_holiday_leave,
    list_my_leave_applications,
    list_leave_applications,
)


class SessionUnitOfWork:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class LeaveApplicationSubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_personal_leave_list_scopes_admin_and_employee_accounts_to_their_own_records(self):
        employee_id, leave_type_id = uuid4(), uuid4()
        for role, role_codes in (("admin", ["HR_ADMIN", "EMPLOYEE"]), ("user", ["EMPLOYEE"])):
            with self.subTest(role=role):
                claims = {
                    "sub": str(uuid4()), "employee_id": str(employee_id), "email": "test@example.invalid",
                    "role": role, "role_codes": role_codes,
                }
                records = [SimpleNamespace(employee_id=employee_id)]
                use_case = SimpleNamespace(list=AsyncMock(return_value=records))
                result = await list_my_leave_applications(leave_type_id, "APPROVED", 25, 25, claims, use_case)
                use_case.list.assert_awaited_once_with(employee_id, leave_type_id, "APPROVED", 25, 25)
                self.assertEqual(result.data, records)

    async def test_personal_leave_list_rejects_missing_employee_instead_of_listing_everyone(self):
        claims = {"sub": str(uuid4()), "email": "test@example.invalid", "role": "admin"}
        use_case = SimpleNamespace(list=AsyncMock())
        with self.assertRaises(HTTPException) as error:
            await list_my_leave_applications(None, None, 0, 100, claims, use_case)
        self.assertEqual(error.exception.status_code, 403)
        use_case.list.assert_not_awaited()

    async def test_personal_leave_list_checks_live_employee_link_and_permission(self):
        route = next(route for route in applications_router.routes if route.endpoint is list_my_leave_applications)
        checker = next(dependency.call for dependency in route.dependant.dependencies if dependency.name == "claims")
        claims = {"sub": str(uuid4()), "employee_id": str(uuid4()), "role": "admin"}
        for permissions, employee_id in ((["leave.read_own"], uuid4()), ([], uuid4())):
            authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
                permission_codes=permissions, role_codes=["HR_ADMIN"], employee_id=employee_id,
            )))
            with self.subTest(permissions=permissions), self.assertRaises(HTTPException) as error:
                await checker(claims, authorization)
            self.assertEqual(error.exception.status_code, 403)

    async def test_admin_records_list_retains_organization_scope_and_employee_filters(self):
        claims = {"sub": str(uuid4()), "email": "test@example.invalid", "role": "admin"}
        for employee_id in (None, uuid4()):
            use_case = SimpleNamespace(list=AsyncMock(return_value=[]))
            await list_leave_applications(employee_id, None, None, 0, 100, claims, use_case)
            use_case.list.assert_awaited_once_with(employee_id, None, None, 0, 100)

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
                uuid4(), application.id, "REJECTED", uuid4(), date(2026, 10, 12), "  Missing details  ",
            )
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.rejection_reason, "Missing details")
        self.assertIsNone(result.approved_by_id)
        post.assert_not_awaited()

    async def test_rejection_requires_a_nonblank_reason_before_updating(self):
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(None))
        for reason in (None, "  ", "x" * 2001):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, "rejection reason"):
                await use_case.decide_pending_for_supervisor(
                    uuid4(), uuid4(), "REJECTED", uuid4(), date(2026, 10, 12), reason,
                )

    async def test_rejection_schema_and_dashboard_refresh(self):
        for reason in (None, "  ", "x" * 2001):
            with self.subTest(reason=reason), self.assertRaises(ValidationError):
                SupervisorLeaveDecisionSchema(decision="REJECTED", rejection_reason=reason)
        payload = SupervisorLeaveDecisionSchema(decision="REJECTED", rejection_reason="  Missing details  ")
        self.assertEqual(payload.rejection_reason, "Missing details")
        employee_id, application_id = uuid4(), uuid4()
        start = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
        result = LeaveApplicationEntity(
            id=application_id, application_no="LEAVE-1", employee_id=employee_id,
            leave_type_id=uuid4(), start_at=start, end_at=start + timedelta(hours=8),
            duration_type="FULL_DAY", requested_minutes=480, reason="Leave",
            status="REJECTED", rejection_reason=payload.rejection_reason,
        )
        use_case = SimpleNamespace(decide_pending_for_supervisor=AsyncMock(return_value=result))
        claims = {"sub": str(uuid4()), "employee_id": str(uuid4()), "email": "test@example.invalid"}
        with patch("app.filemaintenance.leaves.infrastructure.leave_records_router._queue_leave_dashboard_refresh") as refresh, patch(
            "app.filemaintenance.leaves.infrastructure.leave_records_router.log_entity_action", new=AsyncMock()
        ):
            response = await decide_supervisor_pending_leave_application(application_id, payload, claims, use_case, None)
        self.assertEqual(response.data.rejection_reason, "Missing details")
        refresh.assert_called_once_with(employee_id)

    async def test_legacy_update_requires_reason_and_prevents_overwriting_it(self):
        application = SimpleNamespace(status="PENDING")
        session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: application)))
        use_case = LeaveApplicationUseCase(SessionUnitOfWork(session))
        for values in ({"status": "REJECTED"}, {"rejection_reason": "Unapproved change"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                await use_case.update_with_approval_posting(uuid4(), values, uuid4())

    async def test_approval_records_the_actual_approver(self):
        actor_id = uuid4()
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
        ), patch(
            "app.filemaintenance.leaves.application.leave_records_use_case._to_entity", side_effect=lambda model, _: model,
        ):
            result = await LeaveApplicationUseCase(SessionUnitOfWork(session)).decide_pending_for_supervisor(
                uuid4(), application.id, "APPROVED", actor_id, date(2026, 10, 12),
            )
        self.assertEqual(result.approved_by_id, actor_id)

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
        self.assertIsNotNone(application.approved_by_id)
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
