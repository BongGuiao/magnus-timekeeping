from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID


@dataclass
class OrgUnitEntity:
    company_id: UUID
    org_unit_code: str
    org_unit_name: str
    org_unit_type: str
    effective_from: date
    parent_org_unit_id: UUID | None = None
    manager_employee_id: UUID | None = None
    cost_center_code: str | None = None
    effective_to: date | None = None
    status: Literal["DRAFT", "ACTIVE", "INACTIVE", "DELETED"] = "ACTIVE"
    created_by: UUID | None = None
    updated_by: UUID | None = None
    is_active: bool = True
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None
