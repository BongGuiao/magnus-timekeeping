from typing import Any
from uuid import UUID

from fastapi import HTTPException, status


def has_supervisor_role(claims: dict[str, Any]) -> bool:
    role_codes = claims.get("role_codes", claims.get("roles", []))
    return isinstance(role_codes, list) and any(
        isinstance(role_code, str) and role_code.strip().upper() == "SUPERVISOR"
        for role_code in role_codes
    )


def approval_supervisor_scope(
    claims: dict[str, Any],
    *,
    is_admin: bool,
    detail: str,
) -> UUID | None:
    if is_admin and not has_supervisor_role(claims):
        return None
    try:
        return UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        ) from error
