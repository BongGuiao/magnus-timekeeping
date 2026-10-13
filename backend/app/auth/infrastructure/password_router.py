from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.application.change_password_use_case import ChangePasswordInput, ChangePasswordUseCase
from app.auth.domain.password_rules import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.auth.infrastructure.dependencies import get_change_password_use_case, get_current_user_claims
from app.auth.infrastructure.http_errors import http_errors
from app.core.generics.mapper import ResponseEnvelope

router = APIRouter()


class ChangePasswordRequestSchema(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class ChangePasswordResponseSchema(BaseModel):
    message: str
    password_changed_at: datetime


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
