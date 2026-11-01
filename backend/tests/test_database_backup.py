import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.auth.infrastructure.dependencies import (
    get_current_authorization_use_case,
    get_current_user_claims,
)
from app.backup.router import BackupDownload, create_database_dump, router
from app.backup import router as backup_module


class DumpTests(unittest.IsolatedAsyncioTestCase):
    async def test_dump_uses_custom_format_and_environment_credentials(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "database.dump"
            process = SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0))
            async def start(*args, **kwargs):
                path.write_bytes(b"PGDMP-test")
                self.assertEqual(args[0], "pg_dump")
                self.assertIn("--format=custom", args)
                self.assertNotIn("secret", " ".join(args))
                self.assertEqual(kwargs["env"]["PGPASSWORD"], "secret")
                self.assertEqual(kwargs["env"]["PGSSLMODE"], "require")
                return process
            with patch.object(backup_module.settings, "DATABASE_URL", "postgresql+asyncpg://user:secret@db:5432/test?sslmode=require"):
                with patch.object(backup_module.asyncio, "create_subprocess_exec", side_effect=start):
                    await create_database_dump(path)

    async def test_missing_tool_and_failed_dump_are_explicit_errors(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "database.dump"
            with patch.object(backup_module.asyncio, "create_subprocess_exec", side_effect=FileNotFoundError):
                with self.assertRaises(HTTPException) as raised:
                    await create_database_dump(path)
                self.assertEqual(raised.exception.status_code, 503)
            process = SimpleNamespace(returncode=1, wait=AsyncMock(return_value=1))
            with patch.object(backup_module.asyncio, "create_subprocess_exec", return_value=process):
                with self.assertRaises(HTTPException) as raised:
                    await create_database_dump(path)
                self.assertEqual(raised.exception.status_code, 500)

    async def test_timeout_and_cancellation_terminate_pg_dump(self):
        for failure in (asyncio.TimeoutError(), asyncio.CancelledError()):
            with self.subTest(failure=type(failure).__name__), TemporaryDirectory() as directory:
                process = SimpleNamespace(returncode=None, wait=AsyncMock(return_value=0))
                def kill():
                    process.returncode = -9
                process.kill = unittest.mock.Mock(side_effect=kill)
                async def fail_wait(coroutine, **kwargs):
                    coroutine.close()
                    raise failure
                with patch.object(backup_module.asyncio, "create_subprocess_exec", return_value=process):
                    with patch.object(backup_module.asyncio, "wait_for", side_effect=fail_wait):
                        with self.assertRaises((HTTPException, asyncio.CancelledError)):
                            await create_database_dump(Path(directory) / "database.dump")
                process.kill.assert_called_once()

    async def test_invalid_archive_is_not_downloaded(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "database.dump"
            path.write_bytes(b"invalid")
            process = SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0))
            with patch.object(backup_module.asyncio, "create_subprocess_exec", return_value=process):
                with self.assertRaises(HTTPException) as raised:
                    await create_database_dump(path)
                self.assertEqual(raised.exception.status_code, 500)

    async def test_response_cleans_up_even_when_send_fails(self):
        directory = TemporaryDirectory()
        path = Path(directory.name) / "database.dump"
        path.write_bytes(b"PGDMP-test")
        response = BackupDownload(path, directory, "backup.dump")
        scope = {"type": "http", "method": "GET", "headers": [], "extensions": {}}
        with self.assertRaises(ConnectionError):
            await response(scope, AsyncMock(), AsyncMock(side_effect=ConnectionError))
        self.assertFalse(path.exists())


class FakeSession:
    def __init__(self, acquired):
        self.acquired = acquired
        self.scalar = AsyncMock(return_value=acquired)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def begin(self):
        return self


class BackupEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.authorization = AsyncMock()
        self.authorization.execute.return_value = SimpleNamespace(role_codes=["SYSTEM_ADMIN"])
        self.app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(uuid4()), "role": "admin"}
        self.app.dependency_overrides[get_current_authorization_use_case] = lambda: self.authorization
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_current_database_roles_not_token_role_control_access(self):
        for roles in (["EMPLOYEE"], ["HR_ADMIN"], []):
            self.authorization.execute.return_value = SimpleNamespace(role_codes=roles)
            with patch.object(backup_module, "create_database_dump", new_callable=AsyncMock) as dump:
                response = await self.client.post("/auth/database-backup")
                self.assertEqual(response.status_code, 403)
                dump.assert_not_awaited()

    async def test_anonymous_access_is_rejected(self):
        self.app.dependency_overrides.pop(get_current_user_claims)
        response = await self.client.post("/auth/database-backup")
        self.assertIn(response.status_code, (401, 403))

    async def test_backup_download_and_cleanup(self):
        paths = []
        async def dump(path):
            paths.append(path)
            path.write_bytes(b"PGDMP-test")
        with patch.object(backup_module, "AsyncSessionLocal", return_value=FakeSession(True)):
            with patch.object(backup_module, "create_database_dump", side_effect=dump):
                response = await self.client.post("/auth/database-backup")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"PGDMP-test")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn(".dump", response.headers["content-disposition"])
        self.assertFalse(paths[0].exists())

    async def test_concurrent_backup_is_rejected(self):
        with patch.object(backup_module, "AsyncSessionLocal", return_value=FakeSession(False)):
            with patch.object(backup_module, "create_database_dump", new_callable=AsyncMock) as dump:
                response = await self.client.post("/auth/database-backup")
        self.assertEqual(response.status_code, 409)
        dump.assert_not_awaited()

    async def test_failed_backup_removes_partial_file(self):
        paths = []
        async def dump(path):
            paths.append(path)
            path.write_bytes(b"partial")
            raise HTTPException(500, "Backup failed")
        with patch.object(backup_module, "AsyncSessionLocal", return_value=FakeSession(True)):
            with patch.object(backup_module, "create_database_dump", side_effect=dump):
                response = await self.client.post("/auth/database-backup")
        self.assertEqual(response.status_code, 500)
        self.assertFalse(paths[0].exists())
