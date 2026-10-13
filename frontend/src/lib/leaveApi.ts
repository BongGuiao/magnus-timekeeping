import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export type LeaveUnitType = 'MINUTES' | 'HOURS' | 'DAYS'

export interface LeaveType {
  id: string
  company_id: string
  leave_code: string
  leave_name: string
  leave_category: string
  unit_type: LeaveUnitType
  annual_entitlement_minutes: number
  accrual_method: string
  minimum_service_months: number
  allow_negative_balance: boolean
  maximum_negative_minutes: number
  carryover_allowed: boolean
  maximum_carryover_minutes: number
  expiry_rule: string
  cash_conversion_allowed: boolean
  advance_notice_days: number
  document_required: boolean
  document_trigger_minutes: number
  exclude_rest_days: boolean
  exclude_holidays: boolean
  effective_from: string
  effective_to: string | null
  status: string
  is_active: boolean
}

export type LeaveTypePayload = Omit<LeaveType, 'id'>

export interface EmployeeEntitlement {
  id: string
  employee_id: string
  leave_type_id: string
  entitlement_year: number
  opening_minutes: number
  granted_minutes: number
  accrued_minutes: number
  carryover_minutes: number
  adjustment_minutes: number
  used_minutes: number
  reserved_minutes: number
  expired_minutes: number
  converted_minutes: number
  available_minutes: number
  last_calculated_at: string | null
}

export type EmployeeEntitlementPayload = Omit<EmployeeEntitlement, 'id'>

export interface LeaveApplication {
  id: string
  application_no: string
  employee_id: string
  leave_type_id: string
  start_at: string
  end_at: string
  duration_type: string
  requested_minutes: number
  paid_minutes: number | null
  unpaid_minutes: number | null
  reason: string
  contact_information: string | null
  reliever_employee_id: string | null
  is_retroactive: boolean
  workflow_instance_id: string | null
  status: string
  submitted_at: string | null
  approved_at: string | null
  cancelled_at: string | null
  payroll_posted: boolean
  created_at: string
  updated_at: string
}

export interface LeaveDashboardSnapshot {
  balances: Array<{
    type: string
    label: string
    unit_type: LeaveUnitType
    allotted_minutes: number
    used_minutes: number
    available_minutes: number
    entitlement_year: number
  }>
  applications: Array<{
    id: string
    application_no: string
    type: string
    leave_type_id: string
    unit_type: LeaveUnitType
    requested_minutes: number
    start_at: string
    end_at: string
    status: string
  }>
  refreshed_at: string
}

export interface SupervisorPendingLeave {
  id: string
  application_no: string
  employee_id: string
  employee_no: string
  employee_name: string
  leave_type_id: string
  leave_type_name: string
  unit_type: LeaveUnitType
  start_at: string
  end_at: string
  requested_minutes: number
  reason: string
  created_at: string | null
  status: string
}

export type LeaveApplicationPayload = Pick<
  LeaveApplication,
  'application_no' | 'leave_type_id' | 'start_at' | 'end_at' | 'duration_type' | 'requested_minutes' | 'reason'
> & {
  employee_id: string
  contact_information?: string | null
  status: 'DRAFT'
}

export function getAuthenticatedEmployeeId(): string | null {
  const token = localStorage.getItem('access_token')
  const payload = token?.split('.')[1]
  if (!payload) return null

  try {
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/')
    const decoded = atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '='))
    const claims: unknown = JSON.parse(decoded)
    if (typeof claims !== 'object' || claims === null || !('employee_id' in claims)) return null
    const employeeId = claims.employee_id
    return typeof employeeId === 'string' && employeeId.length > 0 ? employeeId : null
  } catch {
    return null
  }
}

const MINUTES_PER_UNIT: Record<LeaveUnitType, number> = {
  MINUTES: 1,
  HOURS: 60,
  DAYS: 480,
}

