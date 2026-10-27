import { AxiosError } from 'axios'
import { apiClient } from '../../../lib/apiClient'
import { fetchEmployees } from '../../../lib/employeeApi'
import { fetchPayrollCutoffs } from '../../../lib/payrollCutoffApi'
import { fetchPayrollGroups } from '../../../lib/payrollGroupApi'
import { fetchEmploymentAssignments } from '../../../lib/employeeRelatedApi'
import type { ApiSuccessEnvelope } from '../../../types/auth'
import type { Employee } from '../../../types/employee'
import type { EmploymentAssignment } from '../../../types/employeeRelated'
import type { PayrollCutoff } from '../../../lib/payrollCutoffApi'
import type { PayrollGroup } from '../../../lib/payrollGroupApi'
import type {
  BenefitType,
  BenefitTypeInput,
  EmployeeBenefitEntitlement,
  EmployeeBenefitEntitlementInput,
  EmployeeBenefitDeduction,
  EmployeeBenefitDeductionInput,
  EmployeeLoan,
  EmployeeLoanInput,
  EmployeeLoanRestructureInput,
  CompensationInput,
  EmployeeCompensation,
  EmployeeYtdTaxBalance,
  ContributionBracket,
  ContributionBracketInput,
  ContributionSchedule,
  ContributionScheduleInput,
  CutoffBenefit,
  CutoffBenefitInput,
  CutoffBenefitUploadRow,
  CutoffBenefitUploadResult,
  EarningRule,
  GrossPayRun,
  PayrollBenefitLine,
  PayrollContributionLine,
  PayrollComponentCode,
  PayrollCutoffOption,
  PayrollEmployeeOption,
  PayrollGroupOption,
  PayrollSystemParameters,
  StatutoryProgram,
  ThirteenthMonthRun,
  WithholdingTaxBracket,
  WithholdingTaxBracketInput,
  WithholdingTaxSchedule,
  WithholdingTaxScheduleInput,
} from '../domain/payroll'
import type { PayrollRepository } from '../application/ports'

interface BackendCompensation {
  id: string
  employee_id: string
  payroll_group_id: string
  base_rate: number | string
  currency: string
  effective_from: string
  effective_to: string | null
  is_active: boolean
}

interface BackendEarningRule {
  component_code: PayrollComponentCode
  multiplier: number | string
}

interface BackendGrossPayLine {
  component_code: GrossPayRun['results'][number]['lines'][number]['componentCode']
  minutes: number
  multiplier: number | string
  amount: number | string
}

interface BackendGrossPayResult {
  employee_id: string
  cutoff_result_id: string
  currency: string | null
  base_rate: number | string | null
  gross_amount: number | string | null
  status: 'HOLD' | 'READY'
  gross_status?: 'HOLD' | 'READY' | null
  hold_reason: string | null
  lines: BackendGrossPayLine[]
  source_minutes: Record<string, number>
  cash_benefit_amount?: number | string | null
  non_cash_benefit_amount?: number | string | null
  employee_benefit_deductions?: number | string | null
  exempt_limited_benefit_amount?: number | string | null
  taxable_income?: number | string | null
  employee_contributions?: number | string | null
  employer_contributions?: number | string | null
  withholding_tax?: number | string | null
  net_amount?: number | string | null
  benefit_lines?: {
    benefit_code: string
    benefit_name: string
    category: PayrollBenefitLine['category']
    tax_treatment: PayrollBenefitLine['taxTreatment']
    withholding_timing: PayrollBenefitLine['withholdingTiming']
    amount: number | string
  }[]
  contribution_lines?: {
    program_code: PayrollContributionLine['programCode']
    employee_amount: number | string
    employer_amount: number | string
  }[]
}

interface BackendGrossPayRun {
  id: string
  cutoff_id: string
  calculation_version: string
  calculated_at: string
  calculated_by: string
  results: BackendGrossPayResult[]
}

interface BackendSchedule {
  id: string
  schedule_name: string
  effective_from: string
  effective_to: string | null
  source_reference: string
  status: 'DRAFT' | 'ACTIVE' | 'RETIRED'
  created_at: string
  created_by: string | null
  updated_at: string
  updated_by: string | null
  row_version: number
}

interface BackendContributionSchedule extends BackendSchedule {
  program_code: StatutoryProgram
}

interface BackendTaxSchedule extends BackendSchedule {
  tax_exempt_benefit_limit: number | string
  calculation_basis: 'ANNUAL_YTD' | 'SEMI_MONTHLY'
}

interface BackendPayrollSystemParameters {
  company_id: string
  year_end_wtax_reconciliation_enabled: boolean
  thirteenth_month_enabled: boolean
  schedule_assignment_approval_required: boolean
  statutory_contribution_timing: 'PER_CUTOFF' | 'FINAL_CUTOFF'
}

interface BackendThirteenthMonthRun {
  id: string
  tax_year: number
  covered_period_from: string
  covered_period_to: string
  calculated_at: string
  calculated_by: string
  results: {
    employee_id: string
    employee_no: string
    employee_name: string
    basic_salary_earned: number | string
    thirteenth_month_pay: number | string
    tax_exempt_amount: number | string
    taxable_amount: number | string
    source_payroll_periods: number
  }[]
}

interface BackendContributionBracket {
  id: string
  schedule_id: string
  bracket_number: number
  compensation_min: number | string
  compensation_max: number | string | null
  contribution_base: number | string
  employee_rate: number | string
  employer_rate: number | string
  employee_fixed_amount: number | string
  employer_fixed_amount: number | string
  employer_additional_fixed_amount: number | string
  employee_contribution_cap: number | string | null
  employer_contribution_cap: number | string | null
}

interface BackendTaxBracket {
  id: string
  schedule_id: string
  bracket_number: number
  annual_income_min: number | string
  annual_income_max: number | string | null
  base_tax: number | string
  marginal_rate: number | string
  excess_over: number | string
}

interface BackendBenefitType {
  id: string
  payroll_group_id: string
  code: string
  name: string
  category: BenefitType['category']
  tax_treatment: BenefitType['taxTreatment']
  withholding_timing: BenefitType['withholdingTiming']
  attendance_based: boolean
  deduct_for_late: boolean
  deduct_for_undertime: boolean
  posting_schedule: BenefitType['postingSchedule']
  is_active: boolean
  created_at: string
  created_by: string
  updated_at: string
  updated_by: string
  row_version: number
}

