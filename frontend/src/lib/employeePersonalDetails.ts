import { z } from 'zod'
import { normalizeCsvHeader, parseCsvRecords } from './employeeCsv'

export const CIVIL_STATUSES = ['SINGLE', 'MARRIED', 'WIDOWED', 'SEPARATED', 'DIVORCED', 'OTHER'] as const

export const personalDetailsSchema = z.object({
  bank_account_no: z.string().trim().max(100),
  sss_no: z.string().trim().max(30),
  pagibig_no: z.string().trim().max(30),
  philhealth_no: z.string().trim().max(30),
  tin_no: z.string().trim().max(30),
  address_line_1: z.string().trim().max(255),
  address_line_2: z.string().trim().max(255),
  region: z.string().trim().max(100),
  psgc_region_code: z.string().regex(/^$|^[0-9]{9}$/),
  psgc_province_code: z.string().regex(/^$|^[0-9]{9}$/),
  psgc_city_code: z.string().regex(/^$|^[0-9]{9}$/),
  psgc_barangay_code: z.string().regex(/^$|^[0-9]{9}$/),
  barangay: z.string().trim().max(100),
  city_municipality: z.string().trim().max(100),
  province: z.string().trim().max(100),
  postal_code: z.string().trim().max(20),
  civil_status: z.union([z.literal(''), z.enum(CIVIL_STATUSES)]),
})

export type PersonalDetailsValues = z.infer<typeof personalDetailsSchema>
export type PersonalDetailsPayload = { [K in keyof PersonalDetailsValues]: PersonalDetailsValues[K] | null }
export interface PersonalDetails extends PersonalDetailsPayload {
  employee_id: string
}
type PsgcCodeField = 'psgc_region_code' | 'psgc_province_code' | 'psgc_city_code' | 'psgc_barangay_code'
export type PersonalDetailsImportRow = Omit<PersonalDetailsPayload, PsgcCodeField> & { employee_no: string }
export interface PersonalDetailsImportResult {
  employee_no: string
  filled_fields: string[]
  conflicting_fields: string[]
  status: 'ready' | 'updated' | 'skipped'
}

export const EMPTY_PERSONAL_DETAILS: PersonalDetailsValues = {
  bank_account_no: '', sss_no: '', pagibig_no: '', philhealth_no: '', tin_no: '',
  address_line_1: '', address_line_2: '', region: '', psgc_region_code: '',
  psgc_province_code: '', psgc_city_code: '', psgc_barangay_code: '', barangay: '', city_municipality: '',
  province: '', postal_code: '', civil_status: '',
}

export const PERSONAL_DETAILS_FIELDS = [
  { key: 'bank_account_no', label: 'Bank account number', maxLength: 100 },
  { key: 'sss_no', label: 'SSS number', maxLength: 30 },
  { key: 'pagibig_no', label: 'Pag-IBIG number', maxLength: 30 },
  { key: 'philhealth_no', label: 'PhilHealth number', maxLength: 30 },
  { key: 'tin_no', label: 'TIN', maxLength: 30 },
  { key: 'address_line_1', label: 'House / unit / street', maxLength: 255 },
  { key: 'address_line_2', label: 'Subdivision / additional address', maxLength: 255 },
  { key: 'region', label: 'Region', maxLength: 100 },
  { key: 'barangay', label: 'Barangay', maxLength: 100 },
  { key: 'city_municipality', label: 'City / municipality', maxLength: 100 },
  { key: 'province', label: 'Province / Metro Manila', maxLength: 100 },
  { key: 'postal_code', label: 'Postal code', maxLength: 20 },
] as const

export const PERSONAL_DETAILS_CSV_HEADERS = [
  'employee_no', ...PERSONAL_DETAILS_FIELDS.map((field) => field.key), 'civil_status',
]

const PERSONAL_DETAILS_CSV_EXAMPLE: Record<string, string> = {
  employee_no: 'EXAMPLE_EMP001',
  bank_account_no: 'EXAMPLE_000123456789',
  sss_no: 'EXAMPLE_0012345678',
  pagibig_no: 'EXAMPLE_000123456789',
  philhealth_no: 'EXAMPLE_001234567890',
  tin_no: 'EXAMPLE_000123456000',
  address_line_1: 'EXAMPLE_123 Sample Street',
  address_line_2: 'EXAMPLE_Sample Subdivision',
  region: 'EXAMPLE_Region',
  barangay: 'EXAMPLE_Barangay',
  city_municipality: 'EXAMPLE_City',
  province: 'EXAMPLE_Province',
  postal_code: 'EXAMPLE_1000',
  civil_status: 'SINGLE',
}
const SAMPLE_PLACEHOLDERS = new Set(
  Object.values(PERSONAL_DETAILS_CSV_EXAMPLE).filter((value) => value.startsWith('EXAMPLE_')),
)

