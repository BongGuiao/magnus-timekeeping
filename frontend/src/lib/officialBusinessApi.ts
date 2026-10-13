import { apiClient } from './apiClient'
import { getAttendanceErrorMessage } from './attendanceApi'
import type { ApiSuccessEnvelope } from '../types/auth'

const BASE_PATH = '/attendance/official-business'

export type OfficialBusinessStatus = 'DRAFT' | 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELLED'

export interface OfficialBusinessRequest {
  id: string
  request_no: string
  employee_id: string
  employee_code: string
  employee_name: string
  start_at: string
  end_at: string
  destination: string
  purpose: string
  client_name: string | null
  geofence_id: string | null
  geofence_name: string | null
  jo_reference: string | null
  vehicle_id: string | null
  vehicle_label: string | null
  requested_minutes: number
  approved_minutes: number | null
  status: OfficialBusinessStatus
  payroll_posted: boolean
  row_version: number
  created_at: string
  updated_at: string
}

export interface OfficialBusinessOption {
  id: string
  label: string
}

export interface OfficialBusinessOptions {
  geofences: OfficialBusinessOption[]
  vehicles: OfficialBusinessOption[]
}

export interface OfficialBusinessInput {
  start_at: string
  end_at: string
  destination: string
  purpose: string
  client_name: string | null
  geofence_id: string | null
  jo_reference: string | null
  vehicle_id: string | null
  requested_minutes: number
}

async function request<T>(action: () => Promise<{ data: ApiSuccessEnvelope<T> }>, fallback: string): Promise<T> {
  try {
    return (await action()).data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, fallback))
  }
}

export async function fetchMyOfficialBusinessRequests(): Promise<OfficialBusinessRequest[]> {
  const records = await request(
    () => apiClient.get<ApiSuccessEnvelope<OfficialBusinessRequest[]>>(BASE_PATH),
    'Could not load your official business requests.',
  )
  if (!Array.isArray(records)) throw new Error('The official business response was not a list.')
  return records
}

export function fetchOfficialBusinessOptions(): Promise<OfficialBusinessOptions> {
  return request(
    () => apiClient.get<ApiSuccessEnvelope<OfficialBusinessOptions>>(`${BASE_PATH}/options`),
    'Could not load official business options.',
  )
}

export function createOfficialBusinessRequest(
  payload: OfficialBusinessInput,
  submit: boolean,
): Promise<OfficialBusinessRequest> {
  return request(
    () => apiClient.post<ApiSuccessEnvelope<OfficialBusinessRequest>>(BASE_PATH, { ...payload, submit }),
    'Could not save the official business request.',
  )
}

export function updateOfficialBusinessRequest(
  requestId: string,
  payload: OfficialBusinessInput,
  rowVersion: number,
): Promise<OfficialBusinessRequest> {
  return request(
    () => apiClient.put<ApiSuccessEnvelope<OfficialBusinessRequest>>(`${BASE_PATH}/${requestId}`, {
      ...payload,
      row_version: rowVersion,
    }),
    'Could not update the official business request.',
  )
}

export function submitOfficialBusinessRequest(requestId: string, rowVersion: number): Promise<OfficialBusinessRequest> {
  return request(
    () => apiClient.post<ApiSuccessEnvelope<OfficialBusinessRequest>>(`${BASE_PATH}/${requestId}/submit`, {
      row_version: rowVersion,
    }),
    'Could not submit the official business request.',
  )
}

export function cancelOfficialBusinessRequest(requestId: string, rowVersion: number): Promise<OfficialBusinessRequest> {
  return request(
    () => apiClient.post<ApiSuccessEnvelope<OfficialBusinessRequest>>(`${BASE_PATH}/${requestId}/cancel`, {
      row_version: rowVersion,
    }),
    'Could not cancel the official business request.',
  )
}

export function fetchPendingOfficialBusinessRequests(): Promise<OfficialBusinessRequest[]> {
  return request(
    () => apiClient.get<ApiSuccessEnvelope<OfficialBusinessRequest[]>>(`${BASE_PATH}/pending`),
    'Could not load pending official business requests.',
  )
}

export function decideOfficialBusinessRequest(
  requestId: string,
  decision: 'APPROVED' | 'REJECTED',
  approvedMinutes: number | null,
  rowVersion: number,
): Promise<OfficialBusinessRequest> {
  return request(
    () => apiClient.post<ApiSuccessEnvelope<OfficialBusinessRequest>>(`${BASE_PATH}/${requestId}/decision`, {
      decision,
      approved_minutes: decision === 'APPROVED' ? approvedMinutes : null,
      row_version: rowVersion,
    }),
    'Could not save the official business decision.',
  )
}

const MANILA_OFFSET = '+08:00'

/** Interprets a datetime-local value as Philippine time and returns an ISO string with offset. */
export function manilaInputToIso(value: string): string {
  return `${value.length === 16 ? `${value}:00` : value}${MANILA_OFFSET}`
}

/** Converts an ISO timestamp into a datetime-local value in Philippine time. */
export function isoToManilaInput(value: string): string {
  const shifted = new Date(new Date(value).getTime() + 8 * 60 * 60 * 1000)
  return shifted.toISOString().slice(0, 16)
}

export function formatManilaDateTime(value: string): string {
  return new Date(value).toLocaleString('en-PH', {
    timeZone: 'Asia/Manila',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (!hours) return `${rest}m`
  return rest ? `${hours}h ${rest}m` : `${hours}h`
}
