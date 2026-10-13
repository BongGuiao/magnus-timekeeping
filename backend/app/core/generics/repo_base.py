from datetime import datetime
from typing import Generic, TypeVar, Type, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sa_delete
from typing import Any, Optional, Sequence
from app.core.generics.mapper import GenericMapper

TEntity = TypeVar("TEntity")
TModel = TypeVar("TModel")


class BaseRepository(Generic[TEntity, TModel]):
    def __init__(self, db: AsyncSession, model_class: Type[TModel], entity_class: Type[TEntity]):
        self.db = db
        self.model_class = model_class
        self.entity_class = entity_class

    async def add(self, entity: TEntity) -> TEntity:
        db_obj = GenericMapper.to_model(entity, self.model_class)
        self.db.add(db_obj)
        await self.db.flush()
        await self.db.refresh(db_obj)
        return GenericMapper.to_entity(db_obj, self.entity_class)
    
    async def update(self, entity: TEntity) -> TEntity:
        db_obj = GenericMapper.to_model(entity, self.model_class)
        db_obj = await self.db.merge(db_obj)
        await self.db.flush()
        await self.db.refresh(db_obj)
        return GenericMapper.to_entity(db_obj, self.entity_class)
    
    async def get(self, id: int) -> Optional[TEntity]:
        result = await self.db.execute(select(self.model_class).filter(self.model_class.id == id))
        db_obj = result.scalar_one_or_none()
        if not db_obj:
            return None
        return GenericMapper.to_entity(db_obj, self.entity_class)
    
    async def delete(self, entity_obj: TEntity) -> None:
        """Updated to accept an already mapped model/entity or handle object deletion safely."""
        db_obj = GenericMapper.to_model(entity_obj, self.model_class)
        # Merge ensures the object is attached to the current session context before deleting
        db_obj = await self.db.merge(db_obj)
        await self.db.delete(db_obj)
        await self.db.flush()

    async def delete_where(self, *criterion) -> int:
        """Allows bulk deleting rows using criteria matching your reversal requirements."""
        stmt = sa_delete(self.model_class).filter(*criterion)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    async def find_all(self, *criterion, order_by=None, offset: int = 0, limit: int = 100) -> list[TEntity]:
        query = select(self.model_class)
        
        if criterion:
            query = query.filter(*criterion)
            
        if order_by is not None:
            # Accepts either a single ordering clause or a list/tuple of them
            if isinstance(order_by, (list, tuple)):
                query = query.order_by(*order_by)
            else:
                query = query.order_by(order_by)
                
        query = query.offset(offset).limit(limit)
        result = await self.db.execute(query)
        db_objs = result.scalars().all()
        return [GenericMapper.to_entity(obj, self.entity_class) for obj in db_objs]
    
    async def search(self, *criterion, offset: int = 0, limit: int = 100) -> list[TEntity]:
        query = select(self.model_class).filter(*criterion).offset(offset).limit(limit)
        result = await self.db.execute(query)
        db_objs = result.scalars().all()
        return [GenericMapper.to_entity(obj, self.entity_class) for obj in db_objs]
    
    async def find_one(self, *criterion) -> Optional[TEntity]:
        query = select(self.model_class).filter(*criterion)
        result = await self.db.execute(query)
        db_obj = result.scalar_one_or_none()
        if not db_obj:
            return None
        return GenericMapper.to_entity(db_obj, self.entity_class)