interface BackendCutoffBenefit {
  id: string
  cutoff_id: string
  employee_id: string
  benefit_type_id: string
  benefit_code: string
  benefit_name: string
  category: BenefitType['category']
  tax_treatment: BenefitType['taxTreatment']
  withholding_timing: BenefitType['withholdingTiming']
  amount: number | string
  notes: string | null
  attendance_based: boolean
  deduct_for_late: boolean
  deduct_for_undertime: boolean
}

interface BackendEmployeeBenefitDeduction {
  id: string
  employee_id: string
  benefit_type_id: string
  benefit_code: string
  benefit_name: string
  amount_per_occurrence: number | string
  schedule: EmployeeBenefitDeduction['schedule']
  effective_from: string
  effective_to: string | null
  is_active: boolean
}

interface BackendEmployeeLoan {
  id: string
  employee_id: string
  payroll_group_id: string
  reference_number: string
  principal_amount: number | string
  installment_amount: number | string
  schedule: EmployeeLoan['schedule']
  effective_from: string
  outstanding_balance: number | string
  status: EmployeeLoan['status']
  previous_loan_id: string | null
  created_at: string
  repayments: {
    id: string
    loan_id: string
    cutoff_id: string
    gross_pay_run_id: string
    amount: number | string
    created_at: string
    cutoff_code: string
  }[]
}

interface BackendEmployeeBenefitEntitlement {
  id: string
  employee_id: string
  benefit_type_id: string
  benefit_code: string
  benefit_name: string
  amount_per_occurrence: number | string
  schedule: EmployeeBenefitEntitlement['schedule']
  effective_from: string
  effective_to: string | null
  is_active: boolean
}

interface BackendYtdTaxBalance {
  employee_id: string
  tax_year: number
  taxable_income: number | string
  tax_withheld: number | string
  exempt_limited_benefits: number | string
}

function toYtdTaxBalance(value: BackendYtdTaxBalance): EmployeeYtdTaxBalance {
  return {
    employeeId: value.employee_id,
    taxYear: value.tax_year,
    taxableIncome: toNumber(value.taxable_income),
    taxWithheld: toNumber(value.tax_withheld),
    exemptLimitedBenefits: toNumber(value.exempt_limited_benefits),
  }
}

function toBenefitType(value: BackendBenefitType): BenefitType {
  return {
    id: value.id,
    payrollGroupId: value.payroll_group_id,
    code: value.code,
    name: value.name,
    category: value.category,
    taxTreatment: value.tax_treatment,
    withholdingTiming: value.withholding_timing,
    attendanceBased: value.attendance_based,
    deductForLate: value.deduct_for_late,
    deductForUndertime: value.deduct_for_undertime,
    postingSchedule: value.posting_schedule,
    isActive: value.is_active,
    createdAt: value.created_at,
    createdBy: value.created_by,
    updatedAt: value.updated_at,
    updatedBy: value.updated_by,
    rowVersion: value.row_version,
  }
}

function toEmployeeBenefitEntitlement(
  value: BackendEmployeeBenefitEntitlement,
): EmployeeBenefitEntitlement {
  return {
    id: value.id,
    employeeId: value.employee_id,
    benefitTypeId: value.benefit_type_id,
    benefitCode: value.benefit_code,
    benefitName: value.benefit_name,
    amountPerOccurrence: toNumber(value.amount_per_occurrence),
    schedule: value.schedule,
    effectiveFrom: value.effective_from,
    effectiveTo: value.effective_to,
    isActive: value.is_active,
  }
}

function toEmployeeBenefitDeduction(
  value: BackendEmployeeBenefitDeduction,
): EmployeeBenefitDeduction {
  return {
    id: value.id,
    employeeId: value.employee_id,
    benefitTypeId: value.benefit_type_id,
    benefitCode: value.benefit_code,
    benefitName: value.benefit_name,
    amountPerOccurrence: toNumber(value.amount_per_occurrence),
    schedule: value.schedule,
    effectiveFrom: value.effective_from,
    effectiveTo: value.effective_to,
    isActive: value.is_active,
  }
}

function toEmployeeLoan(value: BackendEmployeeLoan): EmployeeLoan {
  return {
    id: value.id,
    employeeId: value.employee_id,
    payrollGroupId: value.payroll_group_id,
    referenceNumber: value.reference_number,
    principalAmount: toNumber(value.principal_amount),
    installmentAmount: toNumber(value.installment_amount),
    schedule: value.schedule,
    effectiveFrom: value.effective_from,
    outstandingBalance: toNumber(value.outstanding_balance),
    status: value.status,
    previousLoanId: value.previous_loan_id,
    createdAt: value.created_at,
    repayments: value.repayments.map((repayment) => ({
      id: repayment.id,
      loanId: repayment.loan_id,
      cutoffId: repayment.cutoff_id,
      grossPayRunId: repayment.gross_pay_run_id,
      amount: toNumber(repayment.amount),
      createdAt: repayment.created_at,
      cutoffCode: repayment.cutoff_code,
    })),
  }
}

function toCutoffBenefit(value: BackendCutoffBenefit): CutoffBenefit {
  return {
    id: value.id,
    cutoffId: value.cutoff_id,
    employeeId: value.employee_id,
    benefitTypeId: value.benefit_type_id,
    benefitCode: value.benefit_code,
    benefitName: value.benefit_name,
    category: value.category,
    taxTreatment: value.tax_treatment,
    withholdingTiming: value.withholding_timing,
    amount: toNumber(value.amount),
    notes: value.notes,
    attendanceBased: value.attendance_based,
    deductForLate: value.deduct_for_late,
    deductForUndertime: value.deduct_for_undertime,
  }
}

function toContributionSchedule(schedule: BackendContributionSchedule): ContributionSchedule {
  return {
    id: schedule.id,
    programCode: schedule.program_code,
    scheduleName: schedule.schedule_name,
    effectiveFrom: schedule.effective_from,
    effectiveTo: schedule.effective_to,
    sourceReference: schedule.source_reference,
    status: schedule.status,
    createdAt: schedule.created_at,
    createdBy: schedule.created_by,
    updatedAt: schedule.updated_at,
    updatedBy: schedule.updated_by,
    rowVersion: schedule.row_version,
  }
}

function toWithholdingTaxSchedule(schedule: BackendTaxSchedule): WithholdingTaxSchedule {
  return {
    id: schedule.id,
    scheduleName: schedule.schedule_name,
    effectiveFrom: schedule.effective_from,
    effectiveTo: schedule.effective_to,
    taxExemptBenefitLimit: toNumber(schedule.tax_exempt_benefit_limit),
    calculationBasis: schedule.calculation_basis,
    sourceReference: schedule.source_reference,
    status: schedule.status,
    createdAt: schedule.created_at,
    createdBy: schedule.created_by,
    updatedAt: schedule.updated_at,
    updatedBy: schedule.updated_by,
    rowVersion: schedule.row_version,
  }
}

