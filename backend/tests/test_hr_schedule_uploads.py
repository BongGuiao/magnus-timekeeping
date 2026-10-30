import unittest
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.core.exception_handlers import register_exception_handlers
from app.filemaintenance.schedule.application.schedule_upload_use_cases import (
    ApproveScheduleUploadBatchUseCase,
    PreviewHrScheduleUploadUseCase,
    PreviewScheduleUploadUseCase,
    ReviewScheduleUploadBatchInput,
    ScheduleUploadFileInput,
    SubmitHrScheduleUploadUseCase,
)
from app.filemaintenance.schedule.domain.entities.schedule_upload import (
    ScheduleUploadBatchStatus,
    SupervisorEmployee,
)
from app.filemaintenance.schedule.domain.schedule_upload_exceptions import (
    ScheduleUploadNoLongerApplicableError,
    ScheduleUploadRejectedFileError,
)
from app.filemaintenance.schedule.infrastructure.schedule_upload_csv import (
    CsvScheduleUploadReader,
    schedule_upload_csv_template,
)
from app.filemaintenance.schedule.infrastructure.schedule_upload_dependencies import (
    get_preview_hr_schedule_upload_use_case,
    get_preview_schedule_upload_use_case,
    get_submit_hr_schedule_upload_use_case,
)
from app.filemaintenance.schedule.infrastructure.schedule_upload_repository import SqlAlchemyScheduleUploadRepository
from app.filemaintenance.schedule.infrastructure.schedule_upload_router import router
from backend.tests.test_schedule_upload_use_cases import (
    APPROVER_ID,
    COMPANY_ID,
    NOW,
    SUPERVISOR_ID,
    UPLOADER_ID,
    FakeScheduleUploadRepository,
    FakeUnitOfWork,
)

SECOND_SUPERVISOR_ID = uuid4()


class HrRepository(FakeScheduleUploadRepository):
    def __init__(self):
        super().__init__()
        self.second_employee = replace(self.employee, employee_id=uuid4(), employee_code="E002", employee_name="Second Employee")
        self.teams = {SUPERVISOR_ID: self.team, SECOND_SUPERVISOR_ID: [self.second_employee]}
        self.supervisors = [SupervisorEmployee(SUPERVISOR_ID, "S001"), SupervisorEmployee(SECOND_SUPERVISOR_ID, "S002")]
        self.company_approval = {}

    async def find_supervisors(self, employee_codes, on_date):
        return [supervisor for supervisor in self.supervisors if supervisor.employee_code in employee_codes]

    async def find_team_employees(self, supervisor_employee_id, employee_codes, on_date):
        return [employee for employee in self.teams.get(supervisor_employee_id, []) if employee.employee_code in employee_codes]

    async def schedule_approval_required(self, company_ids):
        return any(self.company_approval.get(company_id, self.approval_required) for company_id in company_ids)


class TransactionalFakeUnitOfWork(FakeUnitOfWork):
    async def __aenter__(self):
        self.snapshot = deepcopy(self.schedule_uploads.__dict__)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await super().__aexit__(exc_type, exc_val, exc_tb)
        if self.rolled_back:
            self.schedule_uploads.__dict__.update(self.snapshot)


def hr_file(*rows):
    return ScheduleUploadFileInput(
        supervisor_employee_id=None, uploaded_by=UPLOADER_ID, file_name="hr.csv",
        content=(schedule_upload_csv_template(True) + "".join(f"{row}\n" for row in rows)).encode(),
    )


class HrScheduleUploadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = HrRepository()
        self.uow = TransactionalFakeUnitOfWork(self.repo)
        self.reader = CsvScheduleUploadReader(include_supervisor=True)
        self.preview = PreviewHrScheduleUploadUseCase(self.uow, self.reader, lambda: NOW)
        self.submit = SubmitHrScheduleUploadUseCase(self.uow, self.reader, lambda: NOW)
        self.valid = hr_file("S001,E001,DAY,REGULAR,2026-11-01,,,", "S002,E002,DAY,REGULAR,2026-11-01,,,")

    async def test_preview_resolves_each_supervisor_without_writes_and_preserves_original_rows(self):
        result = await self.preview.execute(self.valid)
        self.assertTrue(result.is_valid)
        self.assertEqual([row.row_no for row in result.rows], [2, 3])
        self.assertEqual([row.supervisor_employee_code for row in result.rows], ["S001", "S002"])
        self.assertEqual([row.employee_name for row in result.rows], ["Ana Cruz", "Second Employee"])
        self.assertEqual(self.repo.batches, {})
        self.assertEqual(self.repo.added, [])

    async def test_submit_splits_one_pending_batch_per_supervisor_with_hr_as_uploader(self):
        batches = await self.submit.execute(self.valid)
        self.assertEqual(len(batches), 2)
        self.assertEqual({batch.supervisor_employee_id for batch in batches}, {SUPERVISOR_ID, SECOND_SUPERVISOR_ID})
        self.assertEqual(len({batch.batch_no for batch in batches}), 2)
        for batch in batches:
            self.assertEqual(batch.uploaded_by, UPLOADER_ID)
            self.assertEqual(batch.status, ScheduleUploadBatchStatus.PENDING_APPROVAL)
            self.assertEqual(batch.row_count, 1)
            self.assertIsNone(batch.reviewed_by)
        self.assertEqual([batch.rows[0].row_no for batch in batches], [2, 3])
        self.assertEqual(self.repo.added, [])

    async def test_multiple_rows_for_same_supervisor_stay_in_one_batch(self):
        self.repo.team.append(replace(self.repo.employee, employee_id=uuid4(), employee_code="E003"))
        batches = await self.submit.execute(hr_file(
            "S001,E001,DAY,REGULAR,2026-11-01,,,", " S001 ,E003,DAY,REGULAR,2026-11-01,,,",
        ))
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].row_count, 2)

    async def test_unknown_inactive_missing_or_oversized_supervisor_rejects_whole_file(self):
        for code in ("UNKNOWN", "", "X" * 31):
            with self.subTest(code=code):
                upload = hr_file("S001,E001,DAY,REGULAR,2026-11-01,,,", f"{code},E002,DAY,REGULAR,2026-11-01,,,")
                validation = await self.preview.execute(upload)
                self.assertFalse(validation.is_valid)
                self.assertTrue(validation.rows[1].errors)
                with self.assertRaises(ScheduleUploadRejectedFileError):
                    await self.submit.execute(upload)
                self.assertEqual(self.repo.batches, {})
        self.repo.supervisors = self.repo.supervisors[:1]
        self.assertFalse((await self.preview.execute(self.valid)).is_valid)

    async def test_hr_cannot_change_reporting_relationships_or_upload_outside_specified_team(self):
        upload = hr_file("S002,E001,DAY,REGULAR,2026-11-01,,,")
        result = await self.preview.execute(upload)
        self.assertIn("not an active direct report", result.rows[0].errors[0])
        with self.assertRaises(ScheduleUploadRejectedFileError):
            await self.submit.execute(upload)
        self.assertEqual(self.repo.teams[SUPERVISOR_ID], self.repo.team)

    async def test_overlapping_employee_rows_are_detected_across_supervisor_groups(self):
        self.repo.teams[SECOND_SUPERVISOR_ID] = self.repo.team
        result = await self.preview.execute(hr_file(
            "S001,E001,DAY,REGULAR,2026-11-01,,,", "S002,E001,DAY,REGULAR,2026-11-01,,,",
        ))
        self.assertFalse(result.is_valid)
        self.assertTrue(all(any("overlap" in error.lower() for error in row.errors) for row in result.rows))

    async def test_submit_revalidates_team_after_preview(self):
        self.assertTrue((await self.preview.execute(self.valid)).is_valid)
        self.repo.teams[SECOND_SUPERVISOR_ID] = []
        with self.assertRaises(ScheduleUploadRejectedFileError):
            await self.submit.execute(self.valid)
        self.assertEqual(self.repo.batches, {})

    async def test_configured_auto_approval_is_preserved_and_all_employees_are_locked(self):
        self.repo.approval_required = False
        batches = await self.submit.execute(self.valid)
        self.assertTrue(all(batch.status == ScheduleUploadBatchStatus.APPROVED for batch in batches))
        self.assertEqual(len(self.repo.added), 2)
        self.assertEqual(self.repo.locked, {self.repo.employee.employee_id, self.repo.second_employee.employee_id})
        self.assertTrue(all(assignment.created_by == UPLOADER_ID for assignment in self.repo.added))
        self.assertTrue(all("HR submission" in batch.review_remarks for batch in batches))

    async def test_different_company_settings_are_applied_per_supervisor_batch(self):
        second_company = uuid4()
        self.repo.teams[SECOND_SUPERVISOR_ID] = [replace(self.repo.second_employee, company_id=second_company)]
        self.repo.templates.append(replace(self.repo.templates[0], id=uuid4(), company_id=second_company))
        self.repo.company_approval = {COMPANY_ID: True, second_company: False}
        batches = await self.submit.execute(self.valid)
        self.assertEqual([batch.status for batch in batches], [
            ScheduleUploadBatchStatus.PENDING_APPROVAL, ScheduleUploadBatchStatus.APPROVED,
        ])

    async def test_failure_after_first_batch_rolls_back_whole_file(self):
        original_add = self.repo.add_batch

        async def fail_second(batch):
            if self.repo.batches:
                raise RuntimeError("Simulated storage failure.")
            return await original_add(batch)

        self.repo.add_batch = fail_second
        with self.assertLogs("app.core.generics.uc_base", level="ERROR"), self.assertRaisesRegex(RuntimeError, "Simulated storage failure"):
            await self.submit.execute(self.valid)
        self.assertTrue(self.uow.rolled_back)
        self.assertEqual(self.repo.batches, {})
        self.assertEqual(self.repo.added, [])

    async def test_existing_independent_approval_and_revalidation_remain_usable(self):
        batch = (await self.submit.execute(self.valid))[0]
        approved = await ApproveScheduleUploadBatchUseCase(self.uow, lambda: NOW).execute(
            ReviewScheduleUploadBatchInput(batch.id, APPROVER_ID, "Approved"),
        )
        self.assertEqual(approved.status, ScheduleUploadBatchStatus.APPROVED)
        self.assertEqual(approved.reviewed_by, APPROVER_ID)

    async def test_later_application_failure_rolls_back_already_applied_batch(self):
        self.repo.approval_required = False
        original_add = self.repo.add_assignment

        async def fail_second(assignment):
            if self.repo.added:
                raise RuntimeError("Simulated application failure.")
            return await original_add(assignment)

        self.repo.add_assignment = fail_second
        with self.assertLogs("app.core.generics.uc_base", level="ERROR"), self.assertRaisesRegex(RuntimeError, "Simulated application failure"):
            await self.submit.execute(self.valid)
        self.assertTrue(self.uow.rolled_back)
        self.assertEqual(self.repo.batches, {})
        self.assertEqual(self.repo.added, [])
        self.assertEqual(self.repo.links, {})

    async def test_approval_revalidates_stored_supervisor_after_reporting_change(self):
        batch = (await self.submit.execute(self.valid))[1]
        self.repo.teams[SECOND_SUPERVISOR_ID] = []
        with self.assertRaises(ScheduleUploadNoLongerApplicableError):
            await ApproveScheduleUploadBatchUseCase(self.uow, lambda: NOW).execute(
                ReviewScheduleUploadBatchInput(batch.id, APPROVER_ID, "Approved"),
            )
        self.assertEqual(self.repo.batches[batch.id].status, ScheduleUploadBatchStatus.PENDING_APPROVAL)
        self.assertEqual(self.repo.added, [])

    async def test_file_limits_and_missing_supervisor_header_apply_before_database_lookup(self):
        self.repo.find_supervisors = AsyncMock()
        for content in (
            b"employee_code,schedule_code,assignment_type,effective_from\nE001,DAY,REGULAR,2026-11-01\n",
            (schedule_upload_csv_template(True) + "S001,E001,DAY,REGULAR,2026-11-01,,,\n" * 1001).encode(),
        ):
            result = await self.preview.execute(replace(self.valid, content=content))
            self.assertFalse(result.is_valid)
            self.assertTrue(result.file_errors)
        self.repo.find_supervisors.assert_not_awaited()

    async def test_supervisor_repository_filters_current_active_employment(self):
        session = SimpleNamespace(execute=AsyncMock(return_value=[(SUPERVISOR_ID, "S001")]))
        result = await SqlAlchemyScheduleUploadRepository(session).find_supervisors({"S001"}, NOW.date())
        self.assertEqual(result, [SupervisorEmployee(SUPERVISOR_ID, "S001")])
        query = session.execute.call_args.args[0]
        sql = str(query.compile(dialect=postgresql.dialect()))
        for clause in ("hr.employees.is_active IS true", "hr.employees.record_status", "effective_from <=", "effective_to >=", "separation_date >="):
            self.assertIn(clause, sql)


class HrScheduleUploadApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        register_exception_handlers(self.app)
        self.app.include_router(router)
        self.role_codes = ["HR_ADMIN"]
        self.permissions = ["schedule.upload_team"]
        self.claims = {"sub": str(UPLOADER_ID), "email": "hr@example.invalid"}
        self.authorization = SimpleNamespace(execute=AsyncMock(side_effect=lambda _user_id: SimpleNamespace(
            role_codes=self.role_codes, permission_codes=self.permissions,
        )))
        self.repo = HrRepository()
        self.uow = TransactionalFakeUnitOfWork(self.repo)
        self.preview = PreviewHrScheduleUploadUseCase(self.uow, CsvScheduleUploadReader(True), lambda: NOW)
        self.submit = SubmitHrScheduleUploadUseCase(self.uow, CsvScheduleUploadReader(True), lambda: NOW)
        self.app.dependency_overrides.update({
            get_current_user_claims: lambda: self.claims,
            get_current_authorization_use_case: lambda: self.authorization,
            get_preview_hr_schedule_upload_use_case: lambda: self.preview,
            get_submit_hr_schedule_upload_use_case: lambda: self.submit,
            get_preview_schedule_upload_use_case: lambda: PreviewScheduleUploadUseCase(self.uow, CsvScheduleUploadReader(), lambda: NOW),
        })
        self.client = TestClient(self.app)
        self.params = {"dashboard_role_code": "HR_ADMIN"}
        self.upload = hr_file("S001,E001,DAY,REGULAR,2026-11-01,,,", "S002,E002,DAY,REGULAR,2026-11-01,,,")

    def upload_request(self, path, **kwargs):
        return self.client.post(path, params=kwargs.get("params", self.params), files={
            "file": ("team.csv", self.upload.content, "text/csv"),
        })

    def test_hr_template_requires_both_real_role_and_selected_mode(self):
        path = "/schedule-uploads/hr-admin/template"
        response = self.client.get(path, params=self.params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, schedule_upload_csv_template(True))
        self.role_codes = ["SUPERVISOR"]
        self.assertEqual(self.client.get(path, params=self.params).status_code, 403)
        self.role_codes = ["HR_ADMIN"]
        self.assertEqual(self.client.get(path, params={"dashboard_role_code": "SUPERVISOR"}).status_code, 403)
        self.assertEqual(self.client.get(path).status_code, 422)

    def test_normal_template_is_unchanged_even_for_hr_role(self):
        response = self.client.get("/schedule-uploads/template")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, schedule_upload_csv_template())
        self.assertNotIn("supervisor_employee_code", response.text)

    def test_hr_without_linked_employee_can_preview_and_submit_multiple_batches(self):
        preview = self.upload_request("/schedule-uploads/hr-admin/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["data"]["rows"][1]["supervisor_employee_code"], "S002")
        response = self.upload_request("/schedule-uploads/hr-admin")
        self.assertEqual(response.status_code, 201)
        batches = response.json()["data"]
        self.assertEqual(len(batches), 2)
        self.assertTrue(all(batch["status"] == "PENDING_APPROVAL" for batch in batches))
        self.assertTrue(all(batch["uploaded_by"] == str(UPLOADER_ID) for batch in batches))

    def test_spoofing_mode_without_hr_role_cannot_preview_or_submit(self):
        self.role_codes = ["SYSTEM_ADMIN"]
        for path in ("/schedule-uploads/hr-admin/preview", "/schedule-uploads/hr-admin"):
            self.assertEqual(self.upload_request(path).status_code, 403)
        self.assertEqual(self.repo.batches, {})

    def test_hr_role_still_requires_upload_permission(self):
        self.permissions = []
        self.assertEqual(self.client.get("/schedule-uploads/hr-admin/template", params=self.params).status_code, 403)
        self.assertEqual(self.upload_request("/schedule-uploads/hr-admin/preview").status_code, 403)
        self.assertEqual(self.upload_request("/schedule-uploads/hr-admin").status_code, 403)

    def test_wrong_mode_cannot_preview_or_submit(self):
        for path in ("/schedule-uploads/hr-admin/preview", "/schedule-uploads/hr-admin"):
            self.assertEqual(self.upload_request(path, params={"dashboard_role_code": "SUPERVISOR"}).status_code, 403)

    def test_invalid_file_returns_validation_error_without_batches(self):
        self.upload = hr_file("UNKNOWN,E001,DAY,REGULAR,2026-11-01,,,")
        self.assertEqual(self.upload_request("/schedule-uploads/hr-admin").status_code, 422)
        self.assertEqual(self.repo.batches, {})

    def test_hr_file_checks_preserve_csv_and_one_mb_limits(self):
        for path in ("/schedule-uploads/hr-admin/preview", "/schedule-uploads/hr-admin"):
            with self.subTest(path=path):
                invalid_type = self.client.post(path, params=self.params, files={"file": ("team.txt", b"csv", "text/plain")})
                self.assertEqual(invalid_type.status_code, 400)
                oversized = self.client.post(path, params=self.params, files={"file": ("team.csv", b"x" * (1024 * 1024 + 1), "text/csv")})
                self.assertEqual(oversized.status_code, 413)

    def test_ordinary_team_upload_still_requires_linked_employee(self):
        response = self.upload_request("/schedule-uploads/preview")
        self.assertEqual(response.status_code, 403)
        self.assertIn("not linked", response.json()["detail"])

    def test_anonymous_access_rejected(self):
        del self.app.dependency_overrides[get_current_user_claims]
        self.assertEqual(self.client.get("/schedule-uploads/hr-admin/template", params=self.params).status_code, 403)
