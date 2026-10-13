export type CompanyStatus = 'DRAFT' | 'ACTIVE' | 'INACTIVE'

export interface Company {
  id: string
  company_code: string
  legal_name: string
  trade_name: string | null
  tax_id: string | null
  registration_no: string | null
  timezone: string
  address_line1: string | null
  address_line2: string | null
  region: string | null
  psgc_region_code: string | null
  psgc_province_code: string | null
  psgc_city_code: string | null
  psgc_barangay_code: string | null
  barangay: string | null
  city: string | null
  province: string | null
  postal_code: string | null
  default_currency: string
  status: CompanyStatus
  created_at: string
  created_by: string | null
  updated_at: string
  updated_by: string | null
  row_version: number
  is_active: boolean
}