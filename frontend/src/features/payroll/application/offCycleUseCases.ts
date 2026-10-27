import type { OffCycleRunFilter, OffCyclePayrollRepository } from './offCyclePorts'
import type {
  OffCycleBenefitRunInput,
  OffCyclePayrollRun,
  OffCycleThirteenthMonthRunInput,
  OffCycleUploadRow,
  ThirteenthMonthSource,
} from '../domain/offCycle'

export const MAX_OFF_CYCLE_UPLOAD_ROWS = 5000
const AMOUNT_PATTERN = /^\d+(\.\d{1,2})?$/
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/

function parseCsvRecords(contents: string): string[][] {
  const records: string[][] = []
  let record: string[] = []
  let field = ''
  let quoted = false
  const text = contents.replace(/^\uFEFF/, '')
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]
    if (character === '"') {
      if (quoted && text[index + 1] === '"') {
        field += '"'
        index += 1
      } else {
        quoted = !quoted
      }
    } else if (character === ',' && !quoted) {
      record.push(field)
      field = ''
    } else if ((character === '\n' || character === '\r') && !quoted) {
      if (character === '\r' && text[index + 1] === '\n') index += 1
      record.push(field)
      if (record.some((value) => value.trim())) records.push(record)
      record = []
      field = ''
    } else {
      field += character
    }
  }
  if (quoted) throw new Error('The CSV contains an unclosed quoted field.')
  if (field || record.length) {
    record.push(field)
    if (record.some((value) => value.trim())) records.push(record)
  }
  return records
}

/** Parses an incentive upload with columns employee_no, amount and optional notes. */
export function parseOffCycleCsv(contents: string): OffCycleUploadRow[] {
  const records = parseCsvRecords(contents)
  if (records.length < 2) throw new Error('The CSV must contain a header and at least one employee row.')

  const headers = records[0].map((value) => value.trim().toLowerCase())
  if (new Set(headers).size !== headers.length) throw new Error('The CSV contains duplicate column headers.')
  const employeeNoIndex = headers.indexOf('employee_no')
  const amountIndex = headers.indexOf('amount')
  const notesIndex = headers.indexOf('notes')
  if (employeeNoIndex < 0 || amountIndex < 0) {
    throw new Error('Required CSV columns are employee_no and amount. notes is optional.')
  }
  if (records.length - 1 > MAX_OFF_CYCLE_UPLOAD_ROWS) {
    throw new Error(`The CSV can contain no more than ${MAX_OFF_CYCLE_UPLOAD_ROWS.toLocaleString()} rows.`)
  }

  const seen = new Map<string, number>()
  return records.slice(1).map((values, index) => {
    const rowNumber = index + 2
    if (values.length !== headers.length) {
      throw new Error(`Row ${rowNumber}: the number of values does not match the header.`)
    }
    const employeeNo = values[employeeNoIndex].trim()
    const rawAmount = values[amountIndex].trim().replace(/,/g, '')
    const notes = notesIndex >= 0 ? values[notesIndex].trim() : ''
    if (!employeeNo) throw new Error(`Row ${rowNumber}: employee_no is required.`)
    if (employeeNo.length > 30) throw new Error(`Row ${rowNumber}: employee_no must be 30 characters or fewer.`)
    const amount = Number(rawAmount)
    if (!AMOUNT_PATTERN.test(rawAmount) || !Number.isFinite(amount) || amount <= 0) {
      throw new Error(`Row ${rowNumber}: amount must be greater than zero with at most 2 decimal places.`)
    }
    if (notes.length > 500) throw new Error(`Row ${rowNumber}: notes must be 500 characters or fewer.`)
    const key = employeeNo.toUpperCase()
    const firstRow = seen.get(key)
    if (firstRow) throw new Error(`Row ${rowNumber}: employee ${employeeNo} is duplicated (first on row ${firstRow}).`)
    seen.set(key, rowNumber)
    return { rowNumber, employeeNo, amount, notes }
  })
}

export class OffCyclePayrollUseCases {
  private readonly repository: OffCyclePayrollRepository

  constructor(repository: OffCyclePayrollRepository) {
    this.repository = repository
  }

  listRuns(filter: OffCycleRunFilter): Promise<OffCyclePayrollRun[]> {
    if (!filter.companyId) throw new Error('Select a company before loading off-cycle payroll runs.')
    return this.repository.listRuns(filter)
  }

  getRun(runId: string): Promise<OffCyclePayrollRun> {
    return this.repository.getRun(this.requireRunId(runId))
  }

  listThirteenthMonthSources(payrollGroupId: string): Promise<ThirteenthMonthSource[]> {
    if (!payrollGroupId) throw new Error('Select a payroll group first.')
    return this.repository.listThirteenthMonthSources(payrollGroupId)
  }

  createBenefitRun(input: OffCycleBenefitRunInput): Promise<OffCyclePayrollRun> {
    this.validateHeader(input.payrollGroupId, input.benefitTypeId, input.proposedPaymentDate, input.notes)
    if (!input.rows.length) throw new Error('Upload a CSV with at least one employee row.')
    if (input.rows.length > MAX_OFF_CYCLE_UPLOAD_ROWS) {
      throw new Error(`An off-cycle run can contain no more than ${MAX_OFF_CYCLE_UPLOAD_ROWS} employees.`)
    }
    return this.repository.createBenefitRun(input)
  }

  createThirteenthMonthRun(input: OffCycleThirteenthMonthRunInput): Promise<OffCyclePayrollRun> {
    this.validateHeader(input.payrollGroupId, input.benefitTypeId, input.proposedPaymentDate, input.notes)
    if (!input.thirteenthMonthRunId) throw new Error('Select a 13th-month calculation to pay.')
    return this.repository.createThirteenthMonthRun(input)
  }

  recalculateRun(runId: string): Promise<OffCyclePayrollRun> {
    return this.repository.recalculateRun(this.requireRunId(runId))
  }

  submitRun(runId: string): Promise<OffCyclePayrollRun> {
    return this.repository.submitRun(this.requireRunId(runId))
  }

  approveRun(runId: string): Promise<OffCyclePayrollRun> {
    return this.repository.approveRun(this.requireRunId(runId))
  }

  rejectRun(runId: string, reason: string): Promise<OffCyclePayrollRun> {
    const trimmed = reason.trim()
    if (!trimmed) throw new Error('Enter a reason for rejecting this off-cycle run.')
    if (trimmed.length > 500) throw new Error('The rejection reason must be 500 characters or fewer.')
    return this.repository.rejectRun(this.requireRunId(runId), trimmed)
  }

  markRunPaid(runId: string, actualPaymentDate: string): Promise<OffCyclePayrollRun> {
    if (!DATE_PATTERN.test(actualPaymentDate)) throw new Error('Enter the actual payment (release) date.')
    return this.repository.markRunPaid(this.requireRunId(runId), actualPaymentDate)
  }

  deleteRun(runId: string): Promise<void> {
    return this.repository.deleteRun(this.requireRunId(runId))
  }

  private requireRunId(runId: string): string {
    if (!runId) throw new Error('Select an off-cycle run first.')
    return runId
  }

  private validateHeader(
    payrollGroupId: string,
    benefitTypeId: string,
    proposedPaymentDate: string,
    notes: string,
  ): void {
    if (!payrollGroupId) throw new Error('Select a payroll group.')
    if (!benefitTypeId) throw new Error('Select a benefit type.')
    if (!DATE_PATTERN.test(proposedPaymentDate)) throw new Error('Enter the proposed release date.')
    if (notes.length > 500) throw new Error('Notes must be 500 characters or fewer.')
  }
}
