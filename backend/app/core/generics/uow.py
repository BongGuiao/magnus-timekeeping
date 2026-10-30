# app/core/generics/uow.py
from typing import TypeVar, Type, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.core.database import AsyncSessionLocal
from app.core.generics.repo_base import BaseRepository  # Adjust import path as needed

# Define Type Variables
TEntity = TypeVar("TEntity")
TModel = TypeVar("TModel")
TRepo = TypeVar("TRepo")

class GenUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory
        self.session: AsyncSession | None = None
        self._repo_cache: Dict[Any, Any] = {}

    async def __aenter__(self):
        self.session = self.session_factory(expire_on_commit=False)
        self._repo_cache.clear()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                await self.session.rollback()
            else:
                await self.session.commit()
        finally:
            await self.session.close()

    def repo(self, repo_type: Type[TRepo]) -> TRepo:
        """For concrete repository subclasses (preserves custom methods)."""
        if not self.session:
            raise RuntimeError("UnitOfWork session is not active. Use 'async with uow:'")
        
        if repo_type not in self._repo_cache:
            self._repo_cache[repo_type] = repo_type(self.session)
            
        return self._repo_cache[repo_type]
    
    def get_repo(self, entity_class: Type[TEntity], model_class: Type[TModel]) -> BaseRepository[TEntity, TModel]:
        """
        Dynamically returns a BaseRepository with explicitly inferred 
        Entity and Model return types for full IDE IntelliSense.
        """
        if not self.session:
            raise RuntimeError("UnitOfWork session is not active. Use 'async with uow:'")
        
        cache_key = (entity_class, model_class)
        if cache_key not in self._repo_cache:
            self._repo_cache[cache_key] = BaseRepository(self.session, model_class, entity_class)
            
        return self._repo_cache[cache_key]

def get_unit_of_work() -> GenUnitOfWork:
    return GenUnitOfWork(AsyncSessionLocal)