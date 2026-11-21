from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.attendance.domain.tardiness_screening import previous_calendar_month
from app.attendance.infrastructure.tardiness_screening import TardinessReview, load_tardiness_review
from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work

router = APIRouter(prefix="/tardiness-review", tags=["Tardiness Review"])
MANILA = ZoneInfo("Asia/Manila")


@router.get("", response_model=ResponseEnvelope[TardinessReview])
async def preview_previous_month_tardiness(
    response: Response,
    claims: dict = Depends(get_current_user_claims),
    authorization_use_case: GetCurrentAuthorizationUseCase = Depends(get_current_authorization_use_case),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    try:
        actor_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user identity.") from error
    authorization = await authorization_use_case.execute(actor_id)
    if not any(role.strip().upper() == "HR_ADMIN" for role in authorization.role_codes):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only HR administrators can review tardiness.")

    start, end = previous_calendar_month(datetime.now(MANILA).date())
    async with uow as active_uow:
        if active_uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        review = await load_tardiness_review(active_uow.session, start, end)
    response.headers["Cache-Control"] = "no-store"
    return ResponseEnvelope(status="success", data=review)
