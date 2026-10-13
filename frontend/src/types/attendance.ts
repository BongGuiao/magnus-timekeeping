export interface ClockResult {
  employee_name: string
  employee_code: string
  action: 'clock_in' | 'clock_out'
  timestamp: string
  approval_required: boolean
  late_minutes: number
  undertime_minutes: number
  calculated_ot_minutes: number
  overtime_hours: number
  regular_overtime_minutes: number
  regular_overtime_hours: number
  night_differential_overtime_minutes: number
  night_differential_overtime_hours: number
  night_differential_hours: number
}

export interface LastAttendance {
  work_date: string
  clock_in_at: string | null
  clock_out_at: string | null
  first_break_out_at: string | null
  first_break_in_at: string | null
  second_break_out_at: string | null
  second_break_in_at: string | null
  meal_break_out_at: string | null
  meal_break_in_at: string | null
  ot_break_out_at: string | null
  ot_break_in_at: string | null
  expected_clock_in_at: string | null
  expected_clock_out_at: string | null
  break_rules?: {
    break_slot: 'FIRST_BREAK' | 'MEAL_BREAK' | 'SECOND_BREAK'
    segment_type: 'PAID_BREAK' | 'UNPAID_BREAK'
    break_minutes: number
    auto_deduct: boolean
    start_at: string
    end_at: string
  }[]
}

export type BreakType =
  | 'first_break_out_at'
  | 'first_break_in_at'
  | 'meal_break_out_at'
  | 'meal_break_in_at'
  | 'second_break_out_at'
  | 'second_break_in_at'
  | 'ot_break_out_at'
  | 'ot_break_in_at'

export interface BreakResult {
  employee_name: string
  employee_code: string
  action_recorded: string
  timestamp: string
}
