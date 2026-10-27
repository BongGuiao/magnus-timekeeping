import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.auth.domain.entities.user import Role
from app.attendance.infrastructure.official_business_router import (
    OfficialBusinessCreateSchema,
    OfficialBusinessDecisionSchema,
    OfficialBusinessUpdateSchema,
    OfficialBusinessVersionSchema,
    cancel_official_business_request,
    create_official_business_request,
    decide_official_business_request,
    get_my_official_business_requests,
    get_official_business_options,
    get_pending_official_business_requests,
    submit_official_business_request,
    update_official_business_request,
)

MANILA = timezone(timedelta(hours=8))
EMPLOYEE_ID = UUID("d3fcf566-2649-403c-8bb0-14dffdffdf4d")
SUPERVISOR_ID = UUID("e33825b7-82c8-4730-b4ae-dd115d74d51b")
COMPANY_A_GEOFENCE = UUID("c783a7db-f2e7-4c45-8eff-684caa7ab9d5")
COMPANY_B_GEOFENCE = UUID("7cc76168-25a2-42c4-9ccf-98d4b195c6c3")


def _payload(**overrides):
    values = {
        "start_at": datetime(2026, 10, 20, 9, 0, tzinfo=MANILA),
        "end_at": datetime(2026, 10, 20, 12, 0, tzinfo=MANILA),
        "destination": "  Client office, Makati  ",
        "purpose": "  Site visit  ",
    }
    values.update(overrides)
    return values


class OfficialBusinessSchemaTests(unittest.TestCase):
    def test_trims_text_and_defaults_requested_minutes_to_duration(self):
        payload = OfficialBusinessCreateSchema(**_payload(client_name="  ", jo_reference=" JO-1 "))
        self.assertEqual(payload.destination, "Client office, Makati")
        self.assertEqual(payload.purpose, "Site visit")
        self.assertIsNone(payload.client_name)
        self.assertEqual(payload.jo_reference, "JO-1")
        self.assertEqual(payload.requested_minutes, 180)
        self.assertFalse(payload.submit)

    def test_invalid_payloads_are_rejected(self):
        cases = {
            "end before start": _payload(end_at=datetime(2026, 10, 20, 8, 0, tzinfo=MANILA)),
            "end equals start": _payload(end_at=datetime(2026, 10, 20, 9, 0, tzinfo=MANILA)),
            "naive datetime": _payload(start_at=datetime(2026, 10, 20, 9, 0)),
            "blank purpose": _payload(purpose="   "),
            "blank destination": _payload(destination=" "),
            "minutes over duration": _payload(requested_minutes=181),
            "zero minutes": _payload(requested_minutes=0),
            "too long": _payload(end_at=datetime(2026, 11, 21, 9, 0, tzinfo=MANILA)),
            "extra field": _payload(status="APPROVED"),
            "destination too long": _payload(destination="x" * 301),
        }
        for name, values in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValidationError):
                    OfficialBusinessCreateSchema(**values)

    def test_decision_minutes_rules(self):
        OfficialBusinessDecisionSchema(decision="APPROVED", approved_minutes=60, row_version=1)
        OfficialBusinessDecisionSchema(decision="REJECTED", row_version=1)
        with self.assertRaises(ValidationError):
            OfficialBusinessDecisionSchema(decision="APPROVED", row_version=1)
        with self.assertRaises(ValidationError):
            OfficialBusinessDecisionSchema(decision="REJECTED", approved_minutes=5, row_version=1)


class _SessionUow:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            await self.session.flush()
        return False


