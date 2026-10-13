import type { AttendanceLogEntry, OvertimeApplicationType } from '../types/dashboard'

export interface OvertimePeriod {
  requested_start_at: string
  requested_end_at: string
}

// datetime-local has no timezone; all overtime form values represent Philippine time.
export function philippineDateTime(value: string | null | undefined, roundUp = false): string {
  if (!value) return ''
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return ''
  const seconds = roundUp ? Math.ceil(timestamp / 1000) : Math.floor(timestamp / 1000)
  return new Date(seconds * 1000 + 8 * 60 * 60 * 1000).toISOString().slice(0, 19)
}

export function overtimeTimestamp(value: string): string {
  return `${value}+08:00`
}

export function overtimePeriodMinutes(period: OvertimePeriod): number {
  const start = Date.parse(overtimeTimestamp(period.requested_start_at))
  const end = Date.parse(overtimeTimestamp(period.requested_end_at))
  return Number.isFinite(start) && Number.isFinite(end) && end > start
    ? Math.floor((end - start) / 60_000) : 0
}

export function defaultOvertimePeriod(entry: AttendanceLogEntry, type: OvertimeApplicationType): OvertimePeriod {
  let start = entry.timeIn
  let end = entry.timeOut
  if (type !== 'NIGHT_DIFFERENTIAL' && start && end) {
    if (entry.expectedTimeOut && Date.parse(end) > Date.parse(entry.expectedTimeOut)) {
      start = Date.parse(entry.expectedTimeOut) > Date.parse(start) ? entry.expectedTimeOut : start
    } else if (entry.expectedTimeIn && Date.parse(start) < Date.parse(entry.expectedTimeIn)) {
      end = Date.parse(entry.expectedTimeIn) < Date.parse(end) ? entry.expectedTimeIn : end
    }
  }
  return {
    requested_start_at: philippineDateTime(start, true),
    requested_end_at: philippineDateTime(end),
  }
}

export function overtimePeriodError(entry: AttendanceLogEntry, period: OvertimePeriod, minutes: number, maximum: number): string | null {
  const start = Date.parse(overtimeTimestamp(period.requested_start_at))
  const end = Date.parse(overtimeTimestamp(period.requested_end_at))
  const actualStart = Date.parse(entry.timeIn ?? '')
  const actualEnd = Date.parse(entry.timeOut ?? '')
  if (![start, end, actualStart, actualEnd].every(Number.isFinite) || end <= start) {
    return 'Enter a requested start and end, with the end after the start.'
  }
  if (start < actualStart || end > actualEnd) {
    return 'The requested period must be within the effective attendance clock-in and clock-out.'
  }
  if (!Number.isInteger(minutes) || minutes <= 0 || minutes > Math.min(maximum, overtimePeriodMinutes(period))) {
    return 'Requested minutes must be positive and cannot exceed the period duration or calculated maximum.'
  }
  return null
}
