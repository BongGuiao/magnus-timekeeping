from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.schedule.application.schedule_upload_use_cases import (
    ApproveScheduleUploadBatchUseCase,
    CancelScheduleUploadBatchUseCase,
    GetScheduleUploadBatchUseCase,
    ListMySchedulesUseCase,
    ListScheduleUploadBatchesUseCase,
    PreviewScheduleUploadUseCase,
    RejectScheduleUploadBatchUseCase,
    SubmitScheduleUploadUseCase,
    PreviewHrScheduleUploadUseCase,
    SubmitHrScheduleUploadUseCase,
)
from app.filemaintenance.schedule.infrastructure.schedule_upload_csv import CsvScheduleUploadReader
from app.filemaintenance.schedule.infrastructure.schedule_upload_repository import (
    SqlAlchemyScheduleUploadUnitOfWork,
)


def get_schedule_upload_unit_of_work(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> SqlAlchemyScheduleUploadUnitOfWork:
    return SqlAlchemyScheduleUploadUnitOfWork(uow)


def get_preview_schedule_upload_use_case(
    uow: SqlAlchemyScheduleUploadUnitOfWork = Depends(get_schedule_upload_unit_of_work),
) -> PreviewScheduleUploadUseCase:
    return PreviewScheduleUploadUseCase(uow, CsvScheduleUploadReader())


def get_submit_schedule_upload_use_case(
    uow: SqlAlchemyScheduleUploadUnitOfWork = Depends(get_schedule_upload_unit_of_work),
) -> SubmitScheduleUploadUseCase:
    return SubmitScheduleUploadUseCase(uow, CsvScheduleUploadReader())


def get_preview_hr_schedule_upload_use_case(
    uow: SqlAlchemyScheduleUploadUnitOfWork = Depends(get_schedule_upload_unit_of_work),
) -> PreviewHrScheduleUploadUseCase:
    return PreviewHrScheduleUploadUseCase(uow, CsvScheduleUploadReader(include_supervisor=True))


def get_submit_hr_schedule_upload_use_case(
    uow: SqlAlchemyScheduleUploadUnitOfWork = Depends(get_schedule_upload_unit_of_work),
) -> SubmitHrScheduleUploadUseCase:
    return SubmitHrScheduleUploadUseCase(uow, CsvScheduleUploadReader(include_supervisor=True))


def get_list_schedule_upload_batches_use_case(
    uow: SqlAlchemyScheduleUploadUnitOfWork = Depends(get_schedule_upload_unit_of_work),
) -> ListScheduleUploadBatchesUseCase:
    return ListScheduleUploadBatchesUseCase(uow)


def get_get_schedule_upload_batch_use_case(
    uow: SqlAlchemyScheduleUploadUnitOfWork = Depends(get_schedule_upload_unit_of_work),
) -> GetScheduleUploadBatchUseCase:
    return GetScheduleUploadBatchUseCase(uow)


def get_approve_schedule_upload_batch_use_case(
    uow: SqlAlchemyScheduleUploadUnitOfWork = Depends(get_schedule_upload_unit_of_work),
) -> ApproveScheduleUploadBatchUseCase:
    return ApproveScheduleUploadBatchUseCase(uow)


def get_reject_schedule_upload_batch_use_case(
    uow: SqlAlchemyScheduleUploadUnitOfWork = Depends(get_schedule_upload_unit_of_work),
) -> RejectScheduleUploadBatchUseCase:
    return RejectScheduleUploadBatchUseCase(uow)


def get_cancel_schedule_upload_batch_use_case(
    uow: SqlAlchemyScheduleUploadUnitOfWork = Depends(get_schedule_upload_unit_of_work),
) -> CancelScheduleUploadBatchUseCase:
    return CancelScheduleUploadBatchUseCase(uow)


def get_list_my_schedules_use_case(
    uow: SqlAlchemyScheduleUploadUnitOfWork = Depends(get_schedule_upload_unit_of_work),
) -> ListMySchedulesUseCase:
    return ListMySchedulesUseCase(uow)
