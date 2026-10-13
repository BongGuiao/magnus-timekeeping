export interface Geofence {
  id: string
  company_id: string
  location_id: string | null
  geofence_code: string
  geofence_name: string
  geofence_type: string
  center_point: string | null
  radius_meters: number | string | null
  boundary_polygon: string | null
  maximum_gps_accuracy_meters: number
  effective_from: string
  effective_to: string | null
  source_type: string
  source_reference_id: string | null
  status: string
  created_at: string | null
  created_by: string | null
  updated_at: string | null
  updated_by: string | null
  row_version: number
  is_active: boolean
}
