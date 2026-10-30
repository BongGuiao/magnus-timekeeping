import importlib.util
import io
import unittest
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.core.exception_handlers import register_exception_handlers
from app.filemaintenance.employees.application.related_use_case import _normalize_assignment
from app.filemaintenance.employees.application.related_use_case import (
    CreateEmploymentAssignmentUseCase,
    CreateEmploymentAssignmentsBatchUseCase,
    UpdateEmploymentAssignmentUseCase,
)
from app.filemaintenance.employees.domain.entities.employment_assignment import EmploymentAssignmentEntity
from app.filemaintenance.employees.infrastructure.db_model import EmploymentAssignmentModel
from app.filemaintenance.operational_groups.application.use_case import (
    CreateOperationalGroupUseCase,
    DeleteOperationalGroupUseCase,
    ListOperationalGroupsUseCase,
    OperationalGroupConflictError,
    OperationalGroupNotFoundError,
    UpdateOperationalGroupUseCase,
    RestoreOperationalGroupUseCase,
    ensure_operational_group_allowed,
)
from app.filemaintenance.operational_groups.domain.entities.operational_group import OperationalGroupEntity
from app.filemaintenance.operational_groups.infrastructure.router import (
    OperationalGroupCreateSchema,
    OperationalGroupUpdateSchema,
    get_create_use_case,
    get_delete_use_case,
    get_list_use_case,
    get_update_use_case,
    get_restore_use_case,
    router,
)


class FakeUnitOfWork:
    def __init__(self, repository=None, session=None):
        self.repository = repository
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get_repo(self, *_args):
        return self.repository


def group_record(company_id=None, code="NEW_GROUP", active=True):
    return OperationalGroupEntity(company_id or uuid4(), code, "New group", 10, active)


class OperationalGroupUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_filters_company_and_active_status_and_orders_without_truncation(self):
        group = group_record()
        session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [group])))
        result = await ListOperationalGroupsUseCase(FakeUnitOfWork(session=session)).execute(group.company_id)
        self.assertEqual(result, [group])
        query = session.scalars.call_args.args[0]
        sql = str(query.compile(dialect=postgresql.dialect()))
        self.assertIn("is_active IS true", sql)
        self.assertIn("ORDER BY core.operational_groups.sort_order, core.operational_groups.operational_group", sql)
        self.assertNotIn("LIMIT", sql)
        self.assertIn(group.company_id, query.compile().params.values())

    async def test_management_list_can_include_inactive_groups(self):
        session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
        await ListOperationalGroupsUseCase(FakeUnitOfWork(session=session)).execute(uuid4(), True)
        self.assertNotIn("is_active IS true", str(session.scalars.call_args.args[0]))

    async def test_create_accepts_custom_code_for_company(self):
        group = group_record()
        repo = SimpleNamespace(find_one=AsyncMock(return_value=None), add=AsyncMock(return_value=group))
        session = SimpleNamespace(scalar=AsyncMock(return_value=group.company_id))
        result = await CreateOperationalGroupUseCase(FakeUnitOfWork(repo, session)).execute(vars(group))
        self.assertEqual(result, group)
        repo.add.assert_awaited_once_with(group)

    async def test_create_rejects_missing_company(self):
        repo = SimpleNamespace(add=AsyncMock())
        session = SimpleNamespace(scalar=AsyncMock(return_value=None))
        with self.assertRaisesRegex(ValueError, "Company not found"):
            await CreateOperationalGroupUseCase(FakeUnitOfWork(repo, session)).execute(vars(group_record()))
        repo.add.assert_not_awaited()

    async def test_duplicate_code_including_inactive_is_conflict(self):
        group = group_record(active=False)
        repo = SimpleNamespace(find_one=AsyncMock(return_value=group))
        session = SimpleNamespace(scalar=AsyncMock(return_value=group.company_id))
        with self.assertRaises(OperationalGroupConflictError):
            await CreateOperationalGroupUseCase(FakeUnitOfWork(repo, session)).execute(vars(group))

    async def test_concurrent_duplicate_database_error_is_conflict(self):
        group = group_record()
        repo = SimpleNamespace(
            find_one=AsyncMock(return_value=None),
            add=AsyncMock(side_effect=IntegrityError("insert", {}, Exception("duplicate"))),
        )
        session = SimpleNamespace(scalar=AsyncMock(return_value=group.company_id))
        with self.assertRaises(OperationalGroupConflictError):
            await CreateOperationalGroupUseCase(FakeUnitOfWork(repo, session)).execute(vars(group))

    async def test_update_changes_metadata_and_deactivates_without_changing_code(self):
        group = group_record()
        repo = SimpleNamespace(find_one=AsyncMock(return_value=group), update=AsyncMock(side_effect=lambda value: value))
        session = SimpleNamespace(scalar=AsyncMock(return_value=group))
        before, after = await UpdateOperationalGroupUseCase(FakeUnitOfWork(repo, session)).execute(
            group.company_id, group.operational_group, {"display_name": "Updated", "sort_order": 2, "is_active": False},
        )
        self.assertEqual(before, group)
        self.assertEqual(after, replace(group, display_name="Updated", sort_order=2, is_active=False))

    async def test_missing_group_raises_not_found_through_execution_wrapper(self):
        repo = SimpleNamespace(find_one=AsyncMock(return_value=None))
        session = SimpleNamespace(scalar=AsyncMock(return_value=None))
        with self.assertRaises(OperationalGroupNotFoundError):
            await UpdateOperationalGroupUseCase(FakeUnitOfWork(repo, session)).execute(uuid4(), "MISSING", {})

    async def test_deleted_groups_excluded_even_when_inactive_included_unless_requested(self):
        session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
        use_case = ListOperationalGroupsUseCase(FakeUnitOfWork(session=session))
        await use_case.execute(uuid4(), True)
        self.assertIn("deleted_at IS NULL", str(session.scalars.call_args.args[0]))
        await use_case.execute(uuid4(), True, True)
        self.assertNotIn("deleted_at IS NULL", str(session.scalars.call_args.args[0]))

    async def test_delete_is_soft_company_scoped_locked_and_records_actor(self):
        group = group_record()
        actor_id = uuid4()
        session = SimpleNamespace(scalar=AsyncMock(return_value=group))
        repo = SimpleNamespace(update=AsyncMock(side_effect=lambda value: value), delete=AsyncMock())
        before, after = await DeleteOperationalGroupUseCase(FakeUnitOfWork(repo, session)).execute(
            group.company_id, group.operational_group, actor_id,
        )
        self.assertEqual(before, group)
        self.assertFalse(after.is_active)
        self.assertIsNotNone(after.deleted_at)
        self.assertEqual(after.deleted_by, actor_id)
        self.assertEqual(after.operational_group, group.operational_group)
        repo.delete.assert_not_awaited()
        query = session.scalar.call_args.args[0]
        self.assertIn("FOR UPDATE", str(query))
        self.assertIn(group.company_id, query.compile().params.values())

    async def test_restore_keeps_group_inactive_and_does_not_change_code(self):
        group = replace(group_record(active=False), deleted_at=datetime.now(timezone.utc), deleted_by=uuid4())
        session = SimpleNamespace(scalar=AsyncMock(return_value=group))
        repo = SimpleNamespace(update=AsyncMock(side_effect=lambda value: value))
        before, after = await RestoreOperationalGroupUseCase(FakeUnitOfWork(repo, session)).execute(
            group.company_id, group.operational_group,
        )
        self.assertEqual(before, group)
        self.assertEqual(after, replace(group, deleted_at=None, deleted_by=None))

    async def test_deleted_group_cannot_be_edited_or_recreated(self):
        group = replace(group_record(active=False), deleted_at=datetime.now(timezone.utc), deleted_by=uuid4())
        repo = SimpleNamespace(find_one=AsyncMock(return_value=group), update=AsyncMock())
        session = SimpleNamespace(scalar=AsyncMock(return_value=group))
        with self.assertRaises(OperationalGroupConflictError):
            await UpdateOperationalGroupUseCase(FakeUnitOfWork(repo, session)).execute(
                group.company_id, group.operational_group, {"is_active": True},
            )
        session.scalar.return_value = group.company_id
        with self.assertRaises(OperationalGroupConflictError):
            await CreateOperationalGroupUseCase(FakeUnitOfWork(repo, session)).execute(vars(group))
        repo.update.assert_not_awaited()

    async def test_delete_restore_conflicts_and_missing_records(self):
        group = group_record()
        repo = SimpleNamespace(update=AsyncMock())
        session = SimpleNamespace(scalar=AsyncMock(return_value=group))
        uow = FakeUnitOfWork(repo, session)
        with self.assertRaises(OperationalGroupConflictError):
            await RestoreOperationalGroupUseCase(uow).execute(group.company_id, group.operational_group)
        session.scalar.return_value = replace(group, deleted_at=datetime.now(timezone.utc))
        with self.assertRaises(OperationalGroupConflictError):
            await DeleteOperationalGroupUseCase(uow).execute(group.company_id, group.operational_group, uuid4())
        session.scalar.return_value = None
        with self.assertRaises(OperationalGroupNotFoundError):
            await DeleteOperationalGroupUseCase(uow).execute(group.company_id, group.operational_group, uuid4())
        with self.assertRaises(OperationalGroupNotFoundError):
            await RestoreOperationalGroupUseCase(uow).execute(group.company_id, group.operational_group)
        repo.update.assert_not_awaited()


class OperationalGroupAssignmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_group_cannot_be_newly_assigned_but_can_be_retained(self):
        group = replace(group_record(active=False), deleted_at=datetime.now(timezone.utc), deleted_by=uuid4())
        session = SimpleNamespace(scalar=AsyncMock(return_value=group))
        uow = FakeUnitOfWork(session=session)
        with self.assertRaisesRegex(ValueError, "deleted"):
            await ensure_operational_group_allowed(uow, group.company_id, group.operational_group)
        await ensure_operational_group_allowed(
            uow, group.company_id, group.operational_group, (group.company_id, group.operational_group),
        )
        with self.assertRaisesRegex(ValueError, "deleted"):
            await ensure_operational_group_allowed(uow, group.company_id, group.operational_group, (uuid4(), group.operational_group))

    async def test_invalid_assignment_group_type_is_validation_error_not_database_error(self):
        for code in (123, [], "", "X" * 31):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, "1 to 30 characters"):
                await ensure_operational_group_allowed(FakeUnitOfWork(), uuid4(), code)

    async def test_none_remains_optional_without_database_lookup(self):
        await ensure_operational_group_allowed(FakeUnitOfWork(), uuid4(), None)

    async def test_active_custom_group_is_allowed_with_company_scoped_lock(self):
        group = group_record()
        session = SimpleNamespace(scalar=AsyncMock(return_value=group))
        await ensure_operational_group_allowed(FakeUnitOfWork(session=session), group.company_id, group.operational_group)
        query = session.scalar.call_args.args[0]
        sql = str(query.compile(dialect=postgresql.dialect()))
        self.assertIn("FOR SHARE", sql)
        self.assertIn(group.company_id, query.compile().params.values())
        self.assertIn(group.operational_group, query.compile().params.values())

    async def test_missing_or_other_company_group_is_rejected(self):
        session = SimpleNamespace(scalar=AsyncMock(return_value=None))
        with self.assertRaisesRegex(ValueError, "selected company"):
            await ensure_operational_group_allowed(FakeUnitOfWork(session=session), uuid4(), "NEW_GROUP")

    async def test_inactive_group_cannot_be_newly_assigned(self):
        group = group_record(active=False)
        session = SimpleNamespace(scalar=AsyncMock(return_value=group))
        with self.assertRaisesRegex(ValueError, "inactive"):
            await ensure_operational_group_allowed(FakeUnitOfWork(session=session), group.company_id, group.operational_group)

    async def test_unchanged_inactive_group_is_preserved(self):
        group = group_record(active=False)
        session = SimpleNamespace(scalar=AsyncMock(return_value=group))
        await ensure_operational_group_allowed(
            FakeUnitOfWork(session=session), group.company_id, group.operational_group,
            (group.company_id, group.operational_group),
        )

    async def test_company_or_group_change_cannot_reuse_inactive_exception(self):
        group = group_record(active=False)
        for existing in ((uuid4(), group.operational_group), (group.company_id, "OTHER")):
            with self.subTest(existing=existing):
                session = SimpleNamespace(scalar=AsyncMock(return_value=group))
                with self.assertRaisesRegex(ValueError, "inactive"):
                    await ensure_operational_group_allowed(
                        FakeUnitOfWork(session=session), group.company_id, group.operational_group, existing,
                    )

    async def test_assignment_create_and_csv_import_validate_inactive_groups(self):
        group = group_record(active=False)
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=group),
            execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
        )
        uow = FakeUnitOfWork(session=session)
        payload = {
            "employee_id": str(uuid4()), "company_id": str(group.company_id),
            "employment_type": "REGULAR", "employee_category": "RANK_AND_FILE",
            "hire_date": "2026-01-01", "effective_from": "2026-01-01",
            "operational_group": group.operational_group,
        }
        with patch(
            "app.filemaintenance.employees.application.related_use_case._ensure_single_active_assignment", AsyncMock(),
        ):
            with self.assertRaisesRegex(ValueError, "inactive"):
                await CreateEmploymentAssignmentUseCase(uow).execute(payload)
            with self.assertRaisesRegex(ValueError, "CSV row 2:.*inactive"):
                await CreateEmploymentAssignmentsBatchUseCase(uow).execute([{"row_number": 2, "assignment": payload}])

    async def test_assignment_update_supplies_original_company_and_group_for_retention(self):
        from datetime import date

        existing = EmploymentAssignmentEntity(
            employee_id=uuid4(), company_id=uuid4(), employment_type="REGULAR",
            employee_category="RANK_AND_FILE", hire_date=date(2026, 1, 1),
            effective_from=date(2026, 1, 1), operational_group="ARCHIVE", id=uuid4(),
        )
        repo = SimpleNamespace(find_one=AsyncMock(return_value=existing), update=AsyncMock(side_effect=lambda value: value))
        uow = FakeUnitOfWork(repo, SimpleNamespace(execute=AsyncMock()))
        module = "app.filemaintenance.employees.application.related_use_case"
        validator = AsyncMock()
        with (
            patch(f"{module}._get_assignment_geofence_ids", AsyncMock(return_value=[])),
            patch(f"{module}._get_assignment_location_ids", AsyncMock(return_value=[])),
            patch(f"{module}._ensure_single_active_assignment", AsyncMock()),
            patch(f"{module}._replace_assignment_locations", AsyncMock()),
            patch(f"{module}._validate_assignment", validator),
        ):
            await UpdateEmploymentAssignmentUseCase(uow).execute(
                existing.id, {"operational_group": "ARCHIVE", "location_ids": [], "status": "INACTIVE"},
            )
        self.assertEqual(validator.call_args.args[2], (existing.company_id, "ARCHIVE"))

    def test_assignment_normalizes_group_codes_and_blank_values(self):
        self.assertEqual(_normalize_assignment({"operational_group": " custom "})["operational_group"], "CUSTOM")
        self.assertIsNone(_normalize_assignment({"operational_group": " "})["operational_group"])

    def test_assignment_has_company_and_code_foreign_key_instead_of_fixed_list(self):
        foreign_key = next(
            constraint for constraint in EmploymentAssignmentModel.__table__.foreign_key_constraints
            if constraint.name == "fk_assignment_operational_group"
        )
        self.assertEqual(
            [element.target_fullname for element in foreign_key.elements],
            ["core.operational_groups.company_id", "core.operational_groups.operational_group"],
        )
        self.assertNotIn(
            "ck_employment_assignments_operational_group",
            {constraint.name for constraint in EmploymentAssignmentModel.__table__.constraints},
        )


