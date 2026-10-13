from typing import Any, Optional, Protocol
from uuid import UUID

from app.auth.domain.entities.user import UserEntity


class PasswordHasher(Protocol):
    def hash(self, plain_password: str) -> str: ...

    def verify(self, plain_password: str, password_hash: str) -> bool: ...


class UserAccountRepository(Protocol):
    async def get_for_update(self, user_id: UUID) -> Optional[UserEntity]:
        """Loads the account and locks its row so concurrent attempts are counted in order."""
        ...

    async def save(self, user: UserEntity) -> None: ...


class UserAccountUnitOfWork(Protocol):
    users: UserAccountRepository

    async def __aenter__(self) -> "UserAccountUnitOfWork": ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...


class AuditTrail(Protocol):
    async def record(
        self, *, user_id: UUID | str, action: str, resource: str, resource_id: str, after: Any
    ) -> None: ...
