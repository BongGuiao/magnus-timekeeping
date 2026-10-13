export const OPERATIONAL_GROUPS = ['SLI', 'SLR', 'ASS', 'MTT', 'COLLECTION', 'FLEET', 'WAREHOUSE', 'OFFICE', 'OTHER'] as const

export type OperationalGroup = (typeof OPERATIONAL_GROUPS)[number]

interface AuditFields {
  id: string
  created_at: string | null
  created_by: string | null
  updated_at: string | null
  updated_by: string | null
  row_version: number | null
  is_active: boolean
}

export interface EmploymentAssignment extends AuditFields {
  employee_id: string
  company_id: string
  org_unit_id: string | null
  position_id: string | null
  supervisor_employee_id: string | null
  employment_type: string
  employee_category: string
  operational_group: OperationalGroup | null
  payroll_group_id: string | null
  primary_location_id: string | null
  hire_date: string
  effective_from: string
  effective_to: string | null
  separation_date: string | null
  status: string
}

export interface EmployeeSkill extends AuditFields {
  employee_id: string
  skill_code: string
  proficiency_level: string | null
  certification_no: string | null
  issued_date: string | null
  expiry_date: string | null
  verified_by: string | null
  status: string
}

type ReadOnlyFields = 'id' | 'created_at' | 'created_by' | 'updated_at' | 'updated_by' | 'row_version'

export type EmploymentAssignmentWritePayload = Omit<EmploymentAssignment, ReadOnlyFields>
export type EmployeeSkillWritePayload = Omit<EmployeeSkill, ReadOnlyFields>
