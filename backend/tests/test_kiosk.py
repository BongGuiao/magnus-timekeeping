import asyncio
import base64
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.attendance.application.use_case import (
    ClockAttendanceInputDTO, ClockAttendanceOutputDTO, ClockAttendanceUseCase,
    RecordBreakOutputDTO, RecordBreakUseCase,
)
from app.attendance.infrastructure.db_model import AttendanceModel
from app.attendance.infrastructure.kiosk_models import KioskChallengeModel, KioskDeviceModel
from app.attendance.infrastructure.kiosk_router import clock, record_break
from app.attendance.infrastructure.kiosk_service import KioskService, clock_payload, current_user_company, payload_hash, validate_challenge
from app.auth.infrastructure.db_model import UserModel
from app.core.database import init_db_models
from app.core.generics.uow import GenUnitOfWork
from app.enrollment.infrastructure.db_model import FaceEnrollmentModel
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel
from app.filemaintenance.devices.application.device_proof import verify_device_signature
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel, EmploymentAssignmentModel, EmploymentAssignmentLocationModel,
)
from app.filemaintenance.location.infrastructure.db_model import Location
from app.filemaintenance.location.infrastructure.location_type_db_model import LocationType

init_db_models()


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def device_key():
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_numbers()
    return private, {
        "kty": "EC", "crv": "P-256",
        "x": b64(public.x.to_bytes(32, "big")), "y": b64(public.y.to_bytes(32, "big")),
    }


def sign(private, message):
    r, s = decode_dss_signature(private.sign(message.encode(), ec.ECDSA(hashes.SHA256())))
    return b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


class KioskProofTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.private, self.jwk = device_key()
        self.now = datetime.now(timezone.utc)
        self.device = KioskDeviceModel(
            id=uuid4(), device_name="Synthetic test station", status="APPROVED",
            public_key_jwk=self.jwk, company_id=uuid4(), location_id=uuid4(),
        )
        self.challenge = KioskChallengeModel(
            id=uuid4(), device_id=self.device.id, purpose="CLOCK", payload_hash=payload_hash("payload"),
            message="synthetic challenge", expires_at=self.now + timedelta(seconds=90),
        )
        self.session = SimpleNamespace(
            get=AsyncMock(side_effect=[self.challenge, self.device, self.challenge]),
            commit=AsyncMock(), rollback=AsyncMock(), close=AsyncMock(),
        )
        self.service = KioskService(GenUnitOfWork(Mock(return_value=self.session)))

    def test_device_signature_uses_existing_p256_wire_format(self):
        verify_device_signature(self.jwk, b"hello", sign(self.private, "hello"))
        with self.assertRaises(ValueError):
            verify_device_signature(self.jwk, b"hello", "bad")

    def test_punch_fingerprint_binds_employee_action_and_image(self):
        user = uuid4()
        baseline = clock_payload(user, "clock_in", b"image")
        for changed in (
            clock_payload(uuid4(), "clock_in", b"image"),
            clock_payload(user, "clock_out", b"image"),
            clock_payload(user, "clock_in", b"other image"),
        ):
            self.assertNotEqual(payload_hash(baseline), payload_hash(changed))

    async def test_valid_proof_is_consumed_and_device_scope_rechecked(self):
        with patch("app.attendance.infrastructure.kiosk_service.require_active_location", new_callable=AsyncMock) as scope:
            result = await self.service.authorize(
                self.challenge.id, sign(self.private, self.challenge.message), "CLOCK", "payload",
            )
        self.assertEqual(result.id, self.device.id)
        self.assertIsNotNone(self.challenge.consumed_at)
        scope.assert_awaited_once_with(self.session, self.device.company_id, self.device.location_id)
        self.session.commit.assert_awaited_once()
        with self.assertRaises(HTTPException):
            validate_challenge(self.challenge, "CLOCK", "payload", self.now)

    async def test_wrong_device_key_is_rejected_and_attempt_consumed(self):
        other_private, _ = device_key()
        with self.assertRaises(HTTPException) as error:
            await self.service.authorize(self.challenge.id, sign(other_private, self.challenge.message), "CLOCK", "payload")
        self.assertEqual(error.exception.status_code, 403)
        self.assertIsNotNone(self.challenge.consumed_at)
        self.session.commit.assert_awaited_once()

    async def test_pending_and_revoked_kiosks_cannot_punch(self):
        for status in ("PENDING", "REVOKED"):
            self.device.status = status
            self.session.get.side_effect = [self.challenge, self.device, self.challenge]
            with self.assertRaises(HTTPException):
                await self.service.authorize(self.challenge.id, sign(self.private, self.challenge.message), "CLOCK", "payload")
            self.assertIsNone(self.challenge.consumed_at)

    async def test_missing_proof_cannot_authorize(self):
        self.session.get.side_effect = [None]
        with self.assertRaises(HTTPException):
            await self.service.authorize(uuid4(), "x" * 86, "CLOCK", "payload")

    async def test_company_requires_exactly_one_current_employment_company(self):
        company = SimpleNamespace(id=uuid4(), legal_name="Test company")
        for companies in ([], [company], [company, SimpleNamespace(id=uuid4())]):
            session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: companies)))
            if len(companies) == 1:
                self.assertEqual(await current_user_company(session, uuid4()), company)
            else:
                with self.assertRaises(HTTPException) as rejection:
                    await current_user_company(session, uuid4())
                self.assertEqual(rejection.exception.status_code, 409)

    def test_expired_wrong_purpose_and_modified_payload_are_rejected(self):
        for purpose, payload, now in (
            ("BREAK", "payload", self.now),
            ("CLOCK", "modified", self.now),
            ("CLOCK", "payload", self.now + timedelta(minutes=2)),
        ):
            with self.subTest(purpose=purpose, payload=payload):
                with self.assertRaises(HTTPException):
                    validate_challenge(self.challenge, purpose, payload, now)

    async def test_kiosk_route_fails_closed_before_attendance_processing(self):
        service = SimpleNamespace(
            authorize=AsyncMock(side_effect=HTTPException(403, "Device not registered")),
            employee=AsyncMock(),
        )
        use_case = SimpleNamespace(execute=AsyncMock())
        with self.assertRaises(HTTPException):
            await clock(
                request=Request({"type": "http", "headers": []}),
                file=UploadFile(io.BytesIO(b"image"), filename="face.jpg"),
                user_id=uuid4(), action="clock_in", challenge_id=uuid4(), signature="x" * 86,
                service=service, use_case=use_case, es_client=None,
            )
        use_case.execute.assert_not_awaited()

    async def test_kiosk_routes_attribute_employee_and_station_separately(self):
        user_id = uuid4()
        service = SimpleNamespace(
            authorize=AsyncMock(return_value=self.device), employee=AsyncMock(),
        )
        for action in ("clock_in", "clock_out", "first_break_out_at"):
            is_break = action == "first_break_out_at"
            result = (
                RecordBreakOutputDTO("Synthetic Employee", "TEST", action, self.now.isoformat())
                if is_break else ClockAttendanceOutputDTO("Synthetic Employee", "TEST", action, self.now.isoformat())
            )
            use_case = SimpleNamespace(execute=AsyncMock(return_value=result))
            with (
                patch("app.attendance.infrastructure.kiosk_router.CeleryRecentAttendanceRefresher"),
                patch("app.attendance.infrastructure.kiosk_router.log_entity_action", new_callable=AsyncMock) as audit,
            ):
                endpoint = record_break if is_break else clock
                await endpoint(
                    request=Request({"type": "http", "headers": []}),
                    file=UploadFile(io.BytesIO(b"image"), filename="face.jpg"),
                    user_id=user_id, action=action, challenge_id=uuid4(), signature="x" * 86,
                    service=service, use_case=use_case, es_client=None,
                )
            dto = use_case.execute.await_args.args[0]
            self.assertEqual(dto.actor_id, user_id)
            self.assertEqual(dto.punch_metadata["performed_by"], str(user_id))
            self.assertEqual(dto.punch_metadata["kiosk_device_name"], self.device.device_name)
            self.assertEqual(dto.punch_metadata["kiosk_device_id"], str(self.device.id))
            self.assertEqual(audit.await_args.kwargs["user_id"], user_id)
            self.assertEqual(audit.await_args.kwargs["action"], "CREATE" if action == "clock_in" else "UPDATE")
            self.assertEqual(audit.await_args.kwargs["after"]["kiosk_device_name"], self.device.device_name)