function toContributionBracket(bracket: BackendContributionBracket): ContributionBracket {
  return {
    id: bracket.id,
    scheduleId: bracket.schedule_id,
    bracketNumber: bracket.bracket_number,
    compensationMin: toNumber(bracket.compensation_min),
    compensationMax: bracket.compensation_max === null ? null : toNumber(bracket.compensation_max),
    contributionBase: toNumber(bracket.contribution_base),
    employeeRate: toNumber(bracket.employee_rate),
    employerRate: toNumber(bracket.employer_rate),
    employeeFixedAmount: toNumber(bracket.employee_fixed_amount),
    employerFixedAmount: toNumber(bracket.employer_fixed_amount),
    employerAdditionalFixedAmount: toNumber(bracket.employer_additional_fixed_amount),
    employeeContributionCap: bracket.employee_contribution_cap === null ? null : toNumber(bracket.employee_contribution_cap),
    employerContributionCap: bracket.employer_contribution_cap === null ? null : toNumber(bracket.employer_contribution_cap),
  }
}

function toWithholdingTaxBracket(bracket: BackendTaxBracket): WithholdingTaxBracket {
  return {
    id: bracket.id,
    scheduleId: bracket.schedule_id,
    bracketNumber: bracket.bracket_number,
    annualIncomeMin: toNumber(bracket.annual_income_min),
    annualIncomeMax: bracket.annual_income_max === null ? null : toNumber(bracket.annual_income_max),
    baseTax: toNumber(bracket.base_tax),
    marginalRate: toNumber(bracket.marginal_rate),
    excessOver: toNumber(bracket.excess_over),
  }
}

function toBackendContributionBracket(input: ContributionBracketInput) {
  return {
    bracket_number: input.bracketNumber,
    compensation_min: input.compensationMin,
    compensation_max: input.compensationMax,
    contribution_base: input.contributionBase,
    employee_rate: input.employeeRate,
    employer_rate: input.employerRate,
    employee_fixed_amount: input.employeeFixedAmount,
    employer_fixed_amount: input.employerFixedAmount,
    employer_additional_fixed_amount: input.employerAdditionalFixedAmount,
    employee_contribution_cap: input.employeeContributionCap,
    employer_contribution_cap: input.employerContributionCap,
  }
}

function toBackendTaxBracket(input: WithholdingTaxBracketInput) {
  return {
    bracket_number: input.bracketNumber,
    annual_income_min: input.annualIncomeMin,
    annual_income_max: input.annualIncomeMax,
    base_tax: input.baseTax,
    marginal_rate: input.marginalRate,
    excess_over: input.excessOver,
  }
}

export function toNumber(value: number | string): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) throw new Error('The payroll API returned an invalid numeric value.')
  return parsed
}

export function requireArray<T>(value: T[] | undefined, message: string): T[] {
  if (!Array.isArray(value)) throw new Error(message)
  return value
}

function formatApiErrorDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail.trim() || null
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (typeof item !== 'object' || item === null) return null

        const issue = item as { loc?: unknown; msg?: unknown; message?: unknown; detail?: unknown }
        const message = typeof issue.msg === 'string'
          ? issue.msg
          : typeof issue.message === 'string'
            ? issue.message
            : formatApiErrorDetail(issue.detail)
        if (!message) return null

        const location = Array.isArray(issue.loc)
          ? issue.loc.filter((part): part is string | number =>
            typeof part === 'string' || typeof part === 'number')
          : []
        const field = location.filter((part) => part !== 'body' && part !== 'query' && part !== 'path').join('.')
        return field ? `${field}: ${message}` : message
      })
      .filter((message): message is string => Boolean(message))
    return messages.length ? messages.join('; ') : null
  }
  if (typeof detail === 'object' && detail !== null) {
    const body = detail as { detail?: unknown; msg?: unknown; message?: unknown }
    const message = typeof body.message === 'string'
      ? body.message
      : typeof body.msg === 'string'
        ? body.msg
        : formatApiErrorDetail(body.detail)
    if (message) return message

    const serialized = JSON.stringify(detail)
    return serialized && serialized !== '{}' ? serialized : null
  }
  return null
}

function formatApiErrorBody(body: unknown): string | null {
  if (typeof body === 'string') return body.trim() || null
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return formatApiErrorDetail(body)
  }

  const payload = body as {
    detail?: unknown
    message?: unknown
    error?: unknown
    errors?: unknown
    title?: unknown
  }
  for (const value of [payload.detail, payload.message, payload.error, payload.errors, payload.title]) {
    const message = formatApiErrorDetail(value)
    if (message) return message
  }

  const serialized = JSON.stringify(body)
  return serialized && serialized !== '{}' ? serialized : null
}

export function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    if (error.response) {
      const detail = formatApiErrorBody(error.response.data)
      const status = error.response.status
      throw new Error(
        detail ?? `${fallback} The server returned HTTP ${status} without an error description.`,
      )
    }
    throw new Error(`The payroll API could not be reached: ${error.message || fallback}`)
  }
  throw error
}

function toEmployeeOption(employee: Employee): PayrollEmployeeOption {
  return {
    id: employee.id,
    employeeNo: employee.employee_no,
    fullName: [employee.preferred_name || employee.first_name, employee.middle_name, employee.last_name, employee.suffix]
      .filter(Boolean)
      .join(' '),
    isActive: employee.is_active && employee.record_status === 'ACTIVE',
  }
}

function toPayrollGroupOption(group: PayrollGroup): PayrollGroupOption {
  return { id: group.id, code: group.payroll_group_code, name: group.payroll_group_name }
}

function toCutoffOption(cutoff: PayrollCutoff): PayrollCutoffOption {
  return {
    id: cutoff.id,
    code: cutoff.cutoff_code,
    periodStart: cutoff.period_start,
    periodEnd: cutoff.period_end,
    locked: Boolean(cutoff.locked_at) || cutoff.status.toUpperCase() === 'LOCKED',
  }
}

function toCompensation(compensation: BackendCompensation): EmployeeCompensation {
  return {
    id: compensation.id,
    employeeId: compensation.employee_id,
    payrollGroupId: compensation.payroll_group_id,
    baseRate: toNumber(compensation.base_rate),
    currency: compensation.currency,
    effectiveFrom: compensation.effective_from,
    effectiveTo: compensation.effective_to,
    isActive: compensation.is_active,
  }
}

