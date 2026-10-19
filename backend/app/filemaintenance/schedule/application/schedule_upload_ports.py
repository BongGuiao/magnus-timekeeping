from datetime import date
from typing import Collection, Protocol
from uuid import UUID

from app.filemaintenance.schedule.domain.entities.schedule_upload import (
    EmployeeScheduleView,
    ExistingScheduleAssignment,
    NewScheduleAssignment,
    NewScheduleUploadBatch,
    RestDayPatternRef,
    ScheduleTemplateRef,
    ScheduleUploadBatch,
    ScheduleUploadBatchStatus,
    ScheduleUploadFile,
    TeamEmployee,
)
from app.filemaintenance.schedule.domain.schedule_timeline import AssignmentRevision


class ScheduleUploadFileReader(Protocol):
    def read(self, content: bytes) -> ScheduleUploadFile: ...


class ScheduleUploadLookups(Protocol):
    async def find_team_employees(
        self,
        supervisor_employee_id: UUID,
        employee_codes: Collection[str],
        on_date: date,
    ) -> list[TeamEmployee]: ...

    async def find_schedule_templates(
        self,
        company_ids: Collection[UUID],
        schedule_codes: Collection[str],
    ) -> list[ScheduleTemplateRef]: ...

    async def find_rest_day_patterns(
        self,
        pattern_codes: Collection[str],
    ) -> list[RestDayPatternRef]: ...

    async def list_approved_assignments(
        self,
        employee_ids: Collection[UUID],
    ) -> list[ExistingScheduleAssignment]: ...


class ScheduleUploadRepository(ScheduleUploadLookups, Protocol):
    async def next_batch_sequence(self) -> int: ...

    async def add_batch(self, batch: NewScheduleUploadBatch) -> UUID: ...

    async def get_batch(self, batch_id: UUID, *, for_update: bool = False) -> ScheduleUploadBatch | None: ...

    async def list_batches(
        self,
        *,
        uploaded_by: UUID | None,
        status: ScheduleUploadBatchStatus | None,
        limit: int,
    ) -> list[ScheduleUploadBatch]: ...

    async def save_batch_review(self, batch: ScheduleUploadBatch) -> None: ...

    async def lock_employees(self, employee_ids: Collection[UUID]) -> None: ...

    async def revise_assignment(self, revision: AssignmentRevision, actor_id: UUID) -> None: ...

    async def add_assignment(self, assignment: NewScheduleAssignment) -> UUID: ...

    async def link_batch_row(self, batch_id: UUID, row_no: int, assignment_id: UUID) -> None: ...


class EmployeeScheduleReader(Protocol):
    async def list_employee_schedules(
        self,
        employee_id: UUID,
        from_date: date,
    ) -> list[EmployeeScheduleView]: ...


class ScheduleUploadUnitOfWork(Protocol):
    schedule_uploads: ScheduleUploadRepository
    employee_schedules: EmployeeScheduleReader

    async def __aenter__(self) -> "ScheduleUploadUnitOfWork": ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
