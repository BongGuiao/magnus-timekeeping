import asyncio
import importlib.util
import json
import os
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from PIL import Image
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.core import face_recognition_service
from app.core.database import engine, init_db_models
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.enrollment.application.management import (
    ResetFaceEnrollmentInput, lock_enrollment_employee, reset_face_enrollments,
)
from app.enrollment.application.use_case import (
    EnrollFaceInputDTO, EnrollFaceUseCase, EnrollmentAuditUnavailable, FaceSimilarityConflict,
    SimilarEmployee, SimilarityOverride,
)
from app.enrollment.domain.entities.enrollment import EnrollmentStatus
from app.enrollment.infrastructure.db_model import (
    FaceEnrollmentModel, FaceEnrollmentOverrideModel, FaceEnrollmentResetModel,
)
from app.enrollment.infrastructure.dependencies import get_enroll_face_use_case
from app.enrollment.infrastructure.image_storage import face_image_path, face_image_reference, face_reference_path
from app.enrollment.infrastructure.router import router
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel


async def request(app, method, path, payload=None, *, body=None, content_type=b"application/json"):
    content = body if body is not None else json.dumps(payload).encode() if payload is not None else b""
    messages = []

    async def receive():
        return {"type": "http.request", "body": content, "more_body": False}

    async def send(message):
        messages.append(message)

    await app({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "root_path": "", "query_string": b"", "headers": [(b"content-type", content_type)],
        "server": ("localhost", 80), "client": ("127.0.0.1", 1234),
    }, receive, send)
    body = b"".join(message.get("body", b"") for message in messages)
    return SimpleNamespace(
        status=messages[0]["status"],
        headers=dict(messages[0]["headers"]),
        body=json.loads(body) if body.startswith(b"{") else body,
    )


def multipart(fields):
    boundary = "face-enrollment-test"
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="face.jpg"\r\n'
             "Content-Type: image/jpeg\r\n\r\nimage\r\n"]
    parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
              for name, value in fields.items()]
    return "".join(parts + [f"--{boundary}--\r\n"]).encode(), f"multipart/form-data; boundary={boundary}".encode()


class EnrollmentSimilarityOverrideRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.actor = uuid4()
        self.auth = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            role_codes=["HR_ADMIN"], permission_codes=["employees.manage"],
        )))
        self.use_case = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            status="enrolled", enrolled_at="2026-11-13T00:00:00+00:00", sample_count=1, photo_reference=None,
        )))
        self.app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(self.actor), "role": "admin"}
        self.app.dependency_overrides[get_current_authorization_use_case] = lambda: self.auth
        self.app.dependency_overrides[get_enroll_face_use_case] = lambda: self.use_case
        self.app.dependency_overrides[get_audit_es_client] = lambda: None

    async def enroll(self, **fields):
        body, content_type = multipart({"employee_id": str(uuid4()), **fields})
        return await request(self.app, "POST", "/enrollment/face", body=body, content_type=content_type)

    async def test_override_requires_live_hr_admin_access(self):
        self.auth.execute.return_value = SimpleNamespace(role_codes=["SYSTEM_ADMIN"], permission_codes=["employees.manage"])
        response = await self.enroll(similarity_override_employee_nos="0201", similarity_override_reason="Verified ID")
        self.assertEqual(response.status, 403)
        self.use_case.execute.assert_not_awaited()
        self.assertEqual((await self.enroll()).status, 201)

    async def test_override_is_passed_with_trimmed_numbers_and_reason(self):
        response = await self.enroll(similarity_override_employee_nos=" 0201, 0300 ", similarity_override_reason=" Verified ID ")
        self.assertEqual(response.status, 201)
        override = self.use_case.execute.await_args.args[0].similarity_override
        self.assertEqual(override, SimilarityOverride(frozenset({"0201", "0300"}), "Verified ID"))
        for fields in ({"similarity_override_employee_nos": "0201"}, {"similarity_override_reason": "Verified"}):
            with self.subTest(fields=fields):
                self.assertEqual((await self.enroll(**fields)).status, 422)

    async def test_similarity_conflict_returns_structured_details(self):
        self.use_case.execute.side_effect = FaceSimilarityConflict(
            "Too similar.", [SimilarEmployee(uuid4(), "0201", 0.47123)], 0.5,
        )
        response = await self.enroll()
        self.assertEqual(response.status, 409)
        self.assertEqual(response.body["code"], "FACE_SIMILARITY_CONFLICT")
        self.assertEqual(response.body["conflicting_employee_nos"], ["0201"])
        self.assertEqual(response.body["closest_distance"], 0.4712)
        self.assertEqual(response.body["threshold"], 0.5)
        self.assertEqual(response.body["detail"], "Too similar.")


class EnrollmentManagementPermissionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_management_checks_database_role_not_just_jwt_claims(self):
        app = FastAPI()
        app.include_router(router)
        actor_id, employee_id = uuid4(), uuid4()
        auth = SimpleNamespace(execute=AsyncMock())
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(actor_id), "role": "admin", "role_codes": ["HR_ADMIN"],
        }
        app.dependency_overrides[get_current_authorization_use_case] = lambda: auth
        app.dependency_overrides[get_audit_es_client] = lambda: None
        for roles, permissions in (
            (["SYSTEM_ADMIN"], ["employees.manage"]),
            (["HR_ADMIN"], []),
            ([], ["employees.manage"]),
        ):
            auth.execute.return_value = SimpleNamespace(role_codes=roles, permission_codes=permissions)
            for method, suffix, payload in (
                ("GET", "samples", None),
                ("POST", "reset", {"employee_no": "E", "sample_ids": [str(uuid4())], "reason": "Correction"}),
            ):
                with self.subTest(roles=roles, method=method):
                    response = await request(app, method, f"/enrollment/employees/{employee_id}/{suffix}", payload)
                    self.assertEqual(response.status, 403)
        app.dependency_overrides.pop(get_current_user_claims)
        self.assertIn((await request(app, "GET", f"/enrollment/employees/{employee_id}/samples")).status, (401, 403))

    def test_reference_resolution_cannot_delete_arbitrary_paths(self):
        for value in (None, "/tmp/image.jpg", "/enrollment/photos/../../file.jpg", "https://host/image.jpg"):
            self.assertIsNone(face_reference_path(value))
        image_id = uuid4()
        self.assertEqual(face_reference_path(face_image_reference(image_id)), face_image_path(image_id))


DATABASE_NAME = os.getenv("ENROLLMENT_TEST_DATABASE_NAME", "")
AUDIT_SQL_PATH = Path(__file__).resolve().parents[1] / "sql" / "20261113_add_face_enrollment_reset_audit.sql"
OVERRIDE_SQL_PATH = Path(__file__).resolve().parents[1] / "sql" / "20261113_add_face_enrollment_similarity_overrides.sql"


async def apply_audit_sql(connection, path=AUDIT_SQL_PATH):
    ddl = path.read_text().removeprefix("BEGIN;").strip().removesuffix("COMMIT;")
    raw = await connection.get_raw_connection()
    await raw.driver_connection.execute(ddl)


