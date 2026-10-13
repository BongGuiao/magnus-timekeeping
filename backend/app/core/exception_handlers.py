from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Use cases raise ValueError for validation/business-rule failures -> 400."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"status": "error", "detail": str(exc)},
    )


async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
    """BaseUseCase.execute() wraps unexpected failures in RuntimeError -> 500."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": "error", "detail": "An unexpected error occurred. Please try again later."},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(RuntimeError, runtime_error_handler)
