import csv
import importlib.util
import io
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.auth.infrastructure.dependencies import (
    get_current_authorization_use_case,
    get_current_user_claims,
)
from app.core.exception_handlers import register_exception_handlers
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.leaves.application.entitlement_upload_use_case import (
    EntitlementUploadChangedError,
    EntitlementUploadInvalidError,
    EntitlementUploadUseCase,
)
from app.filemaintenance.leaves.application.leave_records_use_case import BALANCE_FIELDS
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.leaves.infrastructure.entitlement_upload_csv import (
    CSV_COLUMNS,
    MAX_ROWS_PER_UPLOAD,
    entitlement_upload_csv_template,
    read_entitlement_upload_csv,
)
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import EmployeeEntitlementModel
from app.filemaintenance.leaves.infrastructure.leave_records_dependencies import get_entitlement_upload_use_case
from app.filemaintenance.leaves.infrastructure.leave_records_router import entitlements_router

if importlib.util.find_spec("httpx") is not None:
    from fastapi.testclient import TestClient
else:
    TestClient = None


def csv_file(*rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        values = {column: "0" for column in CSV_COLUMNS}
        values.update(employee_no="0001", leave_code="VL", entitlement_year="2026")
        values.update(row)
        writer.writerow(values)
    return output.getvalue().encode("utf-8")


class ScalarResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class FakeSession:
    def __init__(self):
        self.company_a = uuid4()
        self.company_b = uuid4()
        self.first = SimpleNamespace(
            id=uuid4(), employee_no="0001", preferred_name=None, first_name="Ana", last_name="Cruz",
        )
        self.second = SimpleNamespace(
            id=uuid4(), employee_no="E002", preferred_name="Ben", first_name="Ben", last_name="Lim",
        )
        self.employees = [self.first, self.second]
        self.assignments = [
            self.assignment(self.first, self.company_a),
            self.assignment(self.second, self.company_b),
        ]
        self.day_type = self.leave_type(self.company_a, "VL", "DAYS")
        self.hour_type = self.leave_type(self.company_b, "VL", "HOURS")
        self.leave_types = [self.day_type, self.hour_type]
        self.existing = EmployeeEntitlementModel(
            id=uuid4(),
            employee_id=self.first.id,
            leave_type_id=self.day_type.id,
            entitlement_year=2026,
            opening_minutes=0,
            granted_minutes=4800,
            accrued_minutes=0,
            carryover_minutes=0,
            adjustment_minutes=0,
            used_minutes=480,
            reserved_minutes=0,
            expired_minutes=0,
            converted_minutes=0,
            available_minutes=4320,
            last_calculated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.entitlements = [self.existing]
        self.queries = []
        self.flush_error = None

    @staticmethod
    def assignment(employee, company_id):
        return SimpleNamespace(
            employee_id=employee.id, company_id=company_id, hire_date=date(2020, 1, 1),
            primary_location_id=uuid4(), effective_from=date(2020, 1, 1), effective_to=None,
            separation_date=None, is_active=True, status="ACTIVE",
        )

    @staticmethod
    def leave_type(company_id, code, unit):
        return SimpleNamespace(
            id=uuid4(), company_id=company_id, leave_code=code, leave_name="Vacation",
            unit_type=unit, is_active=True, status="ACTIVE", effective_from=date(2020, 1, 1),
            effective_to=None, minimum_service_months=0,
        )

    async def execute(self, statement):
        self.queries.append(statement)
        model = statement.column_descriptions[0]["entity"]
        if model is EmployeeModel:
            return ScalarResult(self.employees)
        if model is EmploymentAssignmentModel:
            return ScalarResult([
                item for item in self.assignments
                if item.is_active and item.status == "ACTIVE" and item.primary_location_id is not None
            ])
        if model is LeaveTypeModel:
            return ScalarResult([
                item for item in self.leave_types if item.is_active and item.status == "ACTIVE"
            ])
        if model is EmployeeEntitlementModel:
            types = {leave_type.id: leave_type for leave_type in self.leave_types}
            return ScalarResult([
                (entitlement, types[entitlement.leave_type_id])
                for entitlement in self.entitlements if entitlement.leave_type_id in types
            ])
        raise AssertionError(f"Unexpected query: {model}")

    def add(self, model):
        self.entitlements.append(model)

    async def flush(self):
        if self.flush_error:
            raise self.flush_error
        for model in self.entitlements:
            if model.id is None:
                model.id = uuid4()


class FakeUnitOfWork:
    def __init__(self, session):
        self.session = session
        self.rolled_back = False

    async def __aenter__(self):
        self.original = list(self.session.entitlements)
        self.values = [
            (model, {field: getattr(model, field) for field in (
                *BALANCE_FIELDS, "available_minutes", "last_calculated_at",
            )})
            for model in self.original
        ]
        self.rolled_back = False
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            self.rolled_back = True
            self.session.entitlements[:] = self.original
            for model, values in self.values:
                for field, value in values.items():
                    setattr(model, field, value)


class EntitlementCsvTests(unittest.TestCase):
    def test_template_has_exact_required_columns_and_requires_data(self):
        template = entitlement_upload_csv_template()
        self.assertEqual(template, ",".join(CSV_COLUMNS) + "\r\n")
        self.assertIn("at least one", read_entitlement_upload_csv(template.encode()).file_errors[0])

    def test_bom_windows_encoding_normalized_headers_and_blank_rows(self):
        content = csv_file({"employee_no": "0001", "leave_code": "VL"})
        text = "\ufeff" + content.decode().replace("employee_no", "Employee No", 1)
        text += "\r\n"
        result = read_entitlement_upload_csv(text.encode("utf-8"))
        self.assertEqual(result.file_errors, ())
        self.assertEqual((len(result.rows), result.rows[0].row_no), (1, 2))
        self.assertEqual(result.rows[0].values["employee_no"], "0001")
        windows = csv_file({"employee_no": "A\u00f1o"}).decode().encode("cp1252")
        self.assertEqual(read_entitlement_upload_csv(windows).rows[0].values["employee_no"], "A\u00f1o")

    def test_rejects_bad_headers_malformed_rows_and_extra_values(self):
        for content, message in (
            (b"", "empty"),
            (b"employee_no,employee_no,extra\n", "Duplicate column"),
            (b"employee_no,employee_no,extra\n", "Unknown column"),
            (b"employee_no,employee_no,extra\n", "Missing required"),
            ((entitlement_upload_csv_template() + '"unterminated\n').encode(), "malformed"),
            ((entitlement_upload_csv_template() + ",".join(["x"] * 13) + "\n").encode(), "more values"),
        ):
            with self.subTest(message=message):
                self.assertIn(message, " ".join(read_entitlement_upload_csv(content).file_errors))

    def test_row_limit_is_enforced(self):
        row = {"employee_no": "0001"}
        self.assertFalse(read_entitlement_upload_csv(csv_file(*([row] * MAX_ROWS_PER_UPLOAD))).file_errors)
        too_many = csv_file(*([row] * (MAX_ROWS_PER_UPLOAD + 1)))
        self.assertIn(
            "1000 rows",
            " ".join(read_entitlement_upload_csv(too_many).file_errors),
        )


class EntitlementUploadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = FakeSession()
        self.uow = FakeUnitOfWork(self.session)
        self.use_case = EntitlementUploadUseCase(self.uow)

    async def test_preview_and_atomic_apply_create_and_update_across_companies(self):
        content = csv_file(
            {"employee_no": "0001", "opening_balance": "1", "granted": "12", "accrued": ".5",
             "carryover": "1", "adjustment": "-.5", "used": "2", "reserved": "1", "expired": ".5"},
            {"employee_no": "E002", "granted": "8", "used": "2"},
        )
        preview = await self.use_case.preview(content)
        self.assertTrue(preview.is_valid)
        self.assertEqual([row.action for row in preview.rows], ["UPDATE", "CREATE"])
        self.assertEqual([row.unit_type for row in preview.rows], ["DAYS", "HOURS"])
        self.assertEqual(preview.rows[0].before["available_minutes"], 4320)
        self.assertEqual(preview.rows[0].after["available_minutes"], 5040)
        self.assertEqual(preview.rows[1].after["available_minutes"], 360)
        self.assertEqual(len(self.session.entitlements), 1)

        result = await self.use_case.apply(content, preview.preview_token)
        self.assertEqual([change.action for change in result.changes], ["UPDATE", "CREATE"])
        self.assertEqual(result.changes[0].before.used_minutes, 480)
        self.assertEqual(result.changes[0].after.used_minutes, 960)
        self.assertEqual(result.changes[0].after.available_minutes, 5040)
        self.assertEqual(result.changes[1].after.available_minutes, 360)
        self.assertEqual(result.changes[1].after.employee_id, self.session.second.id)
        self.assertEqual(len(self.session.entitlements), 2)
        entitlement_queries = [
            statement for statement in self.session.queries
            if statement.column_descriptions[0]["entity"] is EmployeeEntitlementModel
        ]
        self.assertNotIn("FOR UPDATE", str(entitlement_queries[0].compile(dialect=postgresql.dialect())))
        self.assertIn("FOR UPDATE", str(entitlement_queries[-1].compile(dialect=postgresql.dialect())))

    async def test_invalid_rows_and_duplicates_never_change_valid_rows(self):
        content = csv_file(
            {"employee_no": "0001"},
            {"employee_no": "E002", "granted": "-1"},
            {"employee_no": "e002", "granted": "2"},
            {"employee_no": "UNKNOWN"},
            {"employee_no": "0001", "leave_code": "UNKNOWN"},
        )
        preview = await self.use_case.preview(content)
        self.assertFalse(preview.is_valid)
        self.assertTrue(any("Duplicate" in message for message in preview.rows[1].errors))
        self.assertTrue(any("cannot be negative" in message for message in preview.rows[1].errors))
        self.assertTrue(any("not found" in message for message in preview.rows[3].errors))
        self.assertTrue(any("No currently active" in message for message in preview.rows[4].errors))
        with self.assertRaises(EntitlementUploadInvalidError):
            await self.use_case.apply(content, "0" * 64)
        self.assertEqual(len(self.session.entitlements), 1)
        self.assertEqual(self.session.existing.used_minutes, 480)

    async def test_eligibility_and_ambiguous_types_follow_manual_grant_rules(self):
        self.session.day_type.minimum_service_months = 9999
        preview = await self.use_case.preview(csv_file({}))
        self.assertIn("required service months", " ".join(preview.rows[0].errors))
        self.session.day_type.minimum_service_months = 0
        self.session.leave_types.append(self.session.leave_type(self.session.company_a, "VL", "DAYS"))
        preview = await self.use_case.preview(csv_file({}))
        self.assertIn("Multiple active leave types", " ".join(preview.rows[0].errors))
        self.session.assignments[0].is_active = False
        preview = await self.use_case.preview(csv_file({}))
        self.assertIn("no active employment assignment", " ".join(preview.rows[0].errors))

    async def test_historical_entitlement_with_same_code_is_not_silently_duplicated(self):
        historical = self.session.leave_type(self.session.company_a, "VL", "DAYS")
        historical.is_active = False
        self.session.leave_types.append(historical)
        self.session.existing.leave_type_id = historical.id
        content = csv_file({"granted": "12"})
        preview = await self.use_case.preview(content)
        self.assertFalse(preview.is_valid)
        self.assertIn("another version", " ".join(preview.rows[0].errors))
        with self.assertRaises(EntitlementUploadInvalidError):
            await self.use_case.apply(content, "0" * 64)
        self.assertEqual(len(self.session.entitlements), 1)
        self.assertEqual(self.session.existing.granted_minutes, 4800)

    async def test_decimal_units_round_like_form_and_minutes_require_whole_values(self):
        content = csv_file({"employee_no": "E002", "opening_balance": "-.025", "granted": ".025"})
        preview = await self.use_case.preview(content)
        self.assertTrue(preview.is_valid)
        self.assertEqual(preview.rows[0].after["opening_minutes"], -1)
        self.assertEqual(preview.rows[0].after["granted_minutes"], 2)
        self.session.hour_type.unit_type = "MINUTES"
        preview = await self.use_case.preview(content)
        self.assertIn("whole number", " ".join(preview.rows[0].errors))

    async def test_missing_numbers_scientific_notation_and_integer_overflow_are_errors(self):
        for changes, text in (
            ({"granted": ""}, "enter 0"),
            ({"granted": "NaN"}, "must be a number"),
            ({"granted": "1e10"}, "must be a number"),
            ({"granted": "999999999"}, "too large"),
            ({"granted": "4473924", "accrued": "4473924"}, "calculated available balance"),
            ({"entitlement_year": "2201"}, "1900 to 2200"),
        ):
            with self.subTest(changes=changes):
                preview = await self.use_case.preview(csv_file(changes))
                self.assertFalse(preview.is_valid)
                self.assertIn(text, " ".join(preview.rows[0].errors))

    async def test_changed_existing_balance_or_file_requires_a_new_preview(self):
        content = csv_file({"granted": "12"})
        preview = await self.use_case.preview(content)
        self.session.existing.used_minutes += 60
        with self.assertRaises(EntitlementUploadChangedError):
            await self.use_case.apply(content, preview.preview_token)
        self.assertTrue(self.uow.rolled_back)
        self.assertEqual(self.session.existing.used_minutes, 540)
        self.assertEqual(self.session.existing.granted_minutes, 4800)
        fresh = await self.use_case.preview(content)
        with self.assertRaises(EntitlementUploadChangedError):
            await self.use_case.apply(content + b"\r\n", fresh.preview_token)

    async def test_concurrent_create_and_missing_token_are_rejected(self):
        content = csv_file({"employee_no": "E002"})
        preview = await self.use_case.preview(content)
        self.session.entitlements.append(EmployeeEntitlementModel(
            id=uuid4(), employee_id=self.session.second.id, leave_type_id=self.session.hour_type.id,
            entitlement_year=2026, **{field: 0 for field in BALANCE_FIELDS},
            available_minutes=0, last_calculated_at=None,
        ))
        with self.assertRaises(EntitlementUploadChangedError):
            await self.use_case.apply(content, preview.preview_token)
        with self.assertRaises(EntitlementUploadInvalidError):
            await self.use_case.apply(content, "not-a-preview")

    async def test_unique_constraint_race_rolls_back_all_changes(self):
        content = csv_file({"granted": "12"}, {"employee_no": "E002"})
        preview = await self.use_case.preview(content)
        original = Exception("duplicate")
        original.constraint_name = "uq_employee_entitlements_employee_type_year"
        self.session.flush_error = IntegrityError("insert", {}, original)
        with self.assertRaises(EntitlementUploadChangedError):
            await self.use_case.apply(content, preview.preview_token)
        self.assertTrue(self.uow.rolled_back)
        self.assertEqual(len(self.session.entitlements), 1)
        self.assertEqual(self.session.existing.granted_minutes, 4800)


@unittest.skipIf(TestClient is None, "HTTP API tests require the optional httpx test dependency.")
class EntitlementUploadApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        register_exception_handlers(self.app)
        self.app.include_router(entitlements_router)
        self.claims = {"sub": str(uuid4()), "email": "hr@example.invalid"}
        self.permissions = ["leave.manage"]
        self.authorization = SimpleNamespace(execute=AsyncMock(
            side_effect=lambda _user_id: SimpleNamespace(permission_codes=self.permissions)
        ))
        self.session = FakeSession()
        self.use_case = EntitlementUploadUseCase(FakeUnitOfWork(self.session))
        self.app.dependency_overrides.update({
            get_current_user_claims: lambda: self.claims,
            get_current_authorization_use_case: lambda: self.authorization,
            get_entitlement_upload_use_case: lambda: self.use_case,
            get_audit_es_client: lambda: None,
        })
        self.client = TestClient(self.app)

    def post_file(self, path, content, *, name="balances.csv", token=None):
        data = {"preview_token": token} if token is not None else {}
        return self.client.post(path, data=data, files={"file": (name, content, "text/csv")})

    def test_permissions_are_required_for_template_preview_and_apply(self):
        self.permissions = []
        self.assertEqual(self.client.get("/employee-entitlements/upload/template").status_code, 403)
        self.assertEqual(self.post_file("/employee-entitlements/upload/preview", csv_file({})).status_code, 403)
        self.assertEqual(
            self.post_file("/employee-entitlements/upload", csv_file({}), token="0" * 64).status_code, 403
        )

    def test_anonymous_access_is_rejected(self):
        del self.app.dependency_overrides[get_current_user_claims]
        self.assertEqual(self.client.get("/employee-entitlements/upload/template").status_code, 403)
        self.assertEqual(self.post_file("/employee-entitlements/upload/preview", csv_file({})).status_code, 403)
        self.assertEqual(
            self.post_file("/employee-entitlements/upload", csv_file({}), token="0" * 64).status_code, 403
        )

    def test_download_preview_apply_and_audit_each_changed_record(self):
        template = self.client.get("/employee-entitlements/upload/template")
        self.assertEqual(template.status_code, 200)
        self.assertEqual(template.text, entitlement_upload_csv_template())
        self.assertIn("attachment", template.headers["content-disposition"])
        content = csv_file({"granted": "12"}, {"employee_no": "E002", "granted": "8"})
        preview = self.post_file("/employee-entitlements/upload/preview", content)
        self.assertEqual(preview.status_code, 200)
        data = preview.json()["data"]
        self.assertEqual([row["action"] for row in data["rows"]], ["UPDATE", "CREATE"])
        with (
            patch("app.filemaintenance.leaves.infrastructure.leave_records_router.log_entity_action", new_callable=AsyncMock) as audit,
            patch("app.filemaintenance.leaves.infrastructure.leave_records_router._queue_leave_dashboard_refresh") as refresh,
        ):
            response = self.post_file("/employee-entitlements/upload", content, token=data["preview_token"])
        self.assertEqual(response.status_code, 200)
        result = response.json()["data"]
        self.assertEqual((result["created"], result["updated"]), (1, 1))
        self.assertEqual(len(result["entitlement_ids"]), 2)
        self.assertEqual(set(result["employee_ids"]), {str(self.session.first.id), str(self.session.second.id)})
        self.assertEqual(audit.await_count, 2)
        self.assertEqual([call.kwargs["action"] for call in audit.await_args_list], ["UPDATE", "CREATE"])
        self.assertIsNotNone(audit.await_args_list[0].kwargs["before"])
        self.assertEqual(refresh.call_count, 2)

    def test_multiple_changes_for_one_employee_queue_one_dashboard_refresh(self):
        content = csv_file({"granted": "12"}, {"entitlement_year": "2027", "granted": "10"})
        preview = self.post_file("/employee-entitlements/upload/preview", content).json()["data"]
        with patch("app.filemaintenance.leaves.infrastructure.leave_records_router._queue_leave_dashboard_refresh") as refresh:
            response = self.post_file("/employee-entitlements/upload", content, token=preview["preview_token"])
        self.assertEqual(response.status_code, 200)
        refresh.assert_called_once_with(self.session.first.id)

    def test_invalid_preview_cannot_be_applied(self):
        content = csv_file({"granted": "-1"})
        preview = self.post_file("/employee-entitlements/upload/preview", content)
        self.assertEqual(preview.status_code, 200)
        data = preview.json()["data"]
        self.assertFalse(data["is_valid"])
        self.assertIsNone(data["preview_token"])
        response = self.post_file("/employee-entitlements/upload", content, token="0" * 64)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.session.existing.granted_minutes, 4800)

    def test_invalid_type_size_and_missing_or_invalid_token(self):
        path = "/employee-entitlements/upload/preview"
        self.assertEqual(self.post_file(path, b"x", name="balances.txt").status_code, 400)
        self.assertEqual(self.post_file(path, b"x" * (1024 * 1024 + 1)).status_code, 413)
        self.assertEqual(self.post_file("/employee-entitlements/upload", csv_file({})).status_code, 422)
        self.assertEqual(
            self.post_file("/employee-entitlements/upload", csv_file({}), token="z" * 64).status_code, 422
        )

    def test_stale_preview_returns_conflict_without_changes(self):
        content = csv_file({"granted": "12"})
        token = self.post_file("/employee-entitlements/upload/preview", content).json()["data"]["preview_token"]
        self.session.existing.used_minutes += 60
        response = self.post_file("/employee-entitlements/upload", content, token=token)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Check the file again", response.json()["detail"])
        self.assertEqual(self.session.existing.granted_minutes, 4800)


if __name__ == "__main__":
    unittest.main()
