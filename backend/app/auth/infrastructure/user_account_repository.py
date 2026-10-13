from dataclasses import fields
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.entities.user import UserEntity
from app.auth.infrastructure.db_model import UserModel
from app.core.generics.uow import GenUnitOfWork


class SqlAlchemyUserAccountRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_for_update(self, user_id: UUID) -> Optional[UserEntity]:
        model = await self._session.scalar(
            select(UserModel).where(UserModel.id == user_id).with_for_update()
        )
        if model is None:
            return None
        return UserEntity(**{field.name: getattr(model, field.name) for field in fields(UserEntity)})

    async def save(self, user: UserEntity) -> None:
        model = await self._session.get(UserModel, user.id)
        # updated_at and row_version are maintained by the database trigger.
        model.password_hash = user.password_hash
        model.password_changed_at = user.password_changed_at
        model.failed_login_count = user.failed_login_count
        model.locked_until = user.locked_until
        model.updated_by = user.updated_by
        await self._session.flush()


class SqlAlchemyUserAccountUnitOfWork:
    """Adapts the generic unit of work to the auth application's UserAccountUnitOfWork port."""

    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow
        self.users: SqlAlchemyUserAccountRepository

    async def __aenter__(self) -> "SqlAlchemyUserAccountUnitOfWork":
        active = await self._uow.__aenter__()
        self.users = SqlAlchemyUserAccountRepository(active.session)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._uow.__aexit__(exc_type, exc_val, exc_tb)
