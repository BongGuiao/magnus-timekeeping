export type OrgUnitStatus = 'DRAFT' | 'ACTIVE' | 'INACTIVE' | 'DELETED'

export interface OrgUnit {
  id: string
  company_id: string
  parent_org_unit_id: string | null
  org_unit_code: string
  org_unit_name: string
  org_unit_type: string
  manager_employee_id: string | null
  cost_center_code: string | null
  effective_from: string
  effective_to: string | null
  status: OrgUnitStatus
  created_at: string
  created_by: string | null
  updated_at: string
  updated_by: string | null
  row_version: number
  is_active: boolean
  deleted_at?: string | null
  deleted_by?: string | null
}