function toEarningRule(rule: BackendEarningRule): EarningRule {
  return { componentCode: rule.component_code, multiplier: toNumber(rule.multiplier) }
}

function toGrossPayRun(run: BackendGrossPayRun): GrossPayRun {
  return {
    id: run.id,
    cutoffId: run.cutoff_id,
    calculationVersion: run.calculation_version,
    calculatedAt: run.calculated_at,
    calculatedBy: run.calculated_by,
    results: run.results.map((result) => ({
      employeeId: result.employee_id,
      cutoffResultId: result.cutoff_result_id,
      currency: result.currency,
      baseRate: result.base_rate === null ? null : toNumber(result.base_rate),
      grossAmount: result.gross_amount === null ? null : toNumber(result.gross_amount),
      status: result.status,
      grossStatus: result.gross_status ?? result.status,
      holdReason: result.hold_reason,
      lines: result.lines.map((line) => ({
        componentCode: line.component_code,
        minutes: line.minutes,
        multiplier: toNumber(line.multiplier),
        amount: toNumber(line.amount),
      })),
      sourceMinutes: result.source_minutes,
      cashBenefitAmount: result.cash_benefit_amount == null ? 0 : toNumber(result.cash_benefit_amount),
      nonCashBenefitAmount: result.non_cash_benefit_amount == null ? 0 : toNumber(result.non_cash_benefit_amount),
      employeeBenefitDeductions: result.employee_benefit_deductions == null
        ? 0
        : toNumber(result.employee_benefit_deductions),
      exemptLimitedBenefitAmount: result.exempt_limited_benefit_amount == null
        ? null
        : toNumber(result.exempt_limited_benefit_amount),
      taxableIncome: result.taxable_income == null ? null : toNumber(result.taxable_income),
      employeeContributions: result.employee_contributions == null
        ? null
        : toNumber(result.employee_contributions),
      employerContributions: result.employer_contributions == null
        ? null
        : toNumber(result.employer_contributions),
      withholdingTax: result.withholding_tax == null ? null : toNumber(result.withholding_tax),
      netAmount: result.net_amount == null ? null : toNumber(result.net_amount),
      benefitLines: (result.benefit_lines ?? []).map((line) => ({
        benefitCode: line.benefit_code,
        benefitName: line.benefit_name,
        category: line.category,
        taxTreatment: line.tax_treatment,
        withholdingTiming: line.withholding_timing,
        amount: toNumber(line.amount),
      })),
      contributionLines: (result.contribution_lines ?? []).map((line) => ({
        programCode: line.program_code,
        employeeAmount: toNumber(line.employee_amount),
        employerAmount: toNumber(line.employer_amount),
      })),
    })),
  }
}

export class HttpPayrollRepository implements PayrollRepository {
  async listEmployees(): Promise<PayrollEmployeeOption[]> {
    return (await fetchEmployees()).map(toEmployeeOption)
  }

  listCompanyEmploymentAssignments(companyId: string): Promise<EmploymentAssignment[]> {
    return fetchEmploymentAssignments(undefined, companyId)
  }

  async listPayrollGroups(companyId: string): Promise<PayrollGroupOption[]> {
    return (await fetchPayrollGroups(companyId)).map(toPayrollGroupOption)
  }

  async listCutoffs(payrollGroupId: string): Promise<PayrollCutoffOption[]> {
    return (await fetchPayrollCutoffs(payrollGroupId)).map(toCutoffOption)
  }

