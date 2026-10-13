from contextlib import contextmanager
from typing import Iterator

from fastapi import HTTPException, status

from app.auth.domain.exceptions import (
    AccountLockedError,
    AccountNotFoundError,
    AccountUnavailableError,
    AuthRuleError,
    InvalidCredentialsError,
    PasswordPolicyError,
)

_ERROR_STATUS = (
    (AccountNotFoundError, status.HTTP_404_NOT_FOUND),
    (InvalidCredentialsError, status.HTTP_400_BAD_REQUEST),
    (PasswordPolicyError, status.HTTP_422_UNPROCESSABLE_ENTITY),
    (AccountUnavailableError, status.HTTP_403_FORBIDDEN),
    (AccountLockedError, status.HTTP_429_TOO_MANY_REQUESTS),
)


@contextmanager
def http_errors() -> Iterator[None]:
    """Translates auth rule errors raised by use cases into HTTP responses."""
    try:
        yield
    except AuthRuleError as error:
        status_code = next(
            (code for error_type, code in _ERROR_STATUS if isinstance(error, error_type)), None
        )
        if status_code is None:
            raise
        raise HTTPException(status_code=status_code, detail=str(error)) from error
