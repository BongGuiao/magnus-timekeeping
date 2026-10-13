export interface Employee {
  id: string
  employee_no: string
  first_name: string
  last_name: string
  middle_name: string | null
  suffix: string | null
  preferred_name: string | null
  birth_date: string | null
  gender_code: 'MALE' | 'FEMALE' | 'OTHER' | null
  personal_email: string | null
  mobile_no: string | null
  photo_reference: string | null
  record_status: 'ACTIVE' | 'ARCHIVED'
  is_active: boolean
  created_at: string
  created_by: string | null
  updated_at: string
  updated_by: string | null
  row_version: number
}
