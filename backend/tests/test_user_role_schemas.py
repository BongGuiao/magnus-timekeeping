import unittest
from datetime import date
from uuid import uuid4

from pydantic import ValidationError

from app.auth.infrastructure.db_model import UserRoleModel as AuthUserRoleModel
from app.core.database import Base
from app.filemaintenance.roles.application.use_case import _validate_effective_dates
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel
from app.filemaintenance.roles.infrastructure.router import (
    CreateUserRoleSchema,
    UpdateUserRoleSchema,
    router as user_roles_router,
)
from app.filemaintenance.roles.infrastructure.role_catalog_router import (
    CreateRoleSchema,
    UpdateRoleSchema,
    router as roles_router,
)


class UserRoleSchemaTests(unittest.TestCase):
    def test_create_schema_accepts_valid_assignment(self) -> None:
        assignment = CreateUserRoleSchema(
            user_id=uuid4(),
            role_id=uuid4(),
            effective_from=date(2026, 10, 1),
            effective_to=date(2026, 10, 31),
        )

        self.assertEqual(assignment.effective_from, date(2026, 10, 1))

    def test_create_schema_rejects_end_before_start(self) -> None:
        with self.assertRaises(ValidationError):
            CreateUserRoleSchema(
                user_id=uuid4(),
                role_id=uuid4(),
                effective_from=date(2026, 10, 2),
                effective_to=date(2026, 10, 1),
            )

    def test_update_schema_allows_clearing_optional_scope_and_end_date(self) -> None:
        assignment = UpdateUserRoleSchema(
            id=uuid4(),
            company_id=None,
            org_unit_id=None,
            effective_to=None,
        )

        self.assertIsNone(assignment.effective_to)

    def test_assignment_actor_is_not_client_writable(self) -> None:
        with self.assertRaises(ValidationError):
            CreateUserRoleSchema(
                user_id=uuid4(),
                role_id=uuid4(),
                effective_from=date(2026, 10, 1),
                assigned_by=uuid4(),
            )

    def test_merged_date_validation_rejects_end_before_start(self) -> None:
        with self.assertRaisesRegex(ValueError, "effective_to"):
            _validate_effective_dates(date(2026, 10, 2), date(2026, 10, 1))

    def test_auth_and_filemaintenance_use_the_same_user_role_table(self) -> None:
        self.assertIs(AuthUserRoleModel, UserRoleModel)
        self.assertIs(Base.metadata.tables["identity.user_roles"], UserRoleModel.__table__)
        targets = {
            element.target_fullname
            for constraint in UserRoleModel.__table__.foreign_key_constraints
            for element in constraint.elements
        }
        self.assertEqual(
            targets,
            {
                "identity.users.id",
                "identity.roles.id",
                "core.companies.id",
                "core.org_units.id",
            },
        )

    def test_user_role_api_routes_are_registered(self) -> None:
        paths = {route.path for route in user_roles_router.routes}

        self.assertEqual(
            paths,
            {
                "/user-roles/create",
                "/user-roles/update",
                "/user-roles/list",
                "/user-roles/available-roles",
                "/user-roles/{user_role_id}",
            },
        )

    def test_role_catalog_api_routes_are_registered(self) -> None:
        paths = {route.path for route in roles_router.routes}

        self.assertEqual(
            paths,
            {"/roles/create", "/roles/update", "/roles/list", "/roles/{role_id}"},
        )

    def test_role_schema_normalizes_role_code(self) -> None:
        role = CreateRoleSchema(
            role_code="  hr_admin ",
            role_name="HR Administrator",
            scope_type="GLOBAL",
        )

        self.assertEqual(role.role_code, "HR_ADMIN")

    def test_role_update_allows_clearing_description(self) -> None:
        role = UpdateRoleSchema(id=uuid4(), description=None)

        self.assertIsNone(role.description)

    def test_role_update_rejects_null_required_values(self) -> None:
        with self.assertRaises(ValidationError):
            UpdateRoleSchema(id=uuid4(), role_name=None)
