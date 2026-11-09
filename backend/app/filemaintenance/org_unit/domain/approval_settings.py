from uuid import UUID

from app.filemaintenance.org_unit.domain.entities.org_unit import OrgUnitEntity


def validate_org_unit_approval_settings(units: list[OrgUnitEntity]) -> None:
    by_id = {unit.id: unit for unit in units if unit.deleted_at is None}
    ancestors: dict[UUID, set[UUID]] = {}
    for unit in by_id.values():
        if unit.id is None:
            raise ValueError("Organization unit id is required to validate the hierarchy.")
        path = {unit.id}
        parent_id = unit.parent_org_unit_id
        while parent_id is not None:
            if parent_id in path:
                raise ValueError("The organization hierarchy cannot contain a cycle.")
            parent = by_id.get(parent_id)
            if parent is None or parent.company_id != unit.company_id:
                raise ValueError("Parent org units must exist in the same company and must not be deleted.")
            path.add(parent_id)
            parent_id = parent.parent_org_unit_id
        ancestors[unit.id] = path - {unit.id}

    for unit in by_id.values():
        for excluded_id in unit.excluded_approval_org_unit_ids:
            if unit.id not in ancestors.get(excluded_id, set()):
                raise ValueError(
                    f"Approval exclusions for {unit.org_unit_code} must only contain descendant org units. "
                    "Remove invalid exclusions before moving or deleting an org unit."
                )