function csvCell(value: string, header: string): string {
  if (/^[=+\-@]/.test(value.trimStart())) {
    throw new Error(`Cannot export ${header}: its value could be interpreted as a spreadsheet formula.`)
  }
  return /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value
}

export function personalDetailsCsvTemplate(example: PersonalDetailsImportRow | null = null): string {
  const values: Record<string, string | null> = example ?? PERSONAL_DETAILS_CSV_EXAMPLE
  return [
    PERSONAL_DETAILS_CSV_HEADERS.join(','),
    PERSONAL_DETAILS_CSV_HEADERS.map((header) => csvCell(values[header] ?? '', header)).join(','),
    '',
  ].join('\r\n')
}

export function personalDetailsFormValues(details: PersonalDetails | null): PersonalDetailsValues {
  return personalDetailsSchema.parse(Object.fromEntries(
    Object.keys(EMPTY_PERSONAL_DETAILS).map((key) => [key, details?.[key as keyof PersonalDetailsValues] ?? '']),
  ))
}

export function personalDetailsPayload(values: PersonalDetailsValues): PersonalDetailsPayload {
  return {
    bank_account_no: values.bank_account_no || null,
    sss_no: values.sss_no || null,
    pagibig_no: values.pagibig_no || null,
    philhealth_no: values.philhealth_no || null,
    tin_no: values.tin_no || null,
    address_line_1: values.address_line_1 || null,
    address_line_2: values.address_line_2 || null,
    region: values.region || null,
    psgc_region_code: values.psgc_region_code || null,
    psgc_province_code: values.psgc_province_code || null,
    psgc_city_code: values.psgc_city_code || null,
    psgc_barangay_code: values.psgc_barangay_code || null,
    barangay: values.barangay || null,
    city_municipality: values.city_municipality || null,
    province: values.province || null,
    postal_code: values.postal_code || null,
    civil_status: values.civil_status || null,
  }
}

export function parsePersonalDetailsCsv(contents: string): PersonalDetailsImportRow[] {
  const records = parseCsvRecords(contents.replace(/^\uFEFF/, ''))
  if (records.length < 2) throw new Error('Include a header and at least one employee row.')
  const headers = records[0].map(normalizeCsvHeader)
  if (!headers.includes('employee_no')) throw new Error('Missing employee_no column.')
  const unknown = headers.filter((header) => !PERSONAL_DETAILS_CSV_HEADERS.includes(header))
  if (unknown.length) throw new Error(`Unknown columns: ${unknown.join(', ')}.`)
  if (new Set(headers).size !== headers.length) throw new Error('Duplicate column headers.')
  const seen = new Set<string>()
  const rows: PersonalDetailsImportRow[] = []
  for (const [index, cells] of records.slice(1).entries()) {
    if (cells.every((cell) => !cell.trim())) continue
    const rowNumber = index + 2
    if (cells.length > headers.length) throw new Error(`Row ${rowNumber} has too many values.`)
    const values = Object.fromEntries(headers.map((header, column) => [header, cells[column]?.trim() ?? '']))
    if (Object.values(values).some((value) => SAMPLE_PLACEHOLDERS.has(value))) {
      throw new Error(`Row ${rowNumber}: replace or remove every EXAMPLE_ value before importing.`)
    }
    const employeeNo = values.employee_no
    if (!employeeNo || employeeNo.length > 30) throw new Error(`Row ${rowNumber}: employee_no is required (maximum 30 characters).`)
    if (seen.has(employeeNo)) throw new Error(`Row ${rowNumber}: duplicate employee number ${employeeNo}.`)
    seen.add(employeeNo)
    const parsed = personalDetailsSchema.safeParse({
      ...EMPTY_PERSONAL_DETAILS, ...values, civil_status: (values.civil_status ?? '').toUpperCase(),
    })
    if (!parsed.success) {
      throw new Error(`Row ${rowNumber}: invalid ${parsed.error.issues.map((issue) => issue.path.join('.')).join(', ')}.`)
    }
    const {
      psgc_region_code: _regionCode, psgc_province_code: _provinceCode,
      psgc_city_code: _cityCode, psgc_barangay_code: _barangayCode, ...details
    } = personalDetailsPayload(parsed.data)
    rows.push({ employee_no: employeeNo, ...details })
  }
  if (!rows.length || rows.length > 500) throw new Error('Include between 1 and 500 employee rows.')
  return rows
}
