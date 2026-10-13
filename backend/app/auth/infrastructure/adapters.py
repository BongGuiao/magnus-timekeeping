from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch

from app.audit.service import log_entity_action
from app.core import security


class Argon2PasswordHasher:
    """Uses the same Argon2 hashing as sign-in and account creation."""

    def hash(self, plain_password: str) -> str:
        return security.get_password_hash(plain_password)

    def verify(self, plain_password: str, password_hash: str) -> bool:
        return security.verify_password(plain_password, password_hash)


class ElasticsearchAuditTrail:
    def __init__(self, es_client: AsyncElasticsearch | None):
        self._es_client = es_client

    async def record(
        self, *, user_id: UUID | str, action: str, resource: str, resource_id: str, after: Any
    ) -> None:
        await log_entity_action(
            self._es_client, user_id=user_id, action=action, resource=resource,
            resource_id=resource_id, after=after,
        )