TEST_DATABASE_URL = os.getenv("KIOSK_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "Requires a migrated, disposable kiosk_test_* database.")
class KioskDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_scope_revocation_replay_and_real_punch_processing(self):
        url = make_url(TEST_DATABASE_URL)
        if not (url.database or "").startswith("kiosk_test_"):
            raise RuntimeError("Kiosk integration tests require a disposable kiosk_test_* database.")
        engine = create_async_engine(url)
        self.addAsyncCleanup(engine.dispose)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        service = KioskService(GenUnitOfWork(factory))
        private, jwk = device_key()
        device_id, company_id, location_id, employee_id, user_id = [uuid4() for _ in range(5)]
        now = datetime.now(timezone.utc)
        prefix = uuid4().hex[:8]
        async with factory.begin() as session:
            session.add(CompanyModel(id=company_id, company_code=prefix, legal_name="Synthetic kiosk test", status="ACTIVE"))
            session.add(EmployeeModel(id=employee_id, employee_no=prefix, first_name="Synthetic", last_name="Kiosk"))
            await session.flush()
            session.add(LocationType(company_id=company_id, location_type="TEST", display_name="Test", sort_order=0))
            await session.flush()
            session.add(Location(id=location_id, company_id=company_id, location_code="TEST", location_name="Test station", location_type="TEST"))
            session.add(UserModel(id=user_id, employee_id=employee_id, username=prefix, password_hash="not-a-login", account_status="ACTIVE"))
            await session.flush()
            assignment = EmploymentAssignmentModel(
                employee_id=employee_id, company_id=company_id, primary_location_id=location_id,
                employment_type="REGULAR", employee_category="STAFF", hire_date=now.date(),
                effective_from=now.date() - timedelta(days=1),
            )
            session.add(assignment)
            session.add(FaceEnrollmentModel(employee_id=employee_id, face_encoding=[0.0] * 128, status="ENROLLED"))

        pairing = await service.enroll(device_id, "Test station", jwk)
        self.assertEqual(pairing["status"], "PENDING")
        with self.assertRaises(HTTPException):
            await service.challenge(device_id, "CLOCK", payload_hash("payload"))
        # Approve using the same API operation used by the administrator screen.
        from app.attendance.infrastructure.kiosk_router import Approval, approve, revoke
        await approve(
            Approval(pairing_code=pairing["pairing_code"], company_id=uuid4(), location_id=location_id),
            claims={"sub": str(user_id)}, uow=GenUnitOfWork(factory), es_client=None,
        )

        async def authorize(purpose, payload):
            challenge = await service.challenge(device_id, purpose, payload_hash(payload))
            signature = sign(private, challenge["message"])
            device = await service.authorize(UUID(challenge["challenge_id"]), signature, purpose, payload)
            with self.assertRaises(HTTPException):
                await service.authorize(UUID(challenge["challenge_id"]), signature, purpose, payload)
            return device

        device = await authorize("IDENTIFY", prefix)
        self.assertEqual(device.company_id, company_id)
        from app.attendance.infrastructure.kiosk_router import get_company, list_devices
        context = await get_company(claims={"sub": str(user_id)}, uow=GenUnitOfWork(factory))
        self.assertEqual(context.data["id"], company_id)
        listed = await list_devices(claims={"sub": str(user_id)}, uow=GenUnitOfWork(factory))
        self.assertEqual([item["id"] for item in listed.data], [device_id])
        user, employee = await service.employee(device, code=prefix)
        self.assertEqual(user.id, user_id)
        self.assertEqual(employee.id, employee_id)
        with self.assertRaises(HTTPException):
            await service.employee(device, user_id=uuid4())
        async with factory.begin() as session:
            assignment = await session.scalar(select(EmploymentAssignmentModel).where(
                EmploymentAssignmentModel.employee_id == employee_id,
            ))
            assignment.primary_location_id = None
            assignment_id = assignment.id
        with self.assertRaises(HTTPException):
            await service.employee(device, code=prefix)
        async with factory.begin() as session:
            session.add(EmploymentAssignmentLocationModel(
                assignment_id=assignment_id, company_id=company_id, location_id=location_id,
            ))
        await service.employee(device, code=prefix)
        async with factory.begin() as session:
            account = await session.get(UserModel, user_id)
            account.is_active = False
        with self.assertRaises(HTTPException):
            await service.employee(device, code=prefix)
        async with factory.begin() as session:
            account = await session.get(UserModel, user_id)
            account.is_active = True
        # Recheck persisted status after identification, not only the cached UI result.
        for model, record_id, field, disabled, enabled in (
            (EmployeeModel, employee_id, "is_active", False, True),
            (EmployeeModel, employee_id, "record_status", "ARCHIVED", "ACTIVE"),
            (UserModel, user_id, "is_active", False, True),
            (UserModel, user_id, "account_status", "PENDING", "ACTIVE"),
            (EmploymentAssignmentModel, assignment_id, "is_active", False, True),
            (EmploymentAssignmentModel, assignment_id, "status", "INACTIVE", "ACTIVE"),
        ):
            with self.subTest(model=model.__name__, field=field):
                async with factory.begin() as session:
                    row = await session.get(model, record_id)
                    setattr(row, field, disabled)
                for lookup in ({"code": prefix}, {"user_id": user_id}):
                    with self.assertRaises(HTTPException) as rejection:
                        await service.employee(device, **lookup)
                    self.assertEqual(rejection.exception.status_code, 403)
                async with factory.begin() as session:
                    row = await session.get(model, record_id)
                    setattr(row, field, enabled)
                await service.employee(device, user_id=user_id)
        # A location outside the user's company cannot be approved.
        foreign_pairing = await service.enroll(uuid4(), "Wrong location station", jwk)
        with self.assertRaises(HTTPException):
            await approve(
                Approval(pairing_code=foreign_pairing["pairing_code"], location_id=uuid4()),
                claims={"sub": str(user_id)}, uow=GenUnitOfWork(factory), es_client=None,
            )
        challenge = await service.challenge(device_id, "STATUS", payload_hash(""))
        async def consume_once():
            return await KioskService(GenUnitOfWork(factory)).authorize(
                UUID(challenge["challenge_id"]), sign(private, challenge["message"]), "STATUS", "",
            )
        concurrent = await asyncio.gather(consume_once(), consume_once(), return_exceptions=True)
        self.assertEqual(sum(isinstance(item, KioskDeviceModel) for item in concurrent), 1)
        self.assertEqual(sum(isinstance(item, HTTPException) for item in concurrent), 1)

        face = SimpleNamespace(
            extract_face_encoding=lambda image: [0.0] * 128,
            find_best_match=lambda candidate, known: (employee_id, 0.0),
        )
        use_case = ClockAttendanceUseCase(GenUnitOfWork(factory), face)
        with patch("app.attendance.infrastructure.kiosk_router.CeleryRecentAttendanceRefresher") as refresh:
            refresh.return_value.request_refresh = Mock()
            challenge = await service.challenge(device_id, "CLOCK", payload_hash(clock_payload(user_id, "clock_in", b"image")))
            result = await clock(
                request=Request({"type": "http", "headers": []}),
                file=UploadFile(io.BytesIO(b"image"), filename="face.jpg"), user_id=user_id,
                action="clock_in", challenge_id=UUID(challenge["challenge_id"]),
                signature=sign(private, challenge["message"]), service=service, use_case=use_case, es_client=None,
            )
        self.assertEqual(result.data.action, "clock_in")
        async with factory() as session:
            record = await session.scalar(select(AttendanceModel).where(AttendanceModel.user_id == user_id))
            self.assertEqual(record.record_status, "VALID")
            self.assertEqual(record.punch_metadata["clock_in"]["clock_policy"]["kiosk_device_id"], str(device_id))
            self.assertEqual(record.created_by, user_id)
            self.assertEqual(record.updated_by, user_id)
            self.assertEqual(record.punch_metadata["clock_in"]["performed_by"], str(user_id))
            self.assertEqual(record.punch_metadata["clock_in"]["kiosk_device_name"], "Test station")
        # A second Time In cannot turn into a Time Out, even with a valid new proof.
        with self.assertRaisesRegex(ValueError, "conflicts"):
            await use_case.execute(ClockAttendanceInputDTO(
                user_id=user_id, image_bytes=b"image", requested_action="clock_in",
            ))
        async with factory.begin() as session:
            record = await session.scalar(select(AttendanceModel).where(AttendanceModel.user_id == user_id))
            record.clock_in_at = now - timedelta(minutes=15)
            record.updated_by = uuid4()
        for action in ("first_break_out_at", "first_break_in_at"):
            with patch("app.attendance.infrastructure.kiosk_router.CeleryRecentAttendanceRefresher"):
                challenge = await service.challenge(device_id, "BREAK", payload_hash(clock_payload(user_id, action, b"image")))
                await record_break(
                    request=Request({"type": "http", "headers": []}),
                    file=UploadFile(io.BytesIO(b"image"), filename="face.jpg"), user_id=user_id,
                    action=action, challenge_id=UUID(challenge["challenge_id"]),
                    signature=sign(private, challenge["message"]), service=service,
                    use_case=RecordBreakUseCase(GenUnitOfWork(factory), face), es_client=None,
                )
            async with factory() as session:
                record = await session.scalar(select(AttendanceModel).where(AttendanceModel.user_id == user_id))
                self.assertEqual(record.created_by, user_id)
                self.assertEqual(record.updated_by, user_id)
                metadata = record.punch_metadata["device_proofs"][action]
                self.assertEqual(metadata["performed_by"], str(user_id))
                self.assertEqual(metadata["kiosk_device_name"], "Test station")
        async with factory.begin() as session:
            record = await session.scalar(select(AttendanceModel).where(AttendanceModel.user_id == user_id))
            record.clock_in_at = now - timedelta(minutes=10)
            record.first_break_out_at = now - timedelta(minutes=8)
            record.first_break_in_at = now - timedelta(minutes=6)
            record.updated_by = uuid4()
            device_record = await session.get(KioskDeviceModel, device_id)
            device_record.device_name = "Renamed station"
        with patch("app.attendance.infrastructure.kiosk_router.CeleryRecentAttendanceRefresher"):
            challenge = await service.challenge(device_id, "CLOCK", payload_hash(clock_payload(user_id, "clock_out", b"image")))
            result = await clock(
                request=Request({"type": "http", "headers": []}),
                file=UploadFile(io.BytesIO(b"image"), filename="face.jpg"), user_id=user_id,
                action="clock_out", challenge_id=UUID(challenge["challenge_id"]),
                signature=sign(private, challenge["message"]), service=service, use_case=use_case, es_client=None,
            )
        self.assertEqual(result.data.action, "clock_out")
        async with factory() as session:
            record = await session.scalar(select(AttendanceModel).where(AttendanceModel.user_id == user_id))
            self.assertEqual(record.created_by, user_id)
            self.assertEqual(record.updated_by, user_id)
            self.assertEqual(record.punch_metadata["clock_in"]["kiosk_device_name"], "Test station")
            self.assertEqual(record.punch_metadata["clock_out"]["kiosk_device_name"], "Renamed station")
            self.assertEqual(record.punch_metadata["clock_out"]["performed_by"], str(user_id))
        outstanding = await service.challenge(device_id, "CLOCK", payload_hash("payload"))
        await revoke(device_id, claims={"sub": str(user_id)}, uow=GenUnitOfWork(factory), es_client=None)
        with self.assertRaises(HTTPException):
            await service.authorize(UUID(outstanding["challenge_id"]), sign(private, outstanding["message"]), "CLOCK", "payload")
        with self.assertRaises(HTTPException):
            await service.challenge(device_id, "CLOCK", payload_hash("payload"))
