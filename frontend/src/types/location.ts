export type LocationType = string

export type LocationStatus = 'ACTIVE' | 'INACTIVE' | 'DELETED'

export interface Location {
  id: string
  company_id: string
  location_code: string
  location_name: string
  location_type: LocationType
  address_line1: string | null
  region: string | null
  psgc_region_code: string | null
  psgc_province_code: string | null
  psgc_city_code: string | null
  ncr_district: string | null
  psgc_barangay_code: string | null
  barangay: string | null
  city: string | null
  province: string | null
  postal_code: string | null
  latitude: number | string | null
  longitude: number | string | null
  geo_point: string | null
  timezone: string
  status: LocationStatus
  is_active: boolean
  created_at: string
  created_by: string | null
  updated_at: string
  updated_by: string | null
  row_version: number
  deleted_at?: string | null
  deleted_by?: string | null
}
