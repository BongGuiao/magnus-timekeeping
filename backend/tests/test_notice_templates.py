import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.attendance.infrastructure import notice_template_router
from app.attendance.infrastructure.notice_models import NoticeTemplateModel
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.core.config import settings
from app.core.database import init_db_models
from app.core.generics.uow import get_unit_of_work


class NoticeTemplateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        init_db_models()
        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.addAsyncCleanup(self.engine.dispose)
        self.connection = await self.engine.connect()
        self.addAsyncCleanup(self.connection.close)
        self.transaction = await self.connection.begin()
        self.addAsyncCleanup(self.transaction.rollback)
        await self.connection.execute(text("CREATE TEMP TABLE users (id uuid PRIMARY KEY)"))
        await self.connection.execution_options(schema_translate_map={"identity": "pg_temp", "attendance": "pg_temp"})
        await self.connection.run_sync(lambda conn: NoticeTemplateModel.__table__.create(conn))
        self.session = AsyncSession(bind=self.connection)
        self.addAsyncCleanup(self.session.close)
        self.actor = uuid4()
        await self.session.execute(text("INSERT INTO pg_temp.users VALUES (:id)"), {"id": self.actor})

        class UnitOfWork:
            async def __aenter__(inner):
                return SimpleNamespace(session=self.session)

            async def __aexit__(inner, *args):
                return False

        self.authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(role_codes=["HR_ADMIN"])))
        app = FastAPI()
        app.include_router(notice_template_router.router)
        app.dependency_overrides[get_unit_of_work] = lambda: UnitOfWork()
        app.dependency_overrides[get_current_authorization_use_case] = lambda: self.authorization
        app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(self.actor), "role_codes": ["HR_ADMIN"]}
        app.dependency_overrides[get_audit_es_client] = lambda: None
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        self.lock_key = f"notice-test-{uuid4()}"
        lock_patch = patch.object(notice_template_router, "ACTIVATION_LOCK_KEY", self.lock_key)
        lock_patch.start()
        self.addCleanup(lock_patch.stop)

    async def upload(self, content: bytes, filename: str = "notice.html", module: str = "TARDINESS"):
        return await self.client.post(
            "/notice-templates", data={"name": "Notice to Explain", "module": module},
            files={"file": (filename, content, "text/html")},
        )

    async def test_upload_preview_and_activation_preserve_distinct_versions(self):
        first = await self.upload(b'<p onclick="evil()">{{employee_name}}</p><script>evil()</script>{{signature}}')
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.headers["cache-control"], "no-store")
        first_data = first.json()["data"]
        self.assertFalse(first_data["is_active"])
        self.assertNotIn("evil", first_data["sanitized_html"])
        second = await self.upload(b"<p>Second version</p>{{attendance_records}}{{signature}}")
        self.assertEqual(second.status_code, 201, second.text)
        second_data = second.json()["data"]
        self.assertNotEqual(first_data["id"], second_data["id"])
        for item in (first_data, second_data):
            result = await self.client.post(f"/notice-templates/{item['id']}/activate")
            self.assertEqual(result.status_code, 200, result.text)
            self.assertTrue(result.json()["data"]["is_active"])
        listed = await self.client.get("/notice-templates")
        self.assertEqual(listed.headers["cache-control"], "no-store")
        self.assertEqual(sum(row["is_active"] for row in listed.json()["data"]), 1)
        old = await self.client.get(f"/notice-templates/{first_data['id']}")
        self.assertEqual(old.json()["data"]["sanitized_html"], first_data["sanitized_html"])
        self.assertFalse(old.json()["data"]["is_active"])

    async def test_current_hr_role_is_required_even_with_hr_token_claim(self):
        self.authorization.execute.return_value = SimpleNamespace(role_codes=["SUPERVISOR"])
        self.assertEqual((await self.client.get("/notice-templates")).status_code, 403)
        self.assertEqual((await self.upload(b"<p>{{signature}}</p>")).status_code, 403)
        self.assertEqual((await self.client.get(f"/notice-templates/{uuid4()}")).status_code, 403)
        self.assertEqual((await self.client.post(f"/notice-templates/{uuid4()}/activate")).status_code, 403)
        self.assertEqual(len((await self.session.scalars(select(NoticeTemplateModel))).all()), 0)

    async def test_each_module_has_its_own_active_version(self):
        tardiness = await self.upload(b"<p>{{late_dates}}</p>{{signature}}")
        returned = await self.upload(
            b"<p>{{employee_address}}</p>{{last_attendance_date}}{{consecutive_absence_days}}"
            b"{{expected_return_date}}{{signature}}", module="RETURN_TO_WORK",
        )
        self.assertEqual(tardiness.status_code, 201, tardiness.text)
        self.assertEqual(returned.status_code, 201, returned.text)
        replacement = await self.upload(b"<p>Another version</p>{{signature}}", module="RETURN_TO_WORK")
        self.assertEqual(replacement.status_code, 201, replacement.text)
        ids = [response.json()["data"]["id"] for response in (tardiness, returned, replacement)]
        for item_id in ids:
            response = await self.client.post(f"/notice-templates/{item_id}/activate")
            self.assertEqual(response.status_code, 200, response.text)
        listed = (await self.client.get("/notice-templates")).json()["data"]
        active = {item["module"]: item["id"] for item in listed if item["is_active"]}
        self.assertEqual(active, {"TARDINESS": ids[0], "RETURN_TO_WORK": ids[2]})
        original = (await self.client.get(f"/notice-templates/{ids[1]}")).json()["data"]
        self.assertFalse(original["is_active"])
        self.assertIn("{{expected_return_date}}", original["sanitized_html"])

    async def test_invalid_uploads_do_not_create_versions(self):
        for content, filename, module, expected in (
            (b"{{signature}}", "file.txt", "TARDINESS", 422),
            (b"\xff", "file.html", "TARDINESS", 422),
            (b"X" * 100_001, "file.html", "TARDINESS", 413),
            (b"<p>Missing signature</p>", "file.html", "TARDINESS", 422),
            (b"{{unknown}}{{signature}}", "file.html", "TARDINESS", 422),
            (b"{{last_attendance_date}}{{signature}}", "file.html", "TARDINESS", 422),
            (b"{{late_dates}}{{signature}}", "file.html", "RETURN_TO_WORK", 422),
            (b"{{signature}}", "file.html", "OTHER", 422),
        ):
            with self.subTest(filename=filename, module=module, expected=expected):
                response = await self.upload(content, filename, module)
                self.assertEqual(response.status_code, expected, response.text)
        self.assertEqual(len((await self.session.scalars(select(NoticeTemplateModel))).all()), 0)

    async def test_activating_missing_version_does_not_change_active_version(self):
        uploaded = (await self.upload(b"<p>{{signature}}</p>")).json()["data"]
        await self.client.post(f"/notice-templates/{uploaded['id']}/activate")
        response = await self.client.post(f"/notice-templates/{uuid4()}/activate")
        self.assertEqual(response.status_code, 404)
        self.assertTrue((await self.client.get(f"/notice-templates/{uploaded['id']}")).json()["data"]["is_active"])

    async def test_activation_holds_module_lock_until_transaction_ends(self):
        uploaded = (await self.upload(b"<p>{{signature}}</p>")).json()["data"]
        response = await self.client.post(f"/notice-templates/{uploaded['id']}/activate")
        self.assertEqual(response.status_code, 200)
        async with self.engine.connect() as other:
            acquired = await other.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), {"key": self.lock_key},
            )
        self.assertFalse(acquired)