@unittest.skipUnless(DATABASE_NAME, "Requires a disposable enrollment_test_* database.")
class EnrollmentManagementDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not DATABASE_NAME.startswith("enrollment_test_"):
            self.fail("Only a disposable enrollment_test_* database may be used.")
        init_db_models()
        self.engine = create_async_engine(engine.url.set(database=DATABASE_NAME))
        self.addAsyncCleanup(self.engine.dispose)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.execute(text("CREATE SCHEMA IF NOT EXISTS hr"))
            await connection.execute(text("CREATE SCHEMA IF NOT EXISTS biometric"))
            await connection.run_sync(lambda sync: EmployeeModel.__table__.create(sync, checkfirst=True))
            await connection.run_sync(lambda sync: FaceEnrollmentModel.__table__.create(sync, checkfirst=True))
            await apply_audit_sql(connection)
            await apply_audit_sql(connection, OVERRIDE_SQL_PATH)
            await apply_audit_sql(connection, OVERRIDE_SQL_PATH)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.paths = patch(
            "app.enrollment.infrastructure.image_storage.face_image_directory",
            return_value=Path(self.directory.name),
        )
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.a, self.b, self.actor = uuid4(), uuid4(), uuid4()
        self.number = f"SYN-{self.a.hex[:12]}"
        self.a_image, self.b_image = uuid4(), uuid4()
        self.a_sample, self.b_sample = uuid4(), uuid4()
        for image_id in (self.a_image, self.b_image):
            Image.new("RGB", (16, 16), "white").save(face_image_path(image_id), format="JPEG")
        async with self.factory.begin() as session:
            session.add_all([
                EmployeeModel(id=self.a, employee_no=self.number, first_name="Synthetic", last_name="A",
                              photo_reference=face_image_reference(self.a_image)),
                EmployeeModel(id=self.b, employee_no=f"SYN-{self.b.hex[:12]}", first_name="Synthetic", last_name="B",
                              photo_reference=face_image_reference(self.b_image)),
            ])
            await session.flush()
            session.add_all([
                FaceEnrollmentModel(id=self.a_sample, employee_id=self.a, status=EnrollmentStatus.ENROLLED,
                                    face_encoding=[0.0, 1.0] + [0.0] * 126, image_path=face_image_reference(self.a_image)),
                FaceEnrollmentModel(id=self.b_sample, employee_id=self.b, status=EnrollmentStatus.ENROLLED,
                                    face_encoding=[0.8, 1.0] + [0.0] * 126, image_path=face_image_reference(self.b_image)),
            ])
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(self.actor), "role": "admin", "role_codes": ["HR_ADMIN"],
        }
        self.app.dependency_overrides[get_current_authorization_use_case] = lambda: SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(role_codes=["HR_ADMIN"], permission_codes=["employees.manage"])),
        )
        self.app.dependency_overrides[get_unit_of_work] = lambda: GenUnitOfWork(self.factory)
        self.app.dependency_overrides[get_audit_es_client] = lambda: None

    async def asyncTearDown(self):
        # This database is dedicated to these tests; isolate the next synthetic case.
        async with self.engine.begin() as connection:
            await connection.execute(FaceEnrollmentOverrideModel.__table__.delete())
            await connection.execute(FaceEnrollmentResetModel.__table__.delete())
            await connection.execute(FaceEnrollmentModel.__table__.delete())
            await connection.execute(EmployeeModel.__table__.delete())

    def payload(self, **overrides):
        return {"employee_no": self.number, "sample_ids": [str(self.a_sample)], "reason": "Wrong sample verified", **overrides}

    async def reset(self, **overrides):
        return await request(self.app, "POST", f"/enrollment/employees/{self.a}/reset", self.payload(**overrides))

    async def test_review_exposes_metadata_only_and_explicit_missing_photos(self):
        response = await request(self.app, "GET", f"/enrollment/employees/{self.a}/samples")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers[b"cache-control"], b"no-store")
        data = response.body["data"]
        self.assertEqual(data["enrolled_count"], 1)
        self.assertEqual(len(data["samples"]), 1)
        self.assertNotIn("face_encoding", data["samples"][0])
        self.assertEqual(data["samples"][0]["photo_reference"], face_image_reference(self.a_image))
        self.assertTrue(data["samples"][0]["is_profile_photo"])
        face_image_path(self.a_image).unlink()
        response = await request(self.app, "GET", f"/enrollment/employees/{self.a}/samples")
        self.assertIsNone(response.body["data"]["samples"][0]["photo_reference"])

    async def test_reset_requires_exact_employee_snapshot_and_reason(self):
        for overrides, status in (
            ({"employee_no": "WRONG"}, 409),
            ({"sample_ids": [str(uuid4())]}, 409),
            ({"sample_ids": [str(self.a_sample), str(self.a_sample)]}, 422),
            ({"sample_ids": []}, 422),
            ({"reason": "  "}, 422),
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual((await self.reset(**overrides)).status, status)
        async with self.factory() as session:
            self.assertIsNotNone(await session.get(FaceEnrollmentModel, self.a_sample))
            self.assertIsNone(await session.scalar(select(FaceEnrollmentResetModel)))
        self.assertTrue(face_image_path(self.a_image).is_file())

    async def test_database_audit_is_durable_without_elasticsearch(self):
        response = await self.reset()
        self.assertEqual(response.status, 200)
        async with self.factory.begin() as session:
            audit = (await session.scalars(select(FaceEnrollmentResetModel))).one()
            self.assertEqual(audit.employee_id, self.a)
            self.assertEqual(audit.employee_no, self.number)
            self.assertEqual(audit.reset_by, self.actor)
            self.assertEqual(audit.sample_ids, [self.a_sample])
            self.assertEqual(audit.sample_count, 1)
            self.assertEqual(audit.reason, "Wrong sample verified")
            self.assertTrue(audit.profile_photo_cleared)
            self.assertIsNotNone(audit.reset_at.utcoffset())
            audit_id = audit.id
            await session.delete(await session.get(EmployeeModel, self.a))
        async with self.factory() as session:
            audit = await session.get(FaceEnrollmentResetModel, audit_id)
            self.assertIsNotNone(audit)
            self.assertEqual(audit.employee_id, self.a)

    async def test_missing_audit_table_blocks_reset_without_altering_samples_or_photos(self):
        async with self.engine.begin() as connection:
            await connection.execute(text(
                "ALTER TABLE biometric.face_enrollment_resets RENAME TO face_enrollment_resets_unavailable"
            ))
        try:
            with self.assertLogs("app.enrollment.application.management", level="ERROR"):
                response = await self.reset()
            self.assertEqual(response.status, 503)
            self.assertIn("audit record could not be saved", response.body["detail"])
        finally:
            async with self.engine.begin() as connection:
                await connection.execute(text(
                    "ALTER TABLE biometric.face_enrollment_resets_unavailable RENAME TO face_enrollment_resets"
                ))
        async with self.factory() as session:
            self.assertIsNone(await session.scalar(select(FaceEnrollmentResetModel)))
            self.assertIsNotNone(await session.get(FaceEnrollmentModel, self.a_sample))
            self.assertEqual(
                (await session.get(EmployeeModel, self.a)).photo_reference, face_image_reference(self.a_image),
            )
        self.assertTrue(face_image_path(self.a_image).is_file())
        self.assertTrue(face_image_path(self.b_image).is_file())

    async def test_both_migration_paths_are_idempotent_and_protect_audit_history(self):
        path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "f2a3b4c5d6e7_face_enrollment_reset_audit.py"
        spec = importlib.util.spec_from_file_location("face_reset_audit_revision", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def revision(connection, direction):
            with patch.object(module, "op", Operations(MigrationContext.configure(connection))):
                getattr(module, direction)()

        async with self.engine.begin() as connection:
            # Empty-table rollback is safe, then test the Alembic create path from scratch.
            await connection.run_sync(lambda sync: revision(sync, "downgrade"))
            await connection.run_sync(lambda sync: revision(sync, "upgrade"))
            await connection.run_sync(lambda sync: revision(sync, "upgrade"))
        self.assertEqual((await self.reset()).status, 200)
        async with self.engine.begin() as connection:
            await apply_audit_sql(connection)
            await apply_audit_sql(connection)
            await connection.run_sync(lambda sync: revision(sync, "upgrade"))
        with self.assertRaisesRegex(DBAPIError, "Cannot remove face reset audit history"):
            async with self.engine.begin() as connection:
                await connection.run_sync(lambda sync: revision(sync, "downgrade"))
        async with self.factory() as session:
            audits = (await session.scalars(select(FaceEnrollmentResetModel))).all()
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].sample_ids, [self.a_sample])

    async def test_reset_is_targeted_audited_and_allows_correct_reenrollment(self):
        with patch("app.enrollment.infrastructure.router.log_entity_action", new=AsyncMock()) as audit:
            response = await self.reset()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["data"]["removed_count"], 1)
        self.assertIsNone(response.body["data"]["photo_reference"])
        self.assertIsNone(response.body["data"]["cleanup_warning"])
        self.assertEqual(audit.await_args.kwargs["after"], {"sample_count": 0, "reason": "Wrong sample verified"})
        self.assertNotIn("face_encoding", str(audit.await_args))
        self.assertNotIn("photo_reference", str(audit.await_args))
        self.assertFalse(face_image_path(self.a_image).exists())
        self.assertTrue(face_image_path(self.b_image).exists())
        async with self.factory() as session:
            self.assertIsNone(await session.get(FaceEnrollmentModel, self.a_sample))
            self.assertIsNotNone(await session.get(FaceEnrollmentModel, self.b_sample))
            self.assertIsNone((await session.get(EmployeeModel, self.a)).photo_reference)
            self.assertEqual((await session.get(EmployeeModel, self.b)).photo_reference, face_image_reference(self.b_image))
        photo = BytesIO()
        Image.new("RGB", (16, 16), "white").save(photo, format="PNG")
        face = SimpleNamespace(
            extract_face_encoding=Mock(return_value=[0.1, 1.0] + [0.0] * 126),
            match_threshold=lambda: 0.5,
            face_distances=face_recognition_service.face_distances,
        )
        use_case = EnrollFaceUseCase(GenUnitOfWork(self.factory), face)
        result = await use_case.execute(EnrollFaceInputDTO(self.a, photo.getvalue(), self.actor))
        self.assertEqual(result.sample_count, 1)
        self.assertTrue(face_reference_path(result.photo_reference).is_file())
        async with self.factory() as session:
            self.assertEqual((await session.get(EmployeeModel, self.a)).photo_reference, result.photo_reference)
        face.extract_face_encoding.return_value = [0.2, 1.0] + [0.0] * 126
        second = await use_case.execute(EnrollFaceInputDTO(self.a, photo.getvalue(), self.actor))
        self.assertEqual(second.sample_count, 2)
        face.extract_face_encoding.return_value = [0.4, 1.0] + [0.0] * 126
        with self.assertRaisesRegex(ValueError, "too similar.*another employee"):
            await use_case.execute(EnrollFaceInputDTO(self.a, photo.getvalue(), self.actor))
        async with self.factory() as session:
            vectors = (await session.scalars(
                select(FaceEnrollmentModel.face_encoding)
                .where(FaceEnrollmentModel.employee_id == self.a)
                .order_by(FaceEnrollmentModel.created_at)
            )).all()
            self.assertEqual([vector[0] for vector in vectors], [0.1, 0.2])

    async def test_shared_images_and_unrelated_profile_photos_are_preserved(self):
        async with self.factory.begin() as session:
            employee = await session.get(EmployeeModel, self.b)
            employee.photo_reference = face_image_reference(self.a_image)
            employee = await session.get(EmployeeModel, self.a)
            employee.photo_reference = "unrelated-profile-photo.jpg"
        result = await self.reset()
        self.assertEqual(result.body["data"]["photo_reference"], "unrelated-profile-photo.jpg")
        self.assertTrue(face_image_path(self.a_image).is_file())
        async with self.factory() as session:
            self.assertFalse((await session.scalar(select(FaceEnrollmentResetModel))).profile_photo_cleared)
        response = await request(self.app, "GET", f"/enrollment/photos/{self.a_image}.jpg")
        self.assertEqual(response.status, 200)

    async def test_failed_commit_keeps_samples_and_files(self):
        class FailingUow(GenUnitOfWork):
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                try:
                    await self.session.rollback()
                    raise RuntimeError("Simulated commit failure")
                finally:
                    await self.session.close()
        with self.assertRaisesRegex(RuntimeError, "commit failure"):
            await reset_face_enrollments(
                FailingUow(self.factory), self.a, ResetFaceEnrollmentInput(**self.payload()), self.actor,
            )
        async with self.factory() as session:
            self.assertIsNotNone(await session.get(FaceEnrollmentModel, self.a_sample))
            self.assertIsNone(await session.scalar(select(FaceEnrollmentResetModel)))
            self.assertEqual((await session.get(EmployeeModel, self.a)).photo_reference, face_image_reference(self.a_image))
        self.assertTrue(face_image_path(self.a_image).is_file())

    async def test_file_cleanup_failure_is_reported_and_orphan_photo_is_not_served(self):
        with patch.object(Path, "unlink", side_effect=OSError("Synthetic cleanup failure")), self.assertLogs(
            "app.enrollment.application.management", level="ERROR",
        ):
            result = await self.reset()
        self.assertEqual(result.status, 200)
        self.assertIn("cleanup failed", result.body["data"]["cleanup_warning"])
        self.assertTrue(face_image_path(self.a_image).is_file())
        self.assertEqual((await request(self.app, "GET", f"/enrollment/photos/{self.a_image}.jpg")).status, 404)
        async with self.factory() as session:
            self.assertIsNotNone(await session.scalar(select(FaceEnrollmentResetModel)))

    async def test_hr_override_saves_sample_and_audit_together(self):
        use_case, photo = self.similar_face_use_case()
        with self.assertRaises(FaceSimilarityConflict) as raised:
            await use_case.execute(EnrollFaceInputDTO(self.b, photo, self.actor))
        self.assertEqual([item.employee_no for item in raised.exception.conflicts], [self.number])
        self.assertIn("Closest distance 0.450; limit 0.500", str(raised.exception))
        with self.assertRaisesRegex(FaceSimilarityConflict, "similar employees changed"):
            await use_case.execute(EnrollFaceInputDTO(
                self.b, photo, self.actor, SimilarityOverride(frozenset({"SOMEONE-ELSE"}), "Verified ID"),
            ))
        self.assertEqual(await self.sample_count(self.b), 1)

        result = await use_case.execute(EnrollFaceInputDTO(
            self.b, photo, self.actor, SimilarityOverride(frozenset({self.number}), "Verified ID in person"),
        ))
        self.assertEqual(result.sample_count, 2)
        async with self.factory() as session:
            audit = (await session.scalars(select(FaceEnrollmentOverrideModel))).one()
            sample = await session.get(FaceEnrollmentModel, audit.enrollment_id)
            self.assertEqual(sample.employee_id, self.b)
            self.assertEqual(audit.conflicting_employee_ids, [self.a])
            self.assertEqual(audit.conflicting_employee_nos, [self.number])
            self.assertAlmostEqual(audit.closest_distance, 0.45)
            self.assertEqual(audit.threshold, 0.5)
            self.assertEqual(audit.approved_by, self.actor)
            self.assertEqual(audit.reason, "Verified ID in person")

    async def test_unavailable_override_audit_saves_neither_sample_nor_image(self):
        use_case, photo = self.similar_face_use_case()
        async with self.engine.begin() as connection:
            await connection.execute(text(
                "ALTER TABLE biometric.face_enrollment_similarity_overrides RENAME TO face_enrollment_overrides_off"
            ))
        try:
            with self.assertRaisesRegex(EnrollmentAuditUnavailable, "approval audit could not be recorded"):
                await use_case.execute(EnrollFaceInputDTO(
                    self.b, photo, self.actor, SimilarityOverride(frozenset({self.number}), "Verified ID"),
                ))
        finally:
            async with self.engine.begin() as connection:
                await connection.execute(text(
                    "ALTER TABLE biometric.face_enrollment_overrides_off RENAME TO face_enrollment_similarity_overrides"
                ))
        self.assertEqual(await self.sample_count(self.b), 1)
        self.assertEqual(sorted(Path(self.directory.name).iterdir()), sorted(
            [face_image_path(self.a_image), face_image_path(self.b_image)],
        ))

    async def test_invalid_vectors_cannot_be_saved_or_bypassed_by_an_hr_override(self):
        use_case, photo = self.similar_face_use_case()
        payload = EnrollFaceInputDTO(
            self.b, photo, self.actor, SimilarityOverride(frozenset({self.number}), "Verified ID"),
        )
        use_case.face_encoding_service.extract_face_encoding.return_value = [0.0] * 128
        with self.assertRaisesRegex(ValueError, "Captured face encoding is invalid"):
            await use_case.execute(payload)
        use_case.face_encoding_service.extract_face_encoding.return_value = [0.45, 1.0] + [0.0] * 126
        async with self.factory.begin() as session:
            sample = await session.get(FaceEnrollmentModel, self.a_sample)
            sample.face_encoding = [float("nan")] + [0.0] * 127
        with self.assertRaisesRegex(ValueError, "Stored face encoding is invalid"):
            await use_case.execute(payload)
        self.assertEqual(await self.sample_count(self.b), 1)
        async with self.factory() as session:
            self.assertIsNone(await session.scalar(select(FaceEnrollmentOverrideModel)))
        self.assertEqual(
            set(Path(self.directory.name).iterdir()), {face_image_path(self.a_image), face_image_path(self.b_image)},
        )

    def similar_face_use_case(self):
        photo = BytesIO()
        Image.new("RGB", (16, 16), "white").save(photo, format="PNG")
        # 0.35 from employee B's own sample, 0.45 from employee A: inside the 0.5 limit for both.
        face = SimpleNamespace(
            extract_face_encoding=Mock(return_value=[0.45, 1.0] + [0.0] * 126),
            match_threshold=lambda: 0.5,
            face_distances=face_recognition_service.face_distances,
        )
        return EnrollFaceUseCase(GenUnitOfWork(self.factory), face), photo.getvalue()

    async def sample_count(self, employee_id):
        async with self.factory() as session:
            return len((await session.scalars(
                select(FaceEnrollmentModel.id).where(FaceEnrollmentModel.employee_id == employee_id)
            )).all())

    async def test_reset_waits_for_enrollment_lock_and_rejects_stale_review(self):
        locked, release = asyncio.Event(), asyncio.Event()

        async def add_sample():
            async with self.factory.begin() as session:
                await lock_enrollment_employee(session, self.a)
                session.add(FaceEnrollmentModel(
                    employee_id=self.a, status=EnrollmentStatus.ENROLLED, face_encoding=[0.05, 1.0] + [0.0] * 126,
                ))
                locked.set()
                await release.wait()

        enrollment = asyncio.create_task(add_sample())
        await asyncio.wait_for(locked.wait(), timeout=5)
        reset = asyncio.create_task(reset_face_enrollments(
            GenUnitOfWork(self.factory), self.a, ResetFaceEnrollmentInput(**self.payload()), self.actor,
        ))
        try:
            await asyncio.sleep(0.05)
            self.assertFalse(reset.done())
        finally:
            release.set()
            results = await asyncio.wait_for(asyncio.gather(enrollment, reset, return_exceptions=True), timeout=5)
        self.assertIsNone(results[0])
        self.assertIsInstance(results[1], HTTPException)
        self.assertEqual(results[1].status_code, 409)
        self.assertTrue(face_image_path(self.a_image).exists())


if __name__ == "__main__":
    unittest.main()
