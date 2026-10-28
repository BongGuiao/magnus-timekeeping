import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo

EntityT = TypeVar("EntityT")
PH_TIMEZONE = ZoneInfo("Asia/Manila")
logger = logging.getLogger("magnus.audit")


def stamp_audit_fields(
    payload: dict[str, Any],
    actor_id: UUID,
    *,
    creating: bool,
) -> dict[str, Any]:
    current_time = datetime.now(PH_TIMEZONE)
    if creating:
        payload["created_at"] = current_time
        payload["created_by"] = actor_id
    payload["updated_at"] = current_time
    payload["updated_by"] = actor_id
    return payload


def log_entity_change(
    *,
    entity_name: str,
    action: str,
    entity_id: UUID | str | None,
    actor_id: UUID,
    before: EntityT | None,
    after: EntityT,
) -> None:
    before_values = asdict(before) if before is not None else None
    after_values = asdict(after)
    changed_fields = [
        field
        for field, value in after_values.items()
        if before_values is None or before_values.get(field) != value
    ]
    event = {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": [entity_name],
        "event.dataset": f"magnus.{entity_name}_audit",
        "event.action": action,
        "event.outcome": "success",
        f"{entity_name}.id": str(entity_id or getattr(after, "id", None)),
        "user.id": str(actor_id),
        "changed_fields": changed_fields,
        "before": before_values,
        "after": after_values,
    }
    logger.setLevel(logging.INFO)
    logger.info(event)