function toLeaveTypePayload(source: LeaveTypePayload): LeaveTypePayload {
  return {
    company_id: source.company_id,
    leave_code: source.leave_code,
    leave_name: source.leave_name,
    leave_category: source.leave_category,
    unit_type: source.unit_type,
    annual_entitlement_minutes: source.annual_entitlement_minutes,
    accrual_method: source.accrual_method,
    minimum_service_months: source.minimum_service_months,
    allow_negative_balance: source.allow_negative_balance,
    maximum_negative_minutes: source.maximum_negative_minutes,
    carryover_allowed: source.carryover_allowed,
    maximum_carryover_minutes: source.maximum_carryover_minutes,
    expiry_rule: source.expiry_rule,
    cash_conversion_allowed: source.cash_conversion_allowed,
    advance_notice_days: source.advance_notice_days,
    document_required: source.document_required,
    document_trigger_minutes: source.document_trigger_minutes,
    exclude_rest_days: source.exclude_rest_days,
    exclude_holidays: source.exclude_holidays,
    effective_from: source.effective_from,
    effective_to: source.effective_to,
    status: source.status,
    is_active: source.is_active,
  }
}

function toLeaveTypePatch(source: Partial<LeaveTypePayload>): Partial<LeaveTypePayload> {
  const fields = [
    'company_id',
    'leave_code',
    'leave_name',
    'leave_category',
    'unit_type',
    'annual_entitlement_minutes',
    'accrual_method',
    'minimum_service_months',
    'allow_negative_balance',
    'maximum_negative_minutes',
    'carryover_allowed',
    'maximum_carryover_minutes',
    'expiry_rule',
    'cash_conversion_allowed',
    'advance_notice_days',
    'document_required',
    'document_trigger_minutes',
    'exclude_rest_days',
    'exclude_holidays',
    'effective_from',
    'effective_to',
    'status',
    'is_active',
  ] as const satisfies readonly (keyof LeaveTypePayload)[]
  const payload: Partial<LeaveTypePayload> = {}
  for (const field of fields) {
    if (source[field] !== undefined) Object.assign(payload, { [field]: source[field] })
  }
  return payload
}

export function minutesToLeaveUnits(minutes: number, unit: LeaveUnitType): number {
  return minutes / (MINUTES_PER_UNIT[unit] ?? 480)
}

export function formatLeaveBalance(minutes: number, unit: LeaveUnitType): string {
  const effectiveUnit = unit ?? 'DAYS'
  const unitValue = minutesToLeaveUnits(minutes, effectiveUnit)
  const formattedValue = unitValue.toLocaleString(undefined, { maximumFractionDigits: 3 })
  const label = effectiveUnit === 'DAYS'
    ? (Math.abs(unitValue) === 1 ? 'day' : 'days')
    : effectiveUnit === 'HOURS'
      ? (Math.abs(unitValue) === 1 ? 'hour' : 'hours')
      : 'min'
  return `${formattedValue} ${label}`
}

export function leaveUnitsToMinutes(value: number, unit: LeaveUnitType): number {
  return Math.round(value * (MINUTES_PER_UNIT[unit] ?? 480))
}

export function calculateAvailableMinutes(entitlement: EmployeeEntitlementPayload): number {
  return entitlement.opening_minutes
    + entitlement.granted_minutes
    + entitlement.accrued_minutes
    + entitlement.carryover_minutes
    + entitlement.adjustment_minutes
    - entitlement.used_minutes
    - entitlement.reserved_minutes
    - entitlement.expired_minutes
    - entitlement.converted_minutes
}

