from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass
class CompanyEntity:
    company_code: str
    legal_name: str
    trade_name: str | None = None
    tax_id: str | None = None
    registration_no: str | None = None
    timezone: str = "Asia/Manila"
    address_line1: str | None = None
    address_line2: str | None = None
    region: str | None = None
    psgc_region_code: str | None = None
    psgc_province_code: str | None = None
    psgc_city_code: str | None = None
    psgc_barangay_code: str | None = None
    barangay: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    default_currency: str = "PHP"
    status: Literal["DRAFT", "ACTIVE", "INACTIVE"] = "ACTIVE"
    created_by: UUID | None = None
    updated_by: UUID | None = None
    is_active: bool = True
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None