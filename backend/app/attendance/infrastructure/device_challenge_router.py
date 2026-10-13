from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.attendance.application.punch_ports import DeviceAction
from app.attendance.application.punch_use_cases import (
    IssueDeviceChallengeInput,
    IssueDeviceChallengeUseCase,
)
from app.attendance.infrastructure.dependencies import get_issue_device_challenge_use_case
from app.attendance.infrastructure.http_errors import http_errors
from app.auth.domain.entities.user import Role
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.generics.mapper import ResponseEnvelope

router = APIRouter()


class DeviceChallengeRequest(BaseModel):
    user_id: UUID
    device_uuid: str = Field(min_length=1, max_length=200)
    action: DeviceAction


class DeviceChallengeResponse(BaseModel):
    challenge_id: UUID
    message: str
    expires_at: str


@router.post(
    "/device-challenge",
    response_model=ResponseEnvelope[DeviceChallengeResponse],
)
async def create_device_challenge(
    payload: DeviceChallengeRequest,
    claims: dict = Depends(get_current_user_claims),
    use_case: IssueDeviceChallengeUseCase = Depends(get_issue_device_challenge_use_case),
):
    try:
        actor_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error

    with http_errors():
        challenge = await use_case.execute(
            IssueDeviceChallengeInput(
                actor_id=actor_id,
                actor_is_admin=claims.get("role") == Role.ADMIN.value,
                user_id=payload.user_id,
                device_uuid=payload.device_uuid,
                action=payload.action,
            )
        )
    return ResponseEnvelope(status="success", data=DeviceChallengeResponse(**challenge))
