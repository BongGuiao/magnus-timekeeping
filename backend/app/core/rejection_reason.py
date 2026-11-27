MAX_REJECTION_REASON_LENGTH = 2000


def rejection_reason_for_decision(decision: str, reason: str | None) -> str | None:
    cleaned = reason.strip() if reason is not None else ""
    if decision == "REJECTED":
        if not cleaned:
            raise ValueError("A rejection reason is required.")
        if len(cleaned) > MAX_REJECTION_REASON_LENGTH:
            raise ValueError(f"The rejection reason must be at most {MAX_REJECTION_REASON_LENGTH} characters.")
        return cleaned
    if cleaned:
        raise ValueError("A rejection reason can only be provided when rejecting.")
    return None
