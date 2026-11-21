from uuid import UUID


def is_authorized_hr_head(actor_id: UUID, role_codes: list[str], configured_user_id: str | None) -> bool:
    if not configured_user_id:
        raise ValueError("The HR head user ID is not configured.")
    try:
        head_user_id = UUID(configured_user_id.strip())
    except ValueError as error:
        raise ValueError("The configured HR head user ID is invalid.") from error
    if not any(role.strip().upper() == "HR_ADMIN" for role in role_codes):
        return False
    return actor_id == head_user_id