  async listCompensations(
    payrollGroupId: string,
    employeeId?: string,
  ): Promise<EmployeeCompensation[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendCompensation[]>>(
        '/payroll/compensations',
        { params: { payroll_group_id: payrollGroupId, ...(employeeId ? { employee_id: employeeId } : {}) } },
      )
      return requireArray(
        response.data?.data,
        'Payroll API returned an invalid compensation list. Confirm /payroll/* is routed to the backend.',
      ).map(toCompensation)
    } catch (error) {
      return rethrowApiError(error, 'Could not load employee compensation.')
    }
  }

  async createCompensation(input: CompensationInput): Promise<EmployeeCompensation> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendCompensation>>(
        '/payroll/compensations',
        {
          employee_id: input.employeeId,
          payroll_group_id: input.payrollGroupId,
          base_rate: input.baseRate,
          currency: input.currency,
          effective_from: input.effectiveFrom,
          effective_to: input.effectiveTo,
        },
      )
      return toCompensation(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not save employee compensation.')
    }
  }

  async updateCompensation(
    compensationId: string,
    input: CompensationInput,
  ): Promise<EmployeeCompensation> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendCompensation>>(
        `/payroll/compensations/${compensationId}`,
        {
          base_rate: input.baseRate,
          currency: input.currency,
          effective_from: input.effectiveFrom,
          effective_to: input.effectiveTo,
        },
      )
      return toCompensation(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not update employee compensation.')
    }
  }

  async listEarningRules(payrollGroupId: string): Promise<EarningRule[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendEarningRule[]>>(
        '/payroll/earning-rules',
        { params: { payroll_group_id: payrollGroupId } },
      )
      return requireArray(
        response.data?.data,
        'Payroll API returned an invalid earning-rule list. Confirm /payroll/* is routed to the backend.',
      ).map(toEarningRule)
    } catch (error) {
      return rethrowApiError(error, 'Could not load payroll earning rules.')
    }
  }

  async saveEarningRule(
    payrollGroupId: string,
    componentCode: PayrollComponentCode,
    multiplier: number,
  ): Promise<EarningRule> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendEarningRule>>(
        '/payroll/earning-rules',
        { payroll_group_id: payrollGroupId, component_code: componentCode, multiplier },
      )
      return toEarningRule(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not save this earning rule.')
    }
  }

  async calculateGrossPay(cutoffId: string): Promise<GrossPayRun> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendGrossPayRun>>(
        `/payroll/cutoffs/${encodeURIComponent(cutoffId)}/calculate`,
      )
      return toGrossPayRun(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not calculate payroll.')
    }
  }

  async getCurrentGrossPayRun(cutoffId: string): Promise<GrossPayRun | null> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendGrossPayRun | null>>(
        `/payroll/cutoffs/${encodeURIComponent(cutoffId)}/gross-results`,
      )
      return response.data.data ? toGrossPayRun(response.data.data) : null
    } catch (error) {
      return rethrowApiError(error, 'Could not load gross-pay results.')
    }
  }

  async approvePayrollCutoff(cutoffId: string): Promise<void> {
    try {
      await apiClient.post(`/payroll/cutoffs/${encodeURIComponent(cutoffId)}/approve`)
    } catch (error) {
      return rethrowApiError(error, 'Could not approve payroll.')
    }
  }

  async unlockPayrollCutoff(cutoffId: string): Promise<void> {
    try {
      await apiClient.post(`/payroll/cutoffs/${encodeURIComponent(cutoffId)}/unlock`)
    } catch (error) {
      return rethrowApiError(error, 'Could not unlock payroll.')
    }
  }

  async listContributionSchedules(programCode?: StatutoryProgram): Promise<ContributionSchedule[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendContributionSchedule[]>>(
        '/payroll/statutory/contribution-schedules',
        { params: programCode ? { program_code: programCode } : undefined },
      )
      return requireArray(response.data?.data, 'Payroll API returned an invalid contribution-schedule list.')
        .map(toContributionSchedule)
    } catch (error) {
      return rethrowApiError(error, 'Could not load contribution schedules.')
    }
  }

  async getContributionSchedule(scheduleId: string): Promise<ContributionSchedule> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendContributionSchedule>>(
        `/payroll/statutory/contribution-schedules/${encodeURIComponent(scheduleId)}`,
      )
      return toContributionSchedule(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not load the contribution schedule.')
    }
  }

  async createContributionSchedule(input: ContributionScheduleInput): Promise<ContributionSchedule> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendContributionSchedule>>(
        '/payroll/statutory/contribution-schedules',
        {
          program_code: input.programCode,
          schedule_name: input.scheduleName,
          effective_from: input.effectiveFrom,
          effective_to: input.effectiveTo,
          source_reference: input.sourceReference,
        },
      )
      return toContributionSchedule(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not create the contribution schedule.')
    }
  }

  async updateContributionSchedule(
    scheduleId: string,
    input: ContributionScheduleInput,
  ): Promise<ContributionSchedule> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendContributionSchedule>>(
        `/payroll/statutory/contribution-schedules/${encodeURIComponent(scheduleId)}`,
        {
          program_code: input.programCode,
          schedule_name: input.scheduleName,
          effective_from: input.effectiveFrom,
          effective_to: input.effectiveTo,
          source_reference: input.sourceReference,
        },
      )
      return toContributionSchedule(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not update the contribution schedule.')
    }
  }

  async deleteContributionSchedule(scheduleId: string): Promise<void> {
    try {
      await apiClient.delete(`/payroll/statutory/contribution-schedules/${encodeURIComponent(scheduleId)}`)
    } catch (error) {
      return rethrowApiError(error, 'Could not delete the contribution schedule.')
    }
  }

  async activateContributionSchedule(scheduleId: string): Promise<ContributionSchedule> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendContributionSchedule>>(
        `/payroll/statutory/contribution-schedules/${encodeURIComponent(scheduleId)}/activate`,
      )
      return toContributionSchedule(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not activate the contribution schedule.')
    }
  }

  async retireContributionSchedule(scheduleId: string): Promise<ContributionSchedule> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendContributionSchedule>>(
        `/payroll/statutory/contribution-schedules/${encodeURIComponent(scheduleId)}/retire`,
      )
      return toContributionSchedule(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not retire the contribution schedule.')
    }
  }

  async listContributionBrackets(scheduleId: string): Promise<ContributionBracket[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendContributionBracket[]>>(
        `/payroll/statutory/contribution-schedules/${encodeURIComponent(scheduleId)}/brackets`,
      )
      return requireArray(response.data?.data, 'Payroll API returned an invalid contribution-bracket list.')
        .map(toContributionBracket)
    } catch (error) {
      return rethrowApiError(error, 'Could not load contribution brackets.')
    }
  }

  async getContributionBracket(bracketId: string): Promise<ContributionBracket> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendContributionBracket>>(
        `/payroll/statutory/contribution-brackets/${encodeURIComponent(bracketId)}`,
      )
      return toContributionBracket(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not load the contribution bracket.')
    }
  }

  async createContributionBracket(
    scheduleId: string,
    input: ContributionBracketInput,
  ): Promise<ContributionBracket> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendContributionBracket>>(
        `/payroll/statutory/contribution-schedules/${encodeURIComponent(scheduleId)}/brackets`,
        toBackendContributionBracket(input),
      )
      return toContributionBracket(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not create the contribution bracket.')
    }
  }

  async updateContributionBracket(
    bracketId: string,
    input: ContributionBracketInput,
  ): Promise<ContributionBracket> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendContributionBracket>>(
        `/payroll/statutory/contribution-brackets/${encodeURIComponent(bracketId)}`,
        toBackendContributionBracket(input),
      )
      return toContributionBracket(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not update the contribution bracket.')
    }
  }

  async deleteContributionBracket(bracketId: string): Promise<void> {
    try {
      await apiClient.delete(`/payroll/statutory/contribution-brackets/${encodeURIComponent(bracketId)}`)
    } catch (error) {
      return rethrowApiError(error, 'Could not delete the contribution bracket.')
    }
  }

  async listWithholdingTaxSchedules(): Promise<WithholdingTaxSchedule[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendTaxSchedule[]>>(
        '/payroll/statutory/withholding-tax-schedules',
      )
      return requireArray(response.data?.data, 'Payroll API returned an invalid withholding-tax schedule list.')
        .map(toWithholdingTaxSchedule)
    } catch (error) {
      return rethrowApiError(error, 'Could not load withholding-tax schedules.')
    }
  }

  async getPayrollSystemParameters(companyId: string): Promise<PayrollSystemParameters> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendPayrollSystemParameters>>(
        '/payroll/system-parameters',
        { params: { company_id: companyId } },
      )
      return {
        yearEndWtaxReconciliationEnabled:
          response.data.data.year_end_wtax_reconciliation_enabled,
        thirteenthMonthEnabled: response.data.data.thirteenth_month_enabled,
        scheduleAssignmentApprovalRequired:
          response.data.data.schedule_assignment_approval_required,
        statutoryContributionTiming: response.data.data.statutory_contribution_timing,
      }
    } catch (error) {
      return rethrowApiError(error, 'Could not load payroll system parameters.')
    }
  }

  async updatePayrollSystemParameters(
    companyId: string,
    parameters: PayrollSystemParameters,
  ): Promise<PayrollSystemParameters> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendPayrollSystemParameters>>(
        '/payroll/system-parameters',
        {
          year_end_wtax_reconciliation_enabled:
            parameters.yearEndWtaxReconciliationEnabled,
          thirteenth_month_enabled: parameters.thirteenthMonthEnabled,
          schedule_assignment_approval_required:
            parameters.scheduleAssignmentApprovalRequired,
          statutory_contribution_timing: parameters.statutoryContributionTiming,
        },
        { params: { company_id: companyId } },
      )
      return {
        yearEndWtaxReconciliationEnabled:
          response.data.data.year_end_wtax_reconciliation_enabled,
        thirteenthMonthEnabled: response.data.data.thirteenth_month_enabled,
        scheduleAssignmentApprovalRequired:
          response.data.data.schedule_assignment_approval_required,
        statutoryContributionTiming: response.data.data.statutory_contribution_timing,
      }
    } catch (error) {
      return rethrowApiError(error, 'Could not update payroll system parameters.')
    }
  }

  async calculateThirteenthMonth(
    companyId: string,
    taxYear: number,
    coveredPeriodFrom: string,
    coveredPeriodTo: string,
  ): Promise<ThirteenthMonthRun> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendThirteenthMonthRun>>(
        '/payroll/thirteenth-month-runs/calculate',
        {
          company_id: companyId,
          tax_year: taxYear,
          covered_period_from: coveredPeriodFrom,
          covered_period_to: coveredPeriodTo,
        },
      )
      const run = response.data.data
      return {
        id: run.id,
        taxYear: run.tax_year,
        coveredPeriodFrom: run.covered_period_from,
        coveredPeriodTo: run.covered_period_to,
        calculatedAt: run.calculated_at,
        results: requireArray(
          run.results,
          'Payroll API returned an invalid 13th-month calculation.',
        ).map((result) => ({
          employeeId: result.employee_id,
          employeeNo: result.employee_no,
          employeeName: result.employee_name,
          basicSalaryEarned: Number(result.basic_salary_earned),
          thirteenthMonthPay: Number(result.thirteenth_month_pay),
          taxExemptAmount: Number(result.tax_exempt_amount),
          taxableAmount: Number(result.taxable_amount),
          sourcePayrollPeriods: result.source_payroll_periods,
        })),
      }
    } catch (error) {
      return rethrowApiError(error, 'Could not calculate 13th-month pay.')
    }
  }

  async getWithholdingTaxSchedule(scheduleId: string): Promise<WithholdingTaxSchedule> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendTaxSchedule>>(
        `/payroll/statutory/withholding-tax-schedules/${encodeURIComponent(scheduleId)}`,
      )
      return toWithholdingTaxSchedule(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not load the withholding-tax schedule.')
    }
  }

  async createWithholdingTaxSchedule(input: WithholdingTaxScheduleInput): Promise<WithholdingTaxSchedule> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendTaxSchedule>>(
        '/payroll/statutory/withholding-tax-schedules',
        {
          schedule_name: input.scheduleName,
          effective_from: input.effectiveFrom,
          effective_to: input.effectiveTo,
          tax_exempt_benefit_limit: input.taxExemptBenefitLimit,
          calculation_basis: input.calculationBasis,
          source_reference: input.sourceReference,
        },
      )
      return toWithholdingTaxSchedule(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not create the withholding-tax schedule.')
    }
  }

  async updateWithholdingTaxSchedule(
    scheduleId: string,
    input: WithholdingTaxScheduleInput,
  ): Promise<WithholdingTaxSchedule> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendTaxSchedule>>(
        `/payroll/statutory/withholding-tax-schedules/${encodeURIComponent(scheduleId)}`,
        {
          schedule_name: input.scheduleName,
          effective_from: input.effectiveFrom,
          effective_to: input.effectiveTo,
          tax_exempt_benefit_limit: input.taxExemptBenefitLimit,
          calculation_basis: input.calculationBasis,
          source_reference: input.sourceReference,
        },
      )
      return toWithholdingTaxSchedule(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not update the withholding-tax schedule.')
    }
  }

  async deleteWithholdingTaxSchedule(scheduleId: string): Promise<void> {
    try {
      await apiClient.delete(`/payroll/statutory/withholding-tax-schedules/${encodeURIComponent(scheduleId)}`)
    } catch (error) {
      return rethrowApiError(error, 'Could not delete the withholding-tax schedule.')
    }
  }

  async activateWithholdingTaxSchedule(scheduleId: string): Promise<WithholdingTaxSchedule> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendTaxSchedule>>(
        `/payroll/statutory/withholding-tax-schedules/${encodeURIComponent(scheduleId)}/activate`,
      )
      return toWithholdingTaxSchedule(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not activate the withholding-tax schedule.')
    }
  }

  async retireWithholdingTaxSchedule(scheduleId: string): Promise<WithholdingTaxSchedule> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendTaxSchedule>>(
        `/payroll/statutory/withholding-tax-schedules/${encodeURIComponent(scheduleId)}/retire`,
      )
      return toWithholdingTaxSchedule(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not retire the withholding-tax schedule.')
    }
  }

  async listWithholdingTaxBrackets(scheduleId: string): Promise<WithholdingTaxBracket[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendTaxBracket[]>>(
        `/payroll/statutory/withholding-tax-schedules/${encodeURIComponent(scheduleId)}/brackets`,
      )
      return requireArray(response.data?.data, 'Payroll API returned an invalid withholding-tax bracket list.')
        .map(toWithholdingTaxBracket)
    } catch (error) {
      return rethrowApiError(error, 'Could not load withholding-tax brackets.')
    }
  }

  async getWithholdingTaxBracket(bracketId: string): Promise<WithholdingTaxBracket> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendTaxBracket>>(
        `/payroll/statutory/withholding-tax-brackets/${encodeURIComponent(bracketId)}`,
      )
      return toWithholdingTaxBracket(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not load the withholding-tax bracket.')
    }
  }

  async createWithholdingTaxBracket(
    scheduleId: string,
    input: WithholdingTaxBracketInput,
  ): Promise<WithholdingTaxBracket> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendTaxBracket>>(
        `/payroll/statutory/withholding-tax-schedules/${encodeURIComponent(scheduleId)}/brackets`,
        toBackendTaxBracket(input),
      )
      return toWithholdingTaxBracket(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not create the withholding-tax bracket.')
    }
  }

  async updateWithholdingTaxBracket(
    bracketId: string,
    input: WithholdingTaxBracketInput,
  ): Promise<WithholdingTaxBracket> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendTaxBracket>>(
        `/payroll/statutory/withholding-tax-brackets/${encodeURIComponent(bracketId)}`,
        toBackendTaxBracket(input),
      )
      return toWithholdingTaxBracket(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not update the withholding-tax bracket.')
    }
  }

  async deleteWithholdingTaxBracket(bracketId: string): Promise<void> {
    try {
      await apiClient.delete(`/payroll/statutory/withholding-tax-brackets/${encodeURIComponent(bracketId)}`)
    } catch (error) {
      return rethrowApiError(error, 'Could not delete the withholding-tax bracket.')
    }
  }

  async listBenefitTypes(payrollGroupId: string): Promise<BenefitType[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendBenefitType[]>>(
        '/payroll/benefits/types',
        { params: { payroll_group_id: payrollGroupId } },
      )
      return requireArray(response.data?.data, 'Payroll API returned an invalid benefit-type list.')
        .map(toBenefitType)
    } catch (error) {
      return rethrowApiError(error, 'Could not load benefit types.')
    }
  }

  async createBenefitType(input: BenefitTypeInput): Promise<BenefitType> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendBenefitType>>(
        '/payroll/benefits/types',
        {
          payroll_group_id: input.payrollGroupId,
          code: input.code,
          name: input.name,
          category: input.category,
          tax_treatment: input.taxTreatment,
          withholding_timing: input.withholdingTiming,
          attendance_based: input.attendanceBased,
          deduct_for_late: input.deductForLate,
          deduct_for_undertime: input.deductForUndertime,
          posting_schedule: input.postingSchedule,
        },
      )
      return toBenefitType(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not create the benefit type.')
    }
  }

  async updateBenefitType(
    benefitTypeId: string,
    input: BenefitTypeInput,
  ): Promise<BenefitType> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendBenefitType>>(
        `/payroll/benefits/types/${encodeURIComponent(benefitTypeId)}`,
        {
          payroll_group_id: input.payrollGroupId,
          code: input.code,
          name: input.name,
          category: input.category,
          tax_treatment: input.taxTreatment,
          withholding_timing: input.withholdingTiming,
          attendance_based: input.attendanceBased,
          deduct_for_late: input.deductForLate,
          deduct_for_undertime: input.deductForUndertime,
          posting_schedule: input.postingSchedule,
        },
      )
      return toBenefitType(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not update the benefit type.')
    }
  }

  async setBenefitTypeActive(benefitTypeId: string, isActive: boolean): Promise<BenefitType> {
    try {
      const action = isActive ? 'activate' : 'deactivate'
      const response = await apiClient.post<ApiSuccessEnvelope<BackendBenefitType>>(
        `/payroll/benefits/types/${encodeURIComponent(benefitTypeId)}/${action}`,
      )
      return toBenefitType(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not change the benefit type status.')
    }
  }

  async listEmployeeBenefitEntitlements(
    payrollGroupId: string,
  ): Promise<EmployeeBenefitEntitlement[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendEmployeeBenefitEntitlement[]>>(
        '/payroll/benefits/entitlements',
        { params: { payroll_group_id: payrollGroupId } },
      )
      return requireArray(
        response.data?.data,
        'Payroll API returned an invalid benefit-entitlement list.',
      ).map(toEmployeeBenefitEntitlement)
    } catch (error) {
      return rethrowApiError(error, 'Could not load employee benefit entitlements.')
    }
  }

  async createEmployeeBenefitEntitlement(
    input: EmployeeBenefitEntitlementInput,
  ): Promise<EmployeeBenefitEntitlement> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendEmployeeBenefitEntitlement>>(
        '/payroll/benefits/entitlements',
        {
          employee_id: input.employeeId,
          benefit_type_id: input.benefitTypeId,
          amount_per_occurrence: input.amountPerOccurrence,
          schedule: input.schedule,
          effective_from: input.effectiveFrom,
          effective_to: input.effectiveTo,
        },
      )
      return toEmployeeBenefitEntitlement(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not create the employee benefit entitlement.')
    }
  }

  async updateEmployeeBenefitEntitlement(
    entitlementId: string,
    input: EmployeeBenefitEntitlementInput,
  ): Promise<EmployeeBenefitEntitlement> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendEmployeeBenefitEntitlement>>(
        `/payroll/benefits/entitlements/${encodeURIComponent(entitlementId)}`,
        {
          employee_id: input.employeeId,
          benefit_type_id: input.benefitTypeId,
          amount_per_occurrence: input.amountPerOccurrence,
          schedule: input.schedule,
          effective_from: input.effectiveFrom,
          effective_to: input.effectiveTo,
        },
      )
      return toEmployeeBenefitEntitlement(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not update the employee benefit entitlement.')
    }
  }

  async setEmployeeBenefitEntitlementActive(
    entitlementId: string,
    isActive: boolean,
  ): Promise<EmployeeBenefitEntitlement> {
    try {
      const action = isActive ? 'activate' : 'deactivate'
      const response = await apiClient.post<ApiSuccessEnvelope<BackendEmployeeBenefitEntitlement>>(
        `/payroll/benefits/entitlements/${encodeURIComponent(entitlementId)}/${action}`,
      )
      return toEmployeeBenefitEntitlement(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not change the employee benefit entitlement status.')
    }
  }

  async listCutoffBenefits(cutoffId: string): Promise<CutoffBenefit[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendCutoffBenefit[]>>(
        `/payroll/benefits/cutoffs/${encodeURIComponent(cutoffId)}`,
      )
      return requireArray(response.data?.data, 'Payroll API returned an invalid cutoff benefit list.')
        .map(toCutoffBenefit)
    } catch (error) {
      return rethrowApiError(error, 'Could not load cutoff benefits.')
    }
  }

  async createCutoffBenefit(input: CutoffBenefitInput): Promise<CutoffBenefit> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendCutoffBenefit>>(
        `/payroll/benefits/cutoffs/${encodeURIComponent(input.cutoffId)}`,
        {
          cutoff_id: input.cutoffId,
          employee_id: input.employeeId,
          benefit_type_id: input.benefitTypeId,
          amount: input.amount,
          notes: input.notes,
        },
      )
      return toCutoffBenefit(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not create the cutoff benefit entry.')
    }
  }

  async updateCutoffBenefit(
    entryId: string,
    input: CutoffBenefitInput,
  ): Promise<CutoffBenefit> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendCutoffBenefit>>(
        `/payroll/benefits/entries/${encodeURIComponent(entryId)}`,
        {
          cutoff_id: input.cutoffId,
          employee_id: input.employeeId,
          benefit_type_id: input.benefitTypeId,
          amount: input.amount,
          notes: input.notes,
        },
      )
      return toCutoffBenefit(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not update the cutoff benefit entry.')
    }
  }

  async uploadCutoffBenefits(
    cutoffId: string,
    rows: CutoffBenefitUploadRow[],
  ): Promise<CutoffBenefitUploadResult> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<CutoffBenefitUploadResult>>(
        `/payroll/benefits/cutoffs/${encodeURIComponent(cutoffId)}/upload`,
        {
          rows: rows.map((row) => ({
            employee_no: row.employeeNo,
            benefit_code: row.benefitCode,
            amount: row.amount,
            notes: row.notes,
          })),
        },
      )
      return response.data.data
    } catch (error) {
      return rethrowApiError(error, 'Could not upload cutoff benefits.')
    }
  }

  async uploadCutoffDeductions(
    cutoffId: string,
    rows: CutoffBenefitUploadRow[],
  ): Promise<CutoffBenefitUploadResult> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<CutoffBenefitUploadResult>>(
        `/payroll/benefits/cutoffs/${encodeURIComponent(cutoffId)}/deductions/upload`,
        {
          rows: rows.map((row) => ({
            employee_no: row.employeeNo,
            deduction_code: row.benefitCode,
            amount: row.amount,
            notes: row.notes,
          })),
        },
      )
      return response.data.data
    } catch (error) {
      return rethrowApiError(error, 'Could not upload cutoff deductions.')
    }
  }

  async deleteCutoffBenefit(entryId: string): Promise<void> {
    try {
      await apiClient.delete(`/payroll/benefits/entries/${encodeURIComponent(entryId)}`)
    } catch (error) {
      return rethrowApiError(error, 'Could not delete the cutoff benefit entry.')
    }
  }

  async listEmployeeBenefitDeductions(
    payrollGroupId: string,
  ): Promise<EmployeeBenefitDeduction[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendEmployeeBenefitDeduction[]>>(
        '/payroll/benefits/deductions',
        { params: { payroll_group_id: payrollGroupId } },
      )
      return requireArray(
        response.data?.data,
        'Payroll API returned an invalid recurring-deduction list.',
      ).map(toEmployeeBenefitDeduction)
    } catch (error) {
      return rethrowApiError(error, 'Could not load recurring employee deductions.')
    }
  }

  async createEmployeeBenefitDeduction(
    input: EmployeeBenefitDeductionInput,
  ): Promise<EmployeeBenefitDeduction> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendEmployeeBenefitDeduction>>(
        '/payroll/benefits/deductions',
        {
          employee_id: input.employeeId,
          benefit_type_id: input.benefitTypeId,
          amount_per_occurrence: input.amountPerOccurrence,
          schedule: input.schedule,
          effective_from: input.effectiveFrom,
          effective_to: input.effectiveTo,
        },
      )
      return toEmployeeBenefitDeduction(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not create the recurring employee deduction.')
    }
  }

  async updateEmployeeBenefitDeduction(
    deductionId: string,
    input: EmployeeBenefitDeductionInput,
  ): Promise<EmployeeBenefitDeduction> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendEmployeeBenefitDeduction>>(
        `/payroll/benefits/deductions/${encodeURIComponent(deductionId)}`,
        {
          employee_id: input.employeeId,
          benefit_type_id: input.benefitTypeId,
          amount_per_occurrence: input.amountPerOccurrence,
          schedule: input.schedule,
          effective_from: input.effectiveFrom,
          effective_to: input.effectiveTo,
        },
      )
      return toEmployeeBenefitDeduction(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not update the recurring employee deduction.')
    }
  }

  async setEmployeeBenefitDeductionActive(
    deductionId: string,
    isActive: boolean,
  ): Promise<EmployeeBenefitDeduction> {
    try {
      const action = isActive ? 'activate' : 'deactivate'
      const response = await apiClient.post<ApiSuccessEnvelope<BackendEmployeeBenefitDeduction>>(
        `/payroll/benefits/deductions/${encodeURIComponent(deductionId)}/${action}`,
      )
      return toEmployeeBenefitDeduction(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not change the recurring deduction status.')
    }
  }

  async listEmployeeLoans(payrollGroupId: string): Promise<EmployeeLoan[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendEmployeeLoan[]>>(
        '/payroll/loans',
        { params: { payroll_group_id: payrollGroupId } },
      )
      return requireArray(response.data?.data, 'Payroll API returned an invalid employee-loan list.')
        .map(toEmployeeLoan)
    } catch (error) {
      return rethrowApiError(error, 'Could not load employee loans.')
    }
  }

  async createEmployeeLoan(input: EmployeeLoanInput): Promise<EmployeeLoan> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendEmployeeLoan>>(
        '/payroll/loans',
        {
          employee_id: input.employeeId,
          payroll_group_id: input.payrollGroupId,
          reference_number: input.referenceNumber,
          principal_amount: input.principalAmount,
          installment_amount: input.installmentAmount,
          schedule: input.schedule,
          effective_from: input.effectiveFrom,
        },
      )
      return toEmployeeLoan(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not create the employee loan.')
    }
  }

  async retireEmployeeLoan(loanId: string): Promise<EmployeeLoan> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendEmployeeLoan>>(
        `/payroll/loans/${encodeURIComponent(loanId)}/retire`,
      )
      return toEmployeeLoan(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not retire the employee loan.')
    }
  }

  async restructureEmployeeLoan(
    loanId: string,
    input: EmployeeLoanRestructureInput,
  ): Promise<EmployeeLoan> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendEmployeeLoan>>(
        `/payroll/loans/${encodeURIComponent(loanId)}/restructure`,
        {
          reference_number: input.referenceNumber,
          additional_principal: input.additionalPrincipal,
          installment_amount: input.installmentAmount,
          schedule: input.schedule,
          effective_from: input.effectiveFrom,
        },
      )
      return toEmployeeLoan(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not restructure the employee loan.')
    }
  }

  async getEmployeeYtdTaxBalance(
    employeeId: string,
    taxYear: number,
  ): Promise<EmployeeYtdTaxBalance | null> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendYtdTaxBalance | null>>(
        '/payroll/benefits/ytd-balances',
        { params: { employee_id: employeeId, tax_year: taxYear } },
      )
      return response.data.data ? toYtdTaxBalance(response.data.data) : null
    } catch (error) {
      return rethrowApiError(error, 'Could not load employee tax-year opening balances.')
    }
  }

  async saveEmployeeYtdTaxBalance(
    balance: EmployeeYtdTaxBalance,
  ): Promise<EmployeeYtdTaxBalance> {
    try {
      const response = await apiClient.put<ApiSuccessEnvelope<BackendYtdTaxBalance>>(
        '/payroll/benefits/ytd-balances',
        {
          employee_id: balance.employeeId,
          tax_year: balance.taxYear,
          taxable_income: balance.taxableIncome,
          tax_withheld: balance.taxWithheld,
          exempt_limited_benefits: balance.exemptLimitedBenefits,
        },
      )
      return toYtdTaxBalance(response.data.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not save employee tax-year opening balances.')
    }
  }
}
