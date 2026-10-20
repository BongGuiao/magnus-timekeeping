import type { EmployeeWritePayload } from './employeeApi'

export interface EmployeeCsvRow {
  rowNumber: number
  payload: EmployeeWritePayload
}

export const EMPLOYEE_CSV_HEADERS = [
  'employee_no',
  'first_name',
  'middle_name',
  'last_name',
  'suffix',
  'preferred_name',
  'birth_date',
  'gender_code',
  'personal_email',
  'mobile_no',
  'record_status',
  'is_active',
] as const

function parseRecords(contents: string): string[][] {
  const records: string[][] = []
  let record: string[] = []
  let field = ''
  let quoted = false
  let closedQuote = false

  for (let index = 0; index < contents.length; index += 1) {
    const character = contents[index]

    if (quoted) {
      if (character === '"') {
        if (contents[index + 1] === '"') {
          field += '"'
          index += 1
        } else {
          quoted = false
          closedQuote = true
        }
      } else {
        field += character
      }
      continue
    }

    if (character === ',') {
      record.push(field)
      field = ''
      closedQuote = false
      continue
    }

    if (character === '\r' || character === '\n') {
      if (character === '\r' && contents[index + 1] === '\n') index += 1
      record.push(field)
      records.push(record)
      record = []
      field = ''
      closedQuote = false
      continue
    }

    if (character === '"' && field.length === 0 && !closedQuote) {
      quoted = true
      continue
    }

    if (closedQuote && character.trim() === '') continue
    if (closedQuote || character === '"') {
      throw new Error(`Malformed CSV near row ${records.length + 1}.`)
    }

    field += character
  }

  if (quoted) {
    throw new Error('Malformed CSV: a quoted field was not closed.')
  }

  if (field.length > 0 || record.length > 0) {
    record.push(field)
    records.push(record)
  }
  return records
}

function normalizeHeader(header: string): string {
  return header
    .replace(/^\uFEFF/, '')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
}

function normalizeGender(value: string): EmployeeWritePayload['gender_code'] | null {
  const normalized = value.trim().toUpperCase()
  if (!normalized) return 'OTHER'
  if (normalized === 'MALE' || normalized === 'FEMALE' || normalized === 'OTHER') return normalized
  return null
}

function normalizeRecordStatus(value: string): EmployeeWritePayload['record_status'] | null {
  const normalized = value.trim().toUpperCase()
  if (!normalized) return 'ACTIVE'
  if (normalized === 'ACTIVE' || normalized === 'ARCHIVED') return normalized
  return null
}

function normalizeIsActive(value: string, recordStatus: EmployeeWritePayload['record_status']): boolean | null {
  const normalized = value.trim().toLowerCase()
  if (!normalized) return recordStatus === 'ACTIVE'
  if (['true', 'yes', '1', 'active', 'enabled'].includes(normalized)) return true
  if (['false', 'no', '0', 'inactive', 'disabled'].includes(normalized)) return false
  return null
}

export function parseEmployeeCsv(contents: string): EmployeeCsvRow[] {
  const records = parseRecords(contents.trimStart().replace(/^\uFEFF/, ''))
  if (records.length < 2) {
    throw new Error('The CSV must include a header row and at least one employee row.')
  }

  const headers = records[0].map(normalizeHeader)
  const validHeaders = new Set<string>(EMPLOYEE_CSV_HEADERS)
  const unknownHeaders = headers.filter((header) => !validHeaders.has(header))
  const requiredHeaders = ['employee_no', 'first_name', 'last_name', 'personal_email']
  const missingHeaders = requiredHeaders.filter((header) => !headers.includes(header))
  if (unknownHeaders.length > 0 || missingHeaders.length > 0) {
    const messages = [
      missingHeaders.length ? `Missing required columns: ${missingHeaders.join(', ')}.` : '',
      unknownHeaders.length ? `Unknown columns: ${unknownHeaders.join(', ')}.` : '',
    ].filter(Boolean)
    throw new Error(messages.join(' '))
  }
  if (new Set(headers).size !== headers.length) {
    throw new Error('The CSV contains duplicate column headers.')
  }

  const rows: EmployeeCsvRow[] = []
  for (const [index, cells] of records.slice(1).entries()) {
    if (cells.every((cell) => cell.trim() === '')) continue
    const rowNumber = index + 2
    if (cells.length > headers.length) {
      throw new Error(`CSV row ${rowNumber} has more values than the header row.`)
    }

    const values = Object.fromEntries(headers.map((header, column) => [header, cells[column]?.trim() ?? '']))
    const recordStatus = normalizeRecordStatus(values.record_status ?? '')
    if (!recordStatus) {
      throw new Error(`CSV row ${rowNumber} has an invalid record_status; use ACTIVE or ARCHIVED.`)
    }
    const gender = normalizeGender(values.gender_code ?? '')
    if (!gender) {
      throw new Error(`CSV row ${rowNumber} has an invalid gender_code; use MALE, FEMALE, or OTHER.`)
    }
    const isActive = normalizeIsActive(values.is_active ?? '', recordStatus)
    if (isActive === null) {
      throw new Error(`CSV row ${rowNumber} has an invalid is_active value; use true/false, yes/no, or 1/0.`)
    }

    rows.push({
      rowNumber,
      payload: {
        employee_no: values.employee_no,
        first_name: values.first_name,
        middle_name: values.middle_name || null,
        last_name: values.last_name,
        suffix: values.suffix || null,
        preferred_name: values.preferred_name || null,
        birth_date: values.birth_date || null,
        gender_code: gender,
        personal_email: values.personal_email,
        mobile_no: values.mobile_no || null,
        photo_reference: null,
        record_status: recordStatus,
        is_active: isActive,
      },
    })
  }

  if (rows.length === 0) {
    throw new Error('The CSV does not contain any employee rows.')
  }
  return rows
}
