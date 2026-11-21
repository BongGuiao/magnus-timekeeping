import unittest
from datetime import date
from uuid import uuid4

from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.attendance.infrastructure.notice_models import NoticeModel, NoticeTemplateModel, TardinessCaseModel
from app.core.config import settings
from app.core.database import init_db_models


class NoticeStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        init_db_models()
        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.addAsyncCleanup(self.engine.dispose)
        self.connection = await self.engine.connect()
        self.addAsyncCleanup(self.connection.close)
        self.transaction = await self.connection.begin()
        self.addAsyncCleanup(self.transaction.rollback)
        await self.connection.execute(text("CREATE TEMP TABLE users (id uuid PRIMARY KEY)"))
        await self.connection.execute(text("CREATE TEMP TABLE employees (id uuid PRIMARY KEY)"))
        await self.connection.execution_options(schema_translate_map={
            "identity": "pg_temp", "hr": "pg_temp", "attendance": "pg_temp",
        })
        for model in (NoticeTemplateModel, TardinessCaseModel, NoticeModel):
            await self.connection.run_sync(lambda connection: model.__table__.create(connection))
        self.session = AsyncSession(bind=self.connection)
        self.addAsyncCleanup(self.session.close)

    async def test_notice_snapshot_survives_template_changes_and_case_is_unique(self):
        actor, employee, template_id, case_id, notice_id = (uuid4() for _ in range(5))
        await self.session.execute(text("INSERT INTO pg_temp.users VALUES (:id)"), {"id": actor})
        await self.session.execute(text("INSERT INTO pg_temp.employees VALUES (:id)"), {"id": employee})
        await self.session.execute(insert(NoticeTemplateModel).values(
            id=template_id, name="Original", module="TARDINESS", sanitized_html="<p>Original</p>", created_by=actor,
        ))
        await self.session.execute(insert(TardinessCaseModel).values(
            id=case_id, employee_id=employee, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        ))
        values = {"employee_name": "Test"}
        await self.session.execute(insert(NoticeModel).values(
            id=notice_id, case_id=case_id, employee_id=employee, template_id=template_id,
            template_name="Original", field_values=values, rendered_html="<p>Issued</p>", issued_by=actor,
        ))
        await self.session.execute(update(NoticeTemplateModel).where(
            NoticeTemplateModel.id == template_id,
        ).values(name="Changed", sanitized_html="<p>Changed</p>"))
        notice = await self.session.get(NoticeModel, notice_id)
        self.assertEqual((notice.template_name, notice.field_values, notice.rendered_html),
                         ("Original", values, "<p>Issued</p>"))
        with self.assertRaises(IntegrityError):
            async with self.session.begin_nested():
                await self.session.execute(insert(NoticeModel).values(
                    case_id=case_id, employee_id=employee, template_id=template_id,
                    template_name="Original", field_values=values, rendered_html="<p>Duplicate</p>", issued_by=actor,
                ))
        self.assertEqual(len((await self.session.scalars(select(NoticeModel))).all()), 1)
