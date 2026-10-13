export interface EnrollmentResult {
  status: 'pending' | 'enrolled' | 'failed'
  enrolled_at: string
  sample_count: number
  photo_reference?: string | null
}
