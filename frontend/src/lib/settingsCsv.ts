import { fetchGeofences } from './geofenceApi'
import { fetchLeaveTypes } from './leaveApi'
import { fetchLocations } from './locationApi'
import { fetchOrgUnits } from './orgUnitApi'
import { fetchRestDayPatterns } from './restDayPatternApi'
import { fetchScheduleSegments, fetchScheduleTemplates } from './scheduleTemplateApi'
import type { BenefitType } from '../features/payroll/domain/payroll'
import type { OrgUnit } from '../types/orgUnit'
import type { Location } from '../types/location'
import type { Geofence } from '../types/geofence'
import type { LeaveType } from './leaveApi'
import type { RestDayPattern } from './restDayPatternApi'
import type { ScheduleSegment, ScheduleTemplate } from './scheduleTemplateApi'

export type SettingsCsvView =
  | 'org-units' | 'locations' | 'geofences' | 'schedule-templates'
  | 'rest-day-patterns' | 'leave-management' | 'company-benefit-types' | 'company-deduction-types'

export const SETTINGS_CSV_PERMISSIONS: Record<SettingsCsvView, string> = {
  'org-units': 'company.setup',
  locations: 'company.setup',
  geofences: 'company.setup',
  'schedule-templates': 'schedule.manage',
  'rest-day-patterns': 'schedule.manage',
  'leave-management': 'leave.manage',
  'company-benefit-types': 'payroll.manage',
  'company-deduction-types': 'payroll.manage',
}

export function isSettingsCsvView(view: string): view is SettingsCsvView {
  return Object.prototype.hasOwnProperty.call(SETTINGS_CSV_PERMISSIONS, view)
}

const ORG_FIELDS = [
  'id', 'company_id', 'parent_org_unit_id', 'org_unit_code', 'org_unit_name', 'org_unit_type',
  'manager_employee_id', 'manager_is_approver', 'excluded_approval_org_unit_ids', 'cost_center_code',
  'effective_from', 'effective_to', 'status', 'is_active',
] as const satisfies readonly (keyof OrgUnit)[]
const LOCATION_FIELDS = [
  'id', 'company_id', 'location_code', 'location_name', 'location_type', 'address_line1', 'region',
  'psgc_region_code', 'psgc_province_code', 'psgc_city_code', 'ncr_district', 'psgc_barangay_code',
  'barangay', 'city', 'province', 'postal_code', 'latitude', 'longitude', 'geo_point', 'timezone',
  'status', 'is_active',
] as const satisfies readonly (keyof Location)[]
const GEOFENCE_FIELDS = [
  'id', 'company_id', 'location_id', 'geofence_code', 'geofence_name', 'geofence_type',
  'center_point', 'radius_meters', 'boundary_polygon', 'maximum_gps_accuracy_meters',
  'effective_from', 'effective_to', 'source_type', 'source_reference_id', 'status', 'is_active',
] as const satisfies readonly (keyof Geofence)[]
type ScheduleExport = ScheduleTemplate & { segments: ScheduleSegment[] }
const SCHEDULE_FIELDS = [
  'id', 'company_id', 'schedule_code', 'schedule_name', 'schedule_type', 'required_minutes',
  'grace_minutes', 'grace_method', 'is_overnight', 'ot_eligible', 'pre_shift_ot_allowed',
  'minimum_ot_minutes', 'holiday_calendar_id', 'effective_from', 'effective_to', 'status',
  'is_active', 'segments',
] as const satisfies readonly (keyof ScheduleExport)[]
const PATTERN_FIELDS = [
  'id', 'pattern_code', 'pattern_name', 'cycle_length_days', 'description', 'is_active', 'days',
] as const satisfies readonly (keyof RestDayPattern)[]
const LEAVE_FIELDS = [
  'id', 'company_id', 'leave_code', 'leave_name', 'leave_category', 'unit_type',
  'annual_entitlement_minutes', 'accrual_method', 'minimum_service_months', 'allow_negative_balance',
  'maximum_negative_minutes', 'carryover_allowed', 'maximum_carryover_minutes', 'expiry_rule',
  'cash_conversion_allowed', 'advance_notice_days', 'document_required', 'document_trigger_minutes',
  'exclude_rest_days', 'exclude_holidays', 'effective_from', 'effective_to', 'status', 'is_active',
] as const satisfies readonly (keyof LeaveType)[]
const BENEFIT_FIELDS = [
  'id', 'payrollGroupId', 'code', 'name', 'category', 'taxTreatment', 'withholdingTiming',
  'attendanceBased', 'deductForLate', 'deductForUndertime', 'postingSchedule', 'isActive',
] as const satisfies readonly (keyof BenefitType)[]

