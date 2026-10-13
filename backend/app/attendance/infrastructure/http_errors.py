from contextlib import contextmanager
from typing import Iterator

from fastapi import HTTPException, status

from app.attendance.domain.exceptions import (
    AttendanceRuleError,
    ConflictError,
    PermissionDeniedError,
    RecordNotFoundError,
    RuleViolationError,
    SnapshotUnavailableError,
)

_ERROR_STATUS = (
    (RecordNotFoundError, status.HTTP_404_NOT_FOUND),
    (ConflictError, status.HTTP_409_CONFLICT),
    (PermissionDeniedError, status.HTTP_403_FORBIDDEN),
    (RuleViolationError, status.HTTP_422_UNPROCESSABLE_ENTITY),
    (SnapshotUnavailableError, status.HTTP_503_SERVICE_UNAVAILABLE),
)


@contextmanager
def http_errors() -> Iterator[None]:
    """Translates domain rule errors raised by use cases into HTTP responses."""
    try:
        yield
    except AttendanceRuleError as error:
        status_code = next(
            (code for error_type, code in _ERROR_STATUS if isinstance(error, error_type)), None
        )
        if status_code is None:
            raise
        raise HTTPException(status_code=status_code, detail=str(error)) from error
