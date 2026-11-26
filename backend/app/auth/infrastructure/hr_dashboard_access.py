from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, Query

from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims


async def require_hr_dashboard_access(
    dashboard_role_code: str = Query(...),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    authorization_use_case: GetCurrentAuthorizationUseCase = Depends(get_current_authorization_use_case),
) -> tuple[UUID, UUID]:
    if not claims.get("email"):
        raise HTTPException(status_code=401, detail="Email claim missing from authentication token.")
    try:
        actor_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=401, detail="User id claim missing or invalid in authentication token.") from error
    authorization = await authorization_use_case.execute(actor_id)
    if dashboard_role_code != "HR_ADMIN" or not any(
        role.strip().upper() == "HR_ADMIN" for role in authorization.role_codes
    ):
        raise HTTPException(status_code=403, detail="This action requires the HR_ADMIN role and dashboard.")
    if authorization.employee_id is None:
        raise HTTPException(status_code=403, detail="An active employee profile is required for this action.")
    return actor_id, authorization.employee_id