class OperationalGroupSchemaTests(unittest.TestCase):
    def test_create_normalizes_and_trims(self):
        payload = OperationalGroupCreateSchema(
            company_id=uuid4(), operational_group=" new_group ", display_name=" New group ", sort_order=0, is_active=True,
        )
        self.assertEqual(payload.operational_group, "NEW_GROUP")
        self.assertEqual(payload.display_name, "New group")

    def test_rejects_invalid_codes_names_order_and_code_changes(self):
        valid = dict(company_id=uuid4(), operational_group="NEW", display_name="New", sort_order=0, is_active=True)
        for changes in (
            {"operational_group": ""}, {"operational_group": "HAS SPACE"},
            {"operational_group": "X" * 31}, {"operational_group": "CAF\u00c9"},
            {"operational_group": "\u00df" * 30},
            {"display_name": " "}, {"sort_order": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                OperationalGroupCreateSchema(**(valid | changes))
        with self.assertRaises(ValueError):
            OperationalGroupUpdateSchema(display_name="New", sort_order=0, is_active=True, operational_group="CHANGED")
        for field in ("deleted_at", "deleted_by"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                OperationalGroupUpdateSchema(
                    display_name="New", sort_order=0, is_active=True, **{field: None},
                )


class OperationalGroupApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        register_exception_handlers(self.app)
        self.app.include_router(router)
        self.group = group_record()
        self.claims = {"sub": str(uuid4()), "email": "test@example.invalid"}
        self.permissions = ["company.setup"]
        self.authorization = SimpleNamespace(execute=AsyncMock(
            side_effect=lambda _user_id: SimpleNamespace(permission_codes=self.permissions)
        ))
        self.list_case = SimpleNamespace(execute=AsyncMock(return_value=[self.group]))
        self.create_case = SimpleNamespace(execute=AsyncMock(return_value=self.group))
        self.update_case = SimpleNamespace(execute=AsyncMock(return_value=(self.group, self.group)))
        self.delete_case = SimpleNamespace(execute=AsyncMock(return_value=(
            self.group, replace(self.group, is_active=False, deleted_at=datetime.now(timezone.utc), deleted_by=uuid4()),
        )))
        self.restore_case = SimpleNamespace(execute=AsyncMock(return_value=(self.group, self.group)))
        self.app.dependency_overrides.update({
            get_current_user_claims: lambda: self.claims,
            get_current_authorization_use_case: lambda: self.authorization,
            get_list_use_case: lambda: self.list_case,
            get_create_use_case: lambda: self.create_case,
            get_update_use_case: lambda: self.update_case,
            get_delete_use_case: lambda: self.delete_case,
            get_restore_use_case: lambda: self.restore_case,
            get_audit_es_client: lambda: None,
        })
        self.client = TestClient(self.app)
        self.payload = {
            "company_id": str(self.group.company_id), "operational_group": self.group.operational_group,
            "display_name": self.group.display_name, "sort_order": 10, "is_active": True,
        }

    def test_lookup_returns_envelope_and_requires_company(self):
        response = self.client.get("/operational-groups/list", params={"company_id": str(self.group.company_id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        self.assertEqual(response.json()["data"][0]["operational_group"], "NEW_GROUP")
        self.list_case.execute.assert_awaited_once_with(self.group.company_id, False, False)
        self.assertEqual(self.client.get("/operational-groups/list").status_code, 422)

    def test_anonymous_lookup_rejected(self):
        del self.app.dependency_overrides[get_current_user_claims]
        self.assertEqual(
            self.client.get("/operational-groups/list", params={"company_id": str(self.group.company_id)}).status_code, 403,
        )
        self.assertEqual(self.client.delete(
            "/operational-groups/NEW_GROUP", params={"company_id": str(self.group.company_id)},
        ).status_code, 403)
        self.assertEqual(self.client.post(
            "/operational-groups/NEW_GROUP/restore", params={"company_id": str(self.group.company_id)},
        ).status_code, 403)

    def test_authenticated_employee_can_read_lookup_but_not_manage(self):
        self.permissions = []
        self.assertEqual(self.client.get(
            "/operational-groups/list", params={"company_id": str(self.group.company_id)},
        ).status_code, 200)
        self.assertEqual(self.client.post("/operational-groups/create", json=self.payload).status_code, 403)
        self.assertEqual(self.client.put(
            "/operational-groups/NEW_GROUP", params={"company_id": str(self.group.company_id)},
            json={"display_name": "New", "sort_order": 0, "is_active": False},
        ).status_code, 403)

    def test_create_and_update_require_setup_permission_and_use_normalized_codes(self):
        self.assertEqual(self.client.post("/operational-groups/create", json=self.payload).status_code, 201)
        update = {"display_name": "Updated", "sort_order": 1, "is_active": False}
        response = self.client.put(
            "/operational-groups/new_group", params={"company_id": str(self.group.company_id)}, json=update,
        )
        self.assertEqual(response.status_code, 200)
        self.update_case.execute.assert_awaited_once_with(self.group.company_id, "NEW_GROUP", update)

    def test_duplicate_and_missing_group_errors_are_explicit(self):
        self.create_case.execute.side_effect = OperationalGroupConflictError("Duplicate group.")
        self.assertEqual(self.client.post("/operational-groups/create", json=self.payload).status_code, 409)
        self.update_case.execute.side_effect = OperationalGroupNotFoundError("Group not found.")
        response = self.client.put(
            "/operational-groups/MISSING", params={"company_id": str(self.group.company_id)},
            json={"display_name": "Missing", "sort_order": 0, "is_active": True},
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_restore_require_permission_and_preserve_audit_identity(self):
        params = {"company_id": str(self.group.company_id)}
        with patch("app.filemaintenance.operational_groups.infrastructure.router.log_entity_action", new_callable=AsyncMock) as audit:
            response = self.client.delete("/operational-groups/new_group", params=params)
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(response.json()["data"]["deleted_at"])
            self.delete_case.execute.assert_awaited_once_with(
                self.group.company_id, "NEW_GROUP", UUID(self.claims["sub"]),
            )
            self.assertEqual(audit.call_args.kwargs["action"], "DELETE")
            response = self.client.post("/operational-groups/new_group/restore", params=params)
            self.assertEqual(response.status_code, 200)
            self.restore_case.execute.assert_awaited_once_with(self.group.company_id, "NEW_GROUP")
            self.assertEqual(audit.call_args.kwargs["action"], "RESTORE")
        self.permissions = []
        self.assertEqual(self.client.delete("/operational-groups/NEW_GROUP", params=params).status_code, 403)
        self.assertEqual(self.client.post("/operational-groups/NEW_GROUP/restore", params=params).status_code, 403)

    def test_deleted_filter_is_forwarded_to_use_case(self):
        response = self.client.get("/operational-groups/list", params={
            "company_id": str(self.group.company_id), "include_deleted": True, "include_inactive": True,
        })
        self.assertEqual(response.status_code, 200)
        self.list_case.execute.assert_awaited_once_with(self.group.company_id, True, True)

    def test_delete_restore_missing_and_conflict_responses(self):
        params = {"company_id": str(self.group.company_id)}
        for error, status in (
            (OperationalGroupNotFoundError("Missing."), 404),
            (OperationalGroupConflictError("Conflict."), 409),
        ):
            self.delete_case.execute.side_effect = error
            self.restore_case.execute.side_effect = error
            self.assertEqual(self.client.delete("/operational-groups/NEW_GROUP", params=params).status_code, status)
            self.assertEqual(self.client.post("/operational-groups/NEW_GROUP/restore", params=params).status_code, status)
        self.update_case.execute.side_effect = OperationalGroupConflictError("Restore before editing.")
        self.assertEqual(self.client.put(
            "/operational-groups/NEW_GROUP", params=params,
            json={"display_name": "New", "sort_order": 0, "is_active": True},
        ).status_code, 409)


class OperationalGroupMigrationTests(unittest.TestCase):
    def migration_sql(self, direction):
        path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "c8f9012d3e45_operational_groups.py"
        spec = importlib.util.spec_from_file_location("operational_groups_revision", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = io.StringIO()
        context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
        with patch.object(module, "op", Operations(context)):
            getattr(module, direction)()
        return output.getvalue()

    def test_upgrade_seeds_companies_and_existing_assignments_before_fk_replacement(self):
        sql = self.migration_sql("upgrade")
        self.assertIn("CREATE TABLE core.operational_groups", sql)
        self.assertIn("FROM core.companies c", sql)
        self.assertIn("SELECT DISTINCT company_id, operational_group, operational_group", sql)
        self.assertLess(sql.index("FROM hr.employment_assignments"), sql.index("DROP CONSTRAINT"))
        self.assertIn(
            "FOREIGN KEY(company_id, operational_group) REFERENCES core.operational_groups (company_id, operational_group)", sql,
        )
        for code in ("SLI", "SLR", "ASS", "MTT", "COLLECTION", "FLEET", "WAREHOUSE", "OFFICE", "OTHER"):
            self.assertIn(f"'{code}'", sql)
        self.assertNotIn("UPDATE hr.employment_assignments", sql)

    def test_soft_delete_migration_adds_nullable_metadata_without_replacing_records(self):
        path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "d9a0123e4f56_soft_delete_operational_groups.py"
        spec = importlib.util.spec_from_file_location("operational_groups_soft_delete_revision", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.down_revision, "c8f9012d3e45")
        for direction in ("upgrade", "downgrade"):
            output = io.StringIO()
            context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
            with patch.object(module, "op", Operations(context)):
                getattr(module, direction)()
            sql = output.getvalue()
            if direction == "upgrade":
                self.assertIn("ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE", sql)
                self.assertIn("ADD COLUMN deleted_by UUID", sql)
                self.assertIn("REFERENCES identity.users (id)", sql)
                self.assertNotIn("NOT NULL", sql)
                self.assertNotIn("DELETE FROM", sql)
                self.assertNotIn("employment_assignments", sql)
            else:
                self.assertIn("Restore deleted operational groups", sql)
        standalone = (Path(__file__).resolve().parents[1] / "sql" / "20261030_soft_delete_operational_groups.sql").read_text()
        self.assertIn("BEGIN;", standalone)
        self.assertIn("COMMIT;", standalone)
        self.assertNotIn("DROP", standalone)

    def test_both_upgrade_paths_allow_the_legacy_constraint_to_be_absent(self):
        standalone = (
            Path(__file__).resolve().parents[1] / "sql" / "20261030_create_operational_groups.sql"
        ).read_text()
        for sql in (self.migration_sql("upgrade"), standalone):
            self.assertIn(
                "DROP CONSTRAINT IF EXISTS ck_employment_assignments_operational_group", sql,
            )

    def test_downgrade_refuses_custom_groups_before_dropping_lookup(self):
        sql = self.migration_sql("downgrade")
        self.assertLess(sql.index("RAISE EXCEPTION"), sql.index("DROP TABLE"))
        self.assertIn("ADD CONSTRAINT ck_employment_assignments_operational_group CHECK", sql)
