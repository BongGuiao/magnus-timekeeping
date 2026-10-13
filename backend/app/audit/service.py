import logging
from dataclasses import asdict, is_dataclass
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch

from app.audit.domain import AuditLogCreate

logger = logging.getLogger("magnus.audit.elasticsearch")


def _audit_values(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value.copy()
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError(f"Unsupported audit value type: {type(value).__name__}")


async def log_action(es_client: AsyncElasticsearch, log_data: AuditLogCreate) -> None:
    """Index an audit event without allowing Elasticsearch outages to fail the request."""
    try:
        await es_client.index(
            index="ticketing-audit-logs",
            document=log_data.model_dump(mode="json"),
        )
    except Exception:
        logger.exception("Failed to send audit log to Elasticsearch.")


async def log_entity_action(
    es_client: AsyncElasticsearch | None,
    *,
    user_id: str | UUID,
    action: str,
    resource: str,
    resource_id: str | UUID,
    before: Any = None,
    after: Any = None,
) -> None:
    if es_client is None:
        return
    await log_action(
        es_client,
        AuditLogCreate(
            user_id=str(user_id),
            action=action.upper(),
            resource=resource,
            resource_id=str(resource_id),
            old_values=_audit_values(before),
            new_values=_audit_values(after),
        ),
    )