function formatApiDetail(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === 'string') return item
      if (typeof item !== 'object' || item === null) return undefined
      const issue = item as { loc?: unknown; msg?: unknown; detail?: unknown }
      const message = typeof issue.msg === 'string'
        ? issue.msg
        : typeof issue.detail === 'string'
          ? issue.detail
          : undefined
      if (!message) return undefined
      const location = Array.isArray(issue.loc)
        ? issue.loc.filter((part): part is string | number => typeof part === 'string' || typeof part === 'number')
          .filter((part) => part !== 'body' && part !== 'query' && part !== 'path')
          .join('.')
        : ''
      return location ? `${location}: ${message}` : message
    }).filter((message): message is string => Boolean(message))
    return messages.length ? messages.join('; ') : undefined
  }
  if (typeof detail === 'object' && detail !== null) {
    const message = detail as { msg?: unknown; detail?: unknown }
    if (typeof message.detail === 'string') return message.detail
    if (typeof message.msg === 'string') return message.msg
  }
  return undefined
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as Partial<ApiErrorEnvelope> | undefined
    throw new Error(formatApiDetail(body?.detail) ?? fallback)
  }
  throw error
}

export async function fetchLeaveTypes(filters: { companyId?: string; leaveCode?: string } = {}): Promise<LeaveType[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<LeaveType[]>>('/leave-types/list', {
      params: {
        ...(filters.companyId ? { company_id: filters.companyId } : {}),
        ...(filters.leaveCode ? { leave_code: filters.leaveCode.trim() } : {}),
        ...(filters.leaveCode ? { leave_status: 'ACTIVE', is_active: true } : {}),
      },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load leave types.')
  }
}

export async function fetchMyLeaveApplications(): Promise<LeaveApplication[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<LeaveApplication[]>>('/leave-applications/list')
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load your leave applications.')
  }
}

export async function fetchLeaveDashboardSnapshot(): Promise<LeaveDashboardSnapshot> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<LeaveDashboardSnapshot>>('/leave-applications/dashboard')
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load your leave dashboard.')
  }
}

export async function fetchSupervisorPendingLeaves(): Promise<SupervisorPendingLeave[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<SupervisorPendingLeave[]>>(
      '/leave-applications/supervisor/pending',
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load pending team leave applications.')
  }
}

export async function fetchSupervisorPendingLeaveCount(): Promise<number> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<number>>(
      '/leave-applications/supervisor/pending/count',
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load the pending leave count.')
  }
}

export async function decideSupervisorPendingLeave(
  applicationId: string,
  decision: 'APPROVED' | 'REJECTED',
): Promise<LeaveApplication> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<LeaveApplication>>(
      `/leave-applications/supervisor/${encodeURIComponent(applicationId)}/decision`,
      { decision },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, `Could not ${decision.toLowerCase()} this leave application.`)
  }
}

export async function createLeaveApplication(payload: LeaveApplicationPayload): Promise<LeaveApplication> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<LeaveApplication>>('/leave-applications/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not save your leave application.')
  }
}

export async function createLeaveType(payload: LeaveTypePayload): Promise<LeaveType> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<LeaveType>>('/leave-types/create', toLeaveTypePayload(payload))
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the leave type.')
  }
}

export async function updateLeaveType(id: string, payload: Partial<LeaveTypePayload>): Promise<LeaveType> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<LeaveType>>('/leave-types/update', {
      ...toLeaveTypePatch(payload),
      id,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the leave type.')
  }
}

export async function fetchEmployeeEntitlements(employeeId?: string): Promise<EmployeeEntitlement[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<EmployeeEntitlement[]>>('/employee-entitlements/list', {
      params: employeeId ? { employee_id: employeeId } : undefined,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load employee entitlements.')
  }
}

export async function createEmployeeEntitlement(payload: EmployeeEntitlementPayload): Promise<EmployeeEntitlement> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EmployeeEntitlement>>('/employee-entitlements/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the employee entitlement.')
  }
}

export async function updateEmployeeEntitlement(
  id: string,
  payload: Partial<EmployeeEntitlementPayload>,
): Promise<EmployeeEntitlement> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<EmployeeEntitlement>>(
      `/employee-entitlements/update?entitlement_id=${encodeURIComponent(id)}`,
      payload,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the employee entitlement.')
  }
}
