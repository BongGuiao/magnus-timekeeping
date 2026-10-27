import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from app.filemaintenance.schedule.application.schedule_upload_use_cases import (
    ApproveScheduleUploadBatchUseCase,
    CancelScheduleUploadBatchInput,
    CancelScheduleUploadBatchUseCase,
    GetScheduleUploadBatchInput,
    GetScheduleUploadBatchUseCase,
    PreviewScheduleUploadUseCase,
    RejectScheduleUploadBatchUseCase,
    ReviewScheduleUploadBatchInput,
    ScheduleUploadFileInput,
    SubmitScheduleUploadUseCase,
)
from app.filemaintenance.schedule.domain.entities.schedule_upload import (
    ExistingScheduleAssignment,
    NewScheduleAssignment,
    NewScheduleUploadBatch,
    RestDayPatternRef,
    ScheduleTemplateRef,
    ScheduleUploadBatch,
    ScheduleUploadBatchStatus,
    TeamEmployee,
)
from app.filemaintenance.schedule.domain.schedule_upload_exceptions import (
    ScheduleUploadNoLongerApplicableError,
    ScheduleUploadNotFoundError,
    ScheduleUploadPermissionError,
    ScheduleUploadRejectedFileError,
)
from app.filemaintenance.schedule.infrastructure.schedule_upload_csv import CsvScheduleUploadReader

NOW = datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc)
COMPANY_ID = uuid4()
SUPERVISOR_ID = uuid4()
UPLOADER_ID = uuid4()
APPROVER_ID = uuid4()
HEADER = "employee_code,schedule_code,assignment_type,effective_from,effective_to,rest_day_pattern_code,reason\n"


class FakeScheduleUploadRepository:
    def __init__(self):
        self.employee = TeamEmployee(uuid4(), "E001", "Ana Cruz", COMPANY_ID)
        self.team = [self.employee]
        self.templates = [
            ScheduleTemplateRef(
                id=uuid4(),
                company_id=COMPANY_ID,
                schedule_code="DAY",
                schedule_name="Day shift",
                status="ACTIVE",
                is_active=True,
                effective_from=date(2026, 1, 1),
                effective_to=None,
            )
        ]
        self.patterns = [RestDayPatternRef(uuid4(), "SAT_SUN", "Weekends", True)]
        self.assignments: list[ExistingScheduleAssignment] = []
        self.batches: dict[UUID, ScheduleUploadBatch] = {}
        self.sequence = 0
        self.revisions = []
        self.added: list[NewScheduleAssignment] = []
        self.links: dict[int, UUID] = {}
        self.locked: set[UUID] = set()
        self.approval_required = True

    async def schedule_approval_required(self, company_ids):
        return self.approval_required

    async def find_team_employees(self, supervisor_employee_id, employee_codes, on_date):
        if supervisor_employee_id != SUPERVISOR_ID:
            return []
        return [employee for employee in self.team if employee.employee_code in employee_codes]

    async def find_schedule_templates(self, company_ids, schedule_codes):
        return [t for t in self.templates if t.company_id in company_ids and t.schedule_code in schedule_codes]

    async def find_rest_day_patterns(self, pattern_codes):
        return [pattern for pattern in self.patterns if pattern.pattern_code in pattern_codes]

    async def list_approved_assignments(self, employee_ids):
        return [assignment for assignment in self.assignments if assignment.employee_id in employee_ids]

    async def next_batch_sequence(self):
        self.sequence += 1
        return self.sequence

    async def add_batch(self, batch: NewScheduleUploadBatch):
        batch_id = uuid4()
        self.batches[batch_id] = ScheduleUploadBatch(
            id=batch_id,
            batch_no=batch.batch_no,
            supervisor_employee_id=batch.supervisor_employee_id,
            supervisor_name="Sup Visor",
            uploaded_by=batch.uploaded_by,
            file_name=batch.file_name,
            row_count=len(batch.rows),
            status=ScheduleUploadBatchStatus.PENDING_APPROVAL,
            submitted_at=NOW,
            rows=batch.rows,
        )
        return batch_id

    async def get_batch(self, batch_id, *, for_update=False):
        return self.batches.get(batch_id)

    async def list_batches(self, *, uploaded_by, status, limit):
        return list(self.batches.values())[:limit]

    async def save_batch_review(self, batch):
        self.batches[batch.id] = batch

    async def lock_employees(self, employee_ids):
        self.locked |= set(employee_ids)

    async def revise_assignment(self, revision, actor_id):
        self.revisions.append(revision)

    async def add_assignment(self, assignment):
        self.added.append(assignment)
        return uuid4()

    async def link_batch_row(self, batch_id, row_no, assignment_id):
        self.links[row_no] = assignment_id


