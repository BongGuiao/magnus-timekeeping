export interface EnrollmentResult {
  status: 'pending' | 'enrolled' | 'failed'
  enrolled_at: string
  sample_count: number
  photo_reference?: string | null
}

export interface FaceSampleSummary {
  id: string
  status: EnrollmentResult['status']
  enrolled_at: string | null
  created_at: string
  photo_reference: string | null
  is_profile_photo: boolean
}

export interface FaceEnrollmentReview {
  employee_id: string
  employee_no: string
  enrolled_count: number
  samples: FaceSampleSummary[]
}

export interface ResetFaceEnrollmentPayload {
  employee_no: string
  sample_ids: string[]
  reason: string
}

export interface ResetFaceEnrollmentResult {
  removed_count: number
  photo_reference: string | null
  cleanup_warning: string | null
}
