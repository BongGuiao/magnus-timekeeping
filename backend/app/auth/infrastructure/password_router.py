from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth.application.change_password_use_case import ChangePasswordInput, ChangePasswordUseCase
from app.auth.application.reset_password_use_case import ResetPasswordInput, ResetPasswordToDefaultUseCase
from app.auth.application.use_case import (
    SearchUserByEmployeeCodeInputDTO,
    SearchUserByEmployeeCodeUseCase,
)
from app.auth.domain.password_rules import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.auth.infrastructure.dependencies import (
    get_change_password_use_case,
    get_current_user_claims,
    get_reset_password_use_case,
    get_search_user_by_employee_code_use_case,
    require_system_admin,
)
from app.auth.infrastructure.http_errors import http_errors
from app.core.generics.mapper import ResponseEnvelope

router = APIRouter()


class ChangePasswordRequestSchema(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class ChangePasswordResponseSchema(BaseModel):
    message: str
    password_changed_at: datetime


class PasswordResetTargetSchema(BaseModel):
    employee_code: str
    employee_name: str
    account_status: str
    is_active: bool


class ResetPasswordRequestSchema(BaseModel):
    employee_code: str = Field(min_length=1, max_length=50)


class ResetPasswordResponseSchema(BaseModel):
    message: str
    employee_code: str
    password_reset_at: datetime


def _user_id_from_claims(claims: dict) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in authentication token.",
        ) from error


@router.get("/password-reset/lookup", response_model=ResponseEnvelope[PasswordResetTargetSchema])
async def lookup_password_reset_target(
    employee_code: str = Query(min_length=1, max_length=50),
    _: dict = Depends(require_system_admin),
    use_case: SearchUserByEmployeeCodeUseCase = Depends(get_search_user_by_employee_code_use_case),
):
    """Shows whose password will be reset so the administrator can confirm the employee first."""
    try:
        user = await use_case.execute(SearchUserByEmployeeCodeInputDTO(employee_code=employee_code.strip()))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return ResponseEnvelope[PasswordResetTargetSchema](
        data=PasswordResetTargetSchema(
            employee_code=user.employee_code,
            employee_name=user.employee_name,
            account_status=user.account_status,
            is_active=user.is_active,
        )
    )


@router.post("/password-reset", response_model=ResponseEnvelope[ResetPasswordResponseSchema])
async def reset_password_to_default(
    request: ResetPasswordRequestSchema,
    claims: dict = Depends(require_system_admin),
    use_case: ResetPasswordToDefaultUseCase = Depends(get_reset_password_use_case),
):
    """Restores an employee's password to the default; only system administrators may do this."""
    with http_errors():
        result = await use_case.execute(
            ResetPasswordInput(actor_id=_user_id_from_claims(claims), employee_code=request.employee_code)
        )
    return ResponseEnvelope[ResetPasswordResponseSchema](
        data=ResetPasswordResponseSchema(
            message=f"Password for {result.employee_code} was reset to the default password.",
            employee_code=result.employee_code,
            password_reset_at=result.password_reset_at,
        )
    )


@router.post("/change-password", response_model=ResponseEnvelope[ChangePasswordResponseSchema])
async def change_password(
    request: ChangePasswordRequestSchema,
    claims: dict = Depends(get_current_user_claims),
    use_case: ChangePasswordUseCase = Depends(get_change_password_use_case),
):
    """Changes the signed-in user's own password; the current password must be confirmed."""
    try:
        user_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in authentication token.",
        ) from error

    with http_errors():
        result = await use_case.execute(
            ChangePasswordInput(
                user_id=user_id,
                current_password=request.current_password,
                new_password=request.new_password,
            )
        )
    return ResponseEnvelope[ChangePasswordResponseSchema](
        data=ChangePasswordResponseSchema(
            message="Your password has been changed.",
            password_changed_at=result.password_changed_at,
        )
    )