class FakeUnitOfWork:
    def __init__(self, repository: FakeScheduleUploadRepository):
        self.schedule_uploads = repository
        self.employee_schedules = None
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.rolled_back = exc_type is not None


def _file(*lines: str) -> ScheduleUploadFileInput:
    return ScheduleUploadFileInput(
        supervisor_employee_id=SUPERVISOR_ID,
        uploaded_by=UPLOADER_ID,
        file_name="team.csv",
        content=(HEADER + "".join(f"{line}\n" for line in lines)).encode(),
    )


class ScheduleUploadUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repository = FakeScheduleUploadRepository()
        self.uow = FakeUnitOfWork(self.repository)
        self.reader = CsvScheduleUploadReader()

    def _clock(self, now: datetime = NOW):
        return lambda: now

    async def _submit(self, *lines: str) -> ScheduleUploadBatch:
        return await SubmitScheduleUploadUseCase(self.uow, self.reader, self._clock()).execute(_file(*lines))

    def _make_legacy_pending(self, batch: ScheduleUploadBatch) -> ScheduleUploadBatch:
        pending = replace(
            batch,
            status=ScheduleUploadBatchStatus.PENDING_APPROVAL,
            reviewed_by=None,
            reviewed_at=None,
            review_remarks=None,
            rows=tuple(replace(row, assignment_id=None) for row in batch.rows),
        )
        self.repository.batches[batch.id] = pending
        self.repository.added.clear()
        self.repository.revisions.clear()
        self.repository.links.clear()
        self.repository.locked.clear()
        return pending

    async def test_preview_reports_row_errors_and_effects(self):
        self.repository.assignments.append(
            ExistingScheduleAssignment(
                uuid4(), self.repository.employee.employee_id, uuid4(), "OLD", None, "REGULAR", date(2026, 1, 1), None
            )
        )

        validation = await PreviewScheduleUploadUseCase(self.uow, self.reader, self._clock()).execute(
            _file(
                "E001,DAY,REGULAR,2026-11-01,,SAT_SUN,",
                "E999,DAY,REGULAR,2026-11-01,,,",
                "E001,NOPE,REGULAR,2026-10-20,,,",
            )
        )

        self.assertFalse(validation.is_valid)
        first, second, third = validation.rows
        self.assertTrue(first.is_valid)
        self.assertEqual(first.employee_name, "Ana Cruz")
        self.assertIn("Ends schedule OLD", first.effects[0])
        self.assertIn("not an active direct report", second.errors[0])
        self.assertIn("on or after 2026-10-21", third.errors[0])

    async def test_invalid_file_is_not_submitted(self):
        with self.assertRaises(ScheduleUploadRejectedFileError):
            await self._submit("E001,NOPE,REGULAR,2026-11-01,,,")

        self.assertEqual(self.repository.batches, {})

    async def test_valid_file_waits_for_approval_by_default(self):
        batch = await self._submit("E001,DAY,regular,2026-11-01,,SAT_SUN,Rotation")

        self.assertEqual(batch.status, ScheduleUploadBatchStatus.PENDING_APPROVAL)
        self.assertIsNone(batch.reviewed_by)
        self.assertIsNone(batch.rows[0].assignment_id)
        self.assertEqual(self.repository.added, [])

    async def test_valid_file_applies_and_approves_when_approval_is_disabled(self):
        self.repository.approval_required = False
        batch = await self._submit("E001,DAY,regular,2026-11-01,,SAT_SUN,Rotation")

        self.assertEqual(batch.batch_no, "SCH-2026-000001")
        self.assertEqual(batch.status, ScheduleUploadBatchStatus.APPROVED)
        self.assertEqual(batch.reviewed_by, UPLOADER_ID)
        self.assertEqual(batch.rows[0].employee_id, self.repository.employee.employee_id)
        self.assertEqual(batch.rows[0].assignment_type, "REGULAR")
        self.assertIsNotNone(batch.rows[0].assignment_id)
        self.assertEqual(len(self.repository.added), 1)

    async def test_legacy_approval_applies_plan_and_creates_approved_assignments(self):
        current = ExistingScheduleAssignment(
            uuid4(), self.repository.employee.employee_id, uuid4(), "OLD", None, "REGULAR", date(2026, 1, 1), None
        )
        self.repository.assignments.append(current)
        batch = self._make_legacy_pending(
            await self._submit("E001,DAY,REGULAR,2026-11-01,2026-11-15,SAT_SUN,")
        )

        approved = await ApproveScheduleUploadBatchUseCase(self.uow, self._clock()).execute(
            ReviewScheduleUploadBatchInput(batch.id, APPROVER_ID, "  ok  ")
        )

        self.assertEqual(approved.status, ScheduleUploadBatchStatus.APPROVED)
        self.assertEqual(approved.review_remarks, "ok")
        self.assertEqual(self.repository.locked, {self.repository.employee.employee_id})
        self.assertEqual(self.repository.revisions[0].effective_to, date(2026, 10, 31))
        continuation, new = self.repository.added
        self.assertEqual((continuation.effective_from, continuation.effective_to), (date(2026, 11, 16), None))
        self.assertEqual(continuation.schedule_template_id, current.schedule_template_id)
        self.assertEqual(new.schedule_template_id, self.repository.templates[0].id)
        self.assertEqual(new.rest_day_pattern_id, self.repository.patterns[0].id)
        self.assertEqual((new.created_by, new.approved_by), (UPLOADER_ID, APPROVER_ID))
        self.assertEqual(approved.rows[0].assignment_id, self.repository.links[2])
        self.assertEqual(self.repository.batches[batch.id].status, ScheduleUploadBatchStatus.APPROVED)

    async def test_uploader_cannot_approve_own_batch(self):
        batch = self._make_legacy_pending(await self._submit("E001,DAY,REGULAR,2026-11-01,,,"))

        with self.assertRaises(ScheduleUploadPermissionError):
            await ApproveScheduleUploadBatchUseCase(self.uow, self._clock()).execute(
                ReviewScheduleUploadBatchInput(batch.id, UPLOADER_ID)
            )
        self.assertEqual(self.repository.added, [])

    async def test_approval_fails_when_batch_is_no_longer_valid(self):
        batch = self._make_legacy_pending(await self._submit("E001,DAY,REGULAR,2026-11-01,,,"))
        self.repository.team = []

        with self.assertRaises(ScheduleUploadNoLongerApplicableError) as context:
            await ApproveScheduleUploadBatchUseCase(self.uow, self._clock()).execute(
                ReviewScheduleUploadBatchInput(batch.id, APPROVER_ID)
            )

        self.assertIn("Row 2", str(context.exception))
        self.assertTrue(self.uow.rolled_back)
        self.assertEqual(self.repository.added, [])
        self.assertEqual(self.repository.batches[batch.id].status, ScheduleUploadBatchStatus.PENDING_APPROVAL)

    async def test_approval_after_start_date_is_rejected(self):
        batch = self._make_legacy_pending(await self._submit("E001,DAY,REGULAR,2026-10-21,,,"))
        late = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)

        with self.assertRaises(ScheduleUploadNoLongerApplicableError):
            await ApproveScheduleUploadBatchUseCase(self.uow, self._clock(late)).execute(
                ReviewScheduleUploadBatchInput(batch.id, APPROVER_ID)
            )

    async def test_reject_and_cancel_rules(self):
        first = self._make_legacy_pending(await self._submit("E001,DAY,REGULAR,2026-11-01,,,"))
        rejected = await RejectScheduleUploadBatchUseCase(self.uow, self._clock()).execute(
            ReviewScheduleUploadBatchInput(first.id, APPROVER_ID, "Wrong shift")
        )
        self.assertEqual(rejected.status, ScheduleUploadBatchStatus.REJECTED)

        second = self._make_legacy_pending(await self._submit("E001,DAY,REGULAR,2026-11-01,,,"))
        cancel = CancelScheduleUploadBatchUseCase(self.uow, self._clock())
        with self.assertRaises(ScheduleUploadNotFoundError):
            await cancel.execute(CancelScheduleUploadBatchInput(second.id, APPROVER_ID))
        cancelled = await cancel.execute(CancelScheduleUploadBatchInput(second.id, UPLOADER_ID))
        self.assertEqual(cancelled.status, ScheduleUploadBatchStatus.CANCELLED)
        self.assertEqual(second.batch_no, "SCH-2026-000002")

    async def test_supervisor_only_sees_own_batches(self):
        batch = await self._submit("E001,DAY,REGULAR,2026-11-01,,,")
        get = GetScheduleUploadBatchUseCase(self.uow)

        self.assertEqual((await get.execute(GetScheduleUploadBatchInput(batch.id, UPLOADER_ID))).id, batch.id)
        with self.assertRaises(ScheduleUploadNotFoundError):
            await get.execute(GetScheduleUploadBatchInput(batch.id, uuid4()))
        self.assertEqual((await get.execute(GetScheduleUploadBatchInput(batch.id))).id, batch.id)


if __name__ == "__main__":
    unittest.main()