class OfficialBusinessDatabaseTests(unittest.IsolatedAsyncioTestCase):
    """Runs endpoint functions against the real database inside a rolled-back transaction."""

    async def asyncSetUp(self):
        from app.core.database import AsyncSessionLocal

        self.session = AsyncSessionLocal()
        self.uow = _SessionUow(self.session)

    async def asyncTearDown(self):
        from app.core.database import engine

        await self.session.rollback()
        await self.session.close()
        await engine.dispose()

    def _claims(self, employee_id, role="SUPERVISOR"):
        return {"sub": str(employee_id), "employee_id": str(employee_id), "role": role}

    async def _create(self, employee_id=EMPLOYEE_ID, **overrides):
        submit = overrides.pop("submit", False)
        response = await create_official_business_request(
            OfficialBusinessCreateSchema(**_payload(**overrides), submit=submit),
            claims=self._claims(employee_id, "EMPLOYEE"),
            uow=self.uow,
            es_client=None,
        )
        return response.data

    async def test_model_maps_to_existing_table_and_options_are_company_scoped(self):
        options = (await get_official_business_options(claims=self._claims(EMPLOYEE_ID), uow=self.uow)).data
        self.assertIn(COMPANY_B_GEOFENCE, {option.id for option in options.geofences})

        draft = await self._create(geofence_id=COMPANY_B_GEOFENCE, client_name="ACME")
        self.assertEqual(draft.status, "DRAFT")
        self.assertRegex(draft.request_no, r"^OB-20261020-[0-9A-F]{12}$")
        self.assertEqual(draft.requested_minutes, 180)
        self.assertIsNotNone(draft.geofence_name)

        mine = (await get_my_official_business_requests(claims=self._claims(EMPLOYEE_ID), uow=self.uow)).data
        self.assertIn(draft.id, {item.id for item in mine})
        others = (await get_my_official_business_requests(claims=self._claims(SUPERVISOR_ID), uow=self.uow)).data
        self.assertNotIn(draft.id, {item.id for item in others})

    async def test_overlap_wrong_geofence_and_unknown_vehicle_are_rejected(self):
        await self._create()
        with self.assertRaises(HTTPException) as overlap:
            await self._create(
                start_at=datetime(2026, 10, 20, 11, 0, tzinfo=MANILA),
                end_at=datetime(2026, 10, 20, 13, 0, tzinfo=MANILA),
            )
        self.assertEqual(overlap.exception.status_code, 409)

        # Adjacent periods do not overlap.
        await self._create(
            start_at=datetime(2026, 10, 20, 12, 0, tzinfo=MANILA),
            end_at=datetime(2026, 10, 20, 13, 0, tzinfo=MANILA),
        )

        # Company A geofence ends 2026-10-31; a November request falls outside its effective range.
        with self.assertRaises(HTTPException) as geofence:
            await self._create(
                start_at=datetime(2026, 11, 3, 9, 0, tzinfo=MANILA),
                end_at=datetime(2026, 11, 3, 10, 0, tzinfo=MANILA),
                geofence_id=COMPANY_A_GEOFENCE,
            )
        self.assertEqual(geofence.exception.status_code, 422)

        with self.assertRaises(HTTPException) as vehicle:
            await self._create(
                start_at=datetime(2026, 10, 21, 9, 0, tzinfo=MANILA),
                end_at=datetime(2026, 10, 21, 10, 0, tzinfo=MANILA),
                vehicle_id=uuid4(),
            )
        self.assertEqual(vehicle.exception.status_code, 422)

    async def test_filing_outside_scheduled_shift_is_rejected(self):
        # The employee's resolved shift on 2026-10-20 is 9:00 AM - 6:00 PM.
        for start_hour, end_hour in ((7, 10), (17, 19), (6, 8)):
            with self.subTest(start_hour=start_hour, end_hour=end_hour):
                with self.assertRaises(HTTPException) as outside:
                    await self._create(
                        start_at=datetime(2026, 10, 20, start_hour, 0, tzinfo=MANILA),
                        end_at=datetime(2026, 10, 20, end_hour, 0, tzinfo=MANILA),
                    )
                self.assertEqual(outside.exception.status_code, 422)
                self.assertIn("scheduled shift", outside.exception.detail)

        inside = await self._create(
            start_at=datetime(2026, 10, 20, 9, 0, tzinfo=MANILA),
            end_at=datetime(2026, 10, 20, 18, 0, tzinfo=MANILA),
        )
        self.assertEqual(inside.status, "DRAFT")

    async def test_draft_update_submit_cancel_transitions(self):
        draft = await self._create()
        claims = self._claims(EMPLOYEE_ID, "EMPLOYEE")
        updated = (
            await update_official_business_request(
                draft.id,
                OfficialBusinessUpdateSchema(**_payload(purpose="Updated"), row_version=draft.row_version),
                claims=claims, uow=self.uow, es_client=None,
            )
        ).data
        self.assertEqual(updated.purpose, "Updated")
        self.assertEqual(updated.row_version, draft.row_version + 1)

        with self.assertRaises(HTTPException) as stale:
            await submit_official_business_request(
                draft.id, OfficialBusinessVersionSchema(row_version=draft.row_version),
                claims=claims, uow=self.uow, es_client=None,
            )
        self.assertEqual(stale.exception.status_code, 409)

        submitted = (
            await submit_official_business_request(
                draft.id, OfficialBusinessVersionSchema(row_version=updated.row_version),
                claims=claims, uow=self.uow, es_client=None,
            )
        ).data
        self.assertEqual(submitted.status, "PENDING")

        with self.assertRaises(HTTPException) as edit_pending:
            await update_official_business_request(
                draft.id,
                OfficialBusinessUpdateSchema(**_payload(), row_version=submitted.row_version),
                claims=claims, uow=self.uow, es_client=None,
            )
        self.assertEqual(edit_pending.exception.status_code, 409)

        cancelled = (
            await cancel_official_business_request(
                draft.id, OfficialBusinessVersionSchema(row_version=submitted.row_version),
                claims=claims, uow=self.uow, es_client=None,
            )
        ).data
        self.assertEqual(cancelled.status, "CANCELLED")
        # Cancelled requests no longer block the same period.
        await self._create()

        with self.assertRaises(HTTPException) as other_user:
            await cancel_official_business_request(
                draft.id, OfficialBusinessVersionSchema(row_version=cancelled.row_version),
                claims=self._claims(SUPERVISOR_ID), uow=self.uow, es_client=None,
            )
        self.assertEqual(other_user.exception.status_code, 404)

    async def test_supervisor_scope_and_decisions(self):
        pending = await self._create(submit=True)
        self.assertEqual(pending.status, "PENDING")

        queue = (await get_pending_official_business_requests(claims=self._claims(SUPERVISOR_ID), uow=self.uow)).data
        self.assertIn(pending.id, {item.id for item in queue})
        own_queue = (await get_pending_official_business_requests(claims=self._claims(EMPLOYEE_ID), uow=self.uow)).data
        self.assertNotIn(pending.id, {item.id for item in own_queue})

        with self.assertRaises(HTTPException) as self_decision:
            await decide_official_business_request(
                pending.id,
                OfficialBusinessDecisionSchema(decision="APPROVED", approved_minutes=60, row_version=pending.row_version),
                claims=self._claims(EMPLOYEE_ID, Role.ADMIN.value), uow=self.uow, es_client=None,
            )
        self.assertEqual(self_decision.exception.status_code, 403)

        with self.assertRaises(HTTPException) as unrelated:
            await decide_official_business_request(
                pending.id,
                OfficialBusinessDecisionSchema(decision="REJECTED", row_version=pending.row_version),
                claims=self._claims(uuid4()), uow=self.uow, es_client=None,
            )
        self.assertEqual(unrelated.exception.status_code, 404)

        with self.assertRaises(HTTPException) as too_many:
            await decide_official_business_request(
                pending.id,
                OfficialBusinessDecisionSchema(decision="APPROVED", approved_minutes=181, row_version=pending.row_version),
                claims=self._claims(SUPERVISOR_ID), uow=self.uow, es_client=None,
            )
        self.assertEqual(too_many.exception.status_code, 422)

        approved = (
            await decide_official_business_request(
                pending.id,
                OfficialBusinessDecisionSchema(decision="APPROVED", approved_minutes=150, row_version=pending.row_version),
                claims=self._claims(SUPERVISOR_ID), uow=self.uow, es_client=None,
            )
        ).data
        self.assertEqual((approved.status, approved.approved_minutes), ("APPROVED", 150))

        rejected_source = await self._create(
            submit=True,
            start_at=datetime(2026, 10, 22, 9, 0, tzinfo=MANILA),
            end_at=datetime(2026, 10, 22, 10, 0, tzinfo=MANILA),
        )
        rejected = (
            await decide_official_business_request(
                rejected_source.id,
                OfficialBusinessDecisionSchema(decision="REJECTED", row_version=rejected_source.row_version),
                claims=self._claims(SUPERVISOR_ID), uow=self.uow, es_client=None,
            )
        ).data
        self.assertEqual((rejected.status, rejected.approved_minutes), ("REJECTED", None))


if __name__ == "__main__":
    unittest.main()
