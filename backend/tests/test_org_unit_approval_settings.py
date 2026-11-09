import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from uuid import uuid4

from app.filemaintenance.org_unit.application.use_case import _normalize_payload
from app.filemaintenance.org_unit.domain.approval_settings import validate_org_unit_approval_settings
from app.filemaintenance.org_unit.domain.entities.org_unit import OrgUnitEntity


class OrgUnitApprovalSettingsTests(unittest.TestCase):
    def setUp(self):
        self.company_id = uuid4()
        self.root = self.unit("ROOT")
        self.child = self.unit("CHILD", self.root.id)
        self.leaf = self.unit("LEAF", self.child.id)
        self.sibling = self.unit("SIBLING")
        self.units = [self.root, self.child, self.leaf, self.sibling]

    def unit(self, code, parent_id=None):
        return OrgUnitEntity(
            id=uuid4(), company_id=self.company_id, org_unit_code=code,
            org_unit_name=code, org_unit_type="DEPARTMENT", effective_from=date(2026, 1, 1),
            parent_org_unit_id=parent_id,
        )

    def test_defaults_are_enabled_and_exclusion_lists_are_independent(self):
        self.assertTrue(self.root.manager_is_approver)
        self.assertEqual(self.root.excluded_approval_org_unit_ids, [])
        self.root.excluded_approval_org_unit_ids.append(self.child.id)
        self.assertEqual(self.child.excluded_approval_org_unit_ids, [])

    def test_direct_and_nested_descendant_exclusions_are_valid(self):
        self.root.excluded_approval_org_unit_ids = [self.child.id, self.leaf.id]
        validate_org_unit_approval_settings(self.units)

    def test_self_parent_sibling_unknown_and_other_company_are_rejected(self):
        other_company = replace(self.unit("OTHER"), company_id=uuid4())
        for invalid_id in (self.child.id, self.root.id, self.sibling.id, uuid4(), other_company.id):
            with self.subTest(invalid_id=invalid_id):
                self.child.excluded_approval_org_unit_ids = [invalid_id]
                with self.assertRaisesRegex(ValueError, "descendant"):
                    validate_org_unit_approval_settings([*self.units, other_company])

    def test_reparenting_and_deletion_cannot_leave_invalid_exclusions(self):
        self.root.excluded_approval_org_unit_ids = [self.child.id]
        for changed in (
            replace(self.child, parent_org_unit_id=self.sibling.id),
            replace(self.child, deleted_at=datetime.now(timezone.utc)),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    validate_org_unit_approval_settings([
                        self.root, changed, self.sibling,
                    ])

    def test_cycles_and_cross_company_parents_are_rejected(self):
        for changed in (
            replace(self.root, parent_org_unit_id=self.leaf.id),
            replace(self.child, company_id=uuid4()),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    validate_org_unit_approval_settings([
                        changed if unit.id == changed.id else unit for unit in self.units
                    ])

    def test_disabled_approvers_still_require_valid_exclusions(self):
        self.root.manager_is_approver = False
        self.root.excluded_approval_org_unit_ids = [self.sibling.id]
        with self.assertRaisesRegex(ValueError, "descendant"):
            validate_org_unit_approval_settings(self.units)

    def test_payload_normalization_preserves_boolean_and_uuid_types(self):
        result = _normalize_payload({
            "manager_is_approver": False,
            "excluded_approval_org_unit_ids": [str(self.child.id), self.leaf.id],
        })
        self.assertIs(result["manager_is_approver"], False)
        self.assertEqual(result["excluded_approval_org_unit_ids"], [self.child.id, self.leaf.id])

    def test_invalid_setting_values_are_rejected(self):
        for payload in (
            {"manager_is_approver": "false"},
            {"manager_is_approver": None},
            {"excluded_approval_org_unit_ids": None},
            {"excluded_approval_org_unit_ids": str(self.child.id)},
            {"excluded_approval_org_unit_ids": ["invalid"]},
            {"excluded_approval_org_unit_ids": [self.child.id, self.child.id]},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    _normalize_payload(payload)
