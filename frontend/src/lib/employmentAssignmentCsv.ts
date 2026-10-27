import { parseCsvRecords, normalizeCsvHeader } from './employeeCsv'

export const EMPLOYMENT_ASSIGNMENT_CSV_HEADERS = [
  'employee_no',
  'company_code',
  'org_unit_code',
  'supervisor_employee_no',
  'employment_type',
  'employee_category',
  'operational_group',
  'payroll_group_code',
  'location_codes',
  'primary_location_code',
  'hire_date',
  'effective_from',
  'effective_to',
  'separation_date',
  'status',
  'is_active',
] as const

export interface EmploymentAssignmentCsvRow {
  rowNumber: number
  values: Record<string, string>
}

export function parseEmploymentAssignmentCsv(contents: string): EmploymentAssignmentCsvRow[] {
  const records = parseCsvRecords(contents.trimStart().replace(/^\uFEFF/, ''))
  if (records.length < 2) {
    throw new Error('The CSV must include a header row and at least one assignment row.')
  }

  const headers = records[0].map(normalizeCsvHeader)
  const allowedHeaders = new Set<string>(EMPLOYMENT_ASSIGNMENT_CSV_HEADERS)
  const missingHeaders = ['employee_no', 'company_code', 'employment_type', 'employee_category', 'hire_date', 'effective_from']
    .filter((header) => !headers.includes(header))
  const unknownHeaders = headers.filter((header) => !allowedHeaders.has(header))
  if (missingHeaders.length || unknownHeaders.length) {
    const messages = [
      missingHeaders.length ? `Missing required columns: ${missingHeaders.join(', ')}.` : '',
      unknownHeaders.length ? `Unknown columns: ${unknownHeaders.join(', ')}.` : '',
    ].filter(Boolean)
    throw new Error(messages.join(' '))
  }
  if (new Set(headers).size !== headers.length) {
    throw new Error('The CSV contains duplicate column headers.')
  }

  const rows: EmploymentAssignmentCsvRow[] = []
  for (const [index, cells] of records.slice(1).entries()) {
    if (cells.every((cell) => cell.trim() === '')) continue
    const rowNumber = index + 2
    if (cells.length > headers.length) {
      throw new Error(`CSV row ${rowNumber} has more values than the header row.`)
    }
    rows.push({
      rowNumber,
      values: Object.fromEntries(headers.map((header, column) => [header, cells[column]?.trim() ?? ''])),
    })
  }
  if (!rows.length) throw new Error('The CSV does not contain any assignment rows.')
  if (rows.length > 500) throw new Error('The CSV can contain no more than 500 assignment rows per import.')
  return rows
}
