from contextlib import contextmanager
from typing import Iterator

from fastapi import HTTPException, status

from app.filemaintenance.schedule.domain.schedule_upload_exceptions import (
    ScheduleUploadError,
    ScheduleUploadNoLongerApplicableError,
    ScheduleUploadNotFoundError,
    ScheduleUploadPermissionError,
    ScheduleUploadRejectedFileError,
    ScheduleUploadStateError,
)

_ERROR_STATUS = (
    (ScheduleUploadNotFoundError, status.HTTP_404_NOT_FOUND),
    (ScheduleUploadPermissionError, status.HTTP_403_FORBIDDEN),
    (ScheduleUploadStateError, status.HTTP_409_CONFLICT),
    (ScheduleUploadNoLongerApplicableError, status.HTTP_409_CONFLICT),
    (ScheduleUploadRejectedFileError, status.HTTP_422_UNPROCESSABLE_ENTITY),
)


@contextmanager
def schedule_upload_http_errors() -> Iterator[None]:
    """Translates schedule upload domain errors raised by use cases into HTTP responses."""
    try:
        yield
    except ScheduleUploadError as error:
        status_code = next(
            (code for error_type, code in _ERROR_STATUS if isinstance(error, error_type)),
            status.HTTP_400_BAD_REQUEST,
        )
        raise HTTPException(status_code=status_code, detail=str(error)) from error