function cell(value: unknown, header: string): string {
  let text: string
  if (value === null || value === undefined) text = ''
  else if (typeof value === 'string') {
    if (/^[\t\r\n]/.test(value) || /^[=+\-@]/.test(value.trimStart())) {
      throw new Error(`Cannot export ${header}: its value could be interpreted as a spreadsheet formula.`)
    }
    text = value
  } else if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error(`Cannot export ${header}: the number is invalid.`)
    text = String(value)
  } else if (typeof value === 'boolean') text = String(value)
  else {
    const json = JSON.stringify(value)
    if (json === undefined) throw new Error(`Cannot export ${header}: the value is invalid.`)
    text = json
  }
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

function csv<T>(rows: T[], fields: readonly (keyof T & string)[]): string {
  return '\uFEFF' + [
    fields.join(','),
    ...rows.map((row) => fields.map((field) => cell(row[field], field)).join(',')),
  ].join('\r\n') + '\r\n'
}

function checkLimit<T>(items: T[], maximum: number, label: string): T[] {
  if (!Array.isArray(items)) throw new Error(`The ${label} API returned an invalid list.`)
  if (items.length >= maximum) {
    throw new Error(`Cannot export ${label}: the API limit of ${maximum} records was reached. Contact an administrator to avoid an incomplete export.`)
  }
  return items
}

function coordinate(value: number | string | null, field: string): number | null {
  if (value === null) return null
  if (typeof value === 'string' && !value.trim()) throw new Error(`Cannot export ${field}: the number is invalid.`)
  const number = Number(value)
  if (!Number.isFinite(number)) throw new Error(`Cannot export ${field}: the number is invalid.`)
  return number
}

export interface SettingsCsvContext {
  companyId: string
  payrollGroupId?: string
  loadBenefitTypes?: (groupId: string) => Promise<BenefitType[]>
}

export async function buildSettingsCsv(view: SettingsCsvView, context: SettingsCsvContext): Promise<string> {
  const { companyId } = context
  if (view !== 'rest-day-patterns' && !companyId) throw new Error('Select a company before downloading CSV.')
  switch (view) {
    case 'org-units':
      return csv(checkLimit(await fetchOrgUnits(companyId), 1000, 'org units'), ORG_FIELDS)
    case 'locations': {
      const locations = checkLimit(await fetchLocations(companyId), 1000, 'locations')
      return csv(locations.map((location) => ({
        ...location,
        latitude: coordinate(location.latitude, 'latitude'),
        longitude: coordinate(location.longitude, 'longitude'),
      })), LOCATION_FIELDS)
    }
    case 'geofences':
      return csv(checkLimit(await fetchGeofences(companyId), 1000, 'geofences').map((fence) => ({
        ...fence, radius_meters: coordinate(fence.radius_meters, 'radius_meters'),
      })), GEOFENCE_FIELDS)
    case 'schedule-templates': {
      const templates = checkLimit(await fetchScheduleTemplates({ companyId }), 1000, 'schedule templates')
      const rows = await Promise.all(templates.map(async (template) => ({
        ...template,
        segments: checkLimit(await fetchScheduleSegments(template.id), 100, 'schedule segments'),
      })))
      return csv(rows, SCHEDULE_FIELDS)
    }
    case 'rest-day-patterns': {
      const patterns = await fetchRestDayPatterns(null)
      if (!Array.isArray(patterns)) throw new Error('The rest day pattern API returned an invalid list.')
      if (patterns.some((pattern) => !Array.isArray(pattern.days))) {
        throw new Error('The rest day pattern API returned invalid cycle days.')
      }
      return csv(patterns, PATTERN_FIELDS)
    }
    case 'leave-management':
      return csv(checkLimit(await fetchLeaveTypes({ companyId }), 1000, 'leave types'), LEAVE_FIELDS)
    case 'company-benefit-types':
    case 'company-deduction-types': {
      if (!context.payrollGroupId || !context.loadBenefitTypes) {
        throw new Error('Select a payroll group before downloading CSV.')
      }
      const types = await context.loadBenefitTypes(context.payrollGroupId)
      if (!Array.isArray(types)) throw new Error('The benefit type API returned an invalid list.')
      return csv(types.filter((type) =>
        (type.category === 'EMPLOYEE_DEDUCTION') === (view === 'company-deduction-types'),
      ), BENEFIT_FIELDS)
    }
  }
}

export async function downloadSettingsCsv(view: SettingsCsvView, context: SettingsCsvContext): Promise<void> {
  const contents = await buildSettingsCsv(view, context)
  const url = URL.createObjectURL(new Blob([contents], { type: 'text/csv;charset=utf-8' }))
  let link: HTMLAnchorElement | undefined
  try {
    link = document.createElement('a')
    link.href = url
    link.download = `${view}.csv`
    document.body.appendChild(link)
    link.click()
  } finally {
    try {
      link?.remove()
    } finally {
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    }
  }
}
