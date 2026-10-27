import { apiClient } from '../../../lib/apiClient'
import type { ApiSuccessEnvelope } from '../../../types/auth'
import type { OffCycleRunFilter, OffCyclePayrollRepository } from '../application/offCyclePorts'
import type {
  OffCycleBenefitRunInput,
  OffCyclePayrollLine,
  OffCyclePayrollRun,
  OffCycleThirteenthMonthRunInput,
  ThirteenthMonthSource,
} from '../domain/offCycle'
import { requireArray, rethrowApiError, toNumber } from './HttpPayrollRepository'

type Money = number | string

interface BackendOffCycleLine {
  id: string
  employee_id: string
  employee_no: string
  employee_name: string
  benefit_code: string
  benefit_name: string
  category: OffCyclePayrollLine['category']
  tax_treatment: OffCyclePayrollLine['taxTreatment']
  withholding_timing: OffCyclePayrollLine['withholdingTiming']
  amount: Money
  taxable_amount: Money
  exempt_limited_amount: Money
  withholding_tax: Money
  net_amount: Money
  notes: string | null
  thirteenth_month_result_id: string | null
}

interface BackendOffCycleRun {
  id: string
  company_id: string
  payroll_group_id: string
  benefit_type_id: string
  benefit_code: string
  benefit_name: string
  run_type: OffCyclePayrollRun['runType']
  status: OffCyclePayrollRun['status']
  proposed_payment_date: string
  actual_payment_date: string | null
  notes: string | null
  rejection_reason: string | null
  created_by: string
  created_at: string
  submitted_at: string | null
  approved_by: string | null
  approved_at: string | null
  paid_by: string | null
  paid_at: string | null
  thirteenth_month_run_id: string | null
  employee_count: number
  total_amount: Money
  total_withholding_tax: Money
  total_net_amount: Money
  lines: BackendOffCycleLine[]
}

interface BackendThirteenthMonthSource {
  id: string
  tax_year: number
  covered_period_from: string | null
  covered_period_to: string | null
  calculated_at: string
  result_count: number
}

const BASE_PATH = '/payroll/off-cycle-runs'

function runPath(runId: string, action?: string): string {
  const path = `${BASE_PATH}/${encodeURIComponent(runId)}`
  return action ? `${path}/${action}` : path
}

function toLine(value: BackendOffCycleLine): OffCyclePayrollLine {
  return {
    id: value.id,
    employeeId: value.employee_id,
    employeeNo: value.employee_no,
    employeeName: value.employee_name,
    benefitCode: value.benefit_code,
    benefitName: value.benefit_name,
    category: value.category,
    taxTreatment: value.tax_treatment,
    withholdingTiming: value.withholding_timing,
    amount: toNumber(value.amount),
    taxableAmount: toNumber(value.taxable_amount),
    exemptLimitedAmount: toNumber(value.exempt_limited_amount),
    withholdingTax: toNumber(value.withholding_tax),
    netAmount: toNumber(value.net_amount),
    notes: value.notes,
    thirteenthMonthResultId: value.thirteenth_month_result_id,
  }
}

function toRun(value: BackendOffCycleRun | undefined): OffCyclePayrollRun {
  if (!value?.id) throw new Error('Payroll API returned an invalid off-cycle run.')
  return {
    id: value.id,
    companyId: value.company_id,
    payrollGroupId: value.payroll_group_id,
    benefitTypeId: value.benefit_type_id,
    benefitCode: value.benefit_code,
    benefitName: value.benefit_name,
    runType: value.run_type,
    status: value.status,
    proposedPaymentDate: value.proposed_payment_date,
    actualPaymentDate: value.actual_payment_date,
    notes: value.notes,
    rejectionReason: value.rejection_reason,
    createdBy: value.created_by,
    createdAt: value.created_at,
    submittedAt: value.submitted_at,
    approvedBy: value.approved_by,
    approvedAt: value.approved_at,
    paidBy: value.paid_by,
    paidAt: value.paid_at,
    thirteenthMonthRunId: value.thirteenth_month_run_id,
    employeeCount: value.employee_count,
    totalAmount: toNumber(value.total_amount),
    totalWithholdingTax: toNumber(value.total_withholding_tax),
    totalNetAmount: toNumber(value.total_net_amount),
    lines: requireArray(value.lines, 'Payroll API returned invalid off-cycle lines.').map(toLine),
  }
}

export class HttpOffCyclePayrollRepository implements OffCyclePayrollRepository {
  async listRuns(filter: OffCycleRunFilter): Promise<OffCyclePayrollRun[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendOffCycleRun[]>>(BASE_PATH, {
        params: {
          company_id: filter.companyId,
          payroll_group_id: filter.payrollGroupId || undefined,
          status: filter.status || undefined,
        },
      })
      return requireArray(response.data?.data, 'Payroll API returned an invalid off-cycle run list.').map(toRun)
    } catch (error) {
      return rethrowApiError(error, 'Could not load off-cycle payroll runs.')
    }
  }

  async getRun(runId: string): Promise<OffCyclePayrollRun> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendOffCycleRun>>(runPath(runId))
      return toRun(response.data?.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not load the off-cycle payroll run.')
    }
  }

  async listThirteenthMonthSources(payrollGroupId: string): Promise<ThirteenthMonthSource[]> {
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<BackendThirteenthMonthSource[]>>(
        `${BASE_PATH}/thirteenth-month-sources`,
        { params: { payroll_group_id: payrollGroupId } },
      )
      return requireArray(response.data?.data, 'Payroll API returned an invalid 13th-month list.').map((item) => ({
        id: item.id,
        taxYear: item.tax_year,
        coveredPeriodFrom: item.covered_period_from,
        coveredPeriodTo: item.covered_period_to,
        calculatedAt: item.calculated_at,
        resultCount: item.result_count,
      }))
    } catch (error) {
      return rethrowApiError(error, 'Could not load 13th-month calculations.')
    }
  }

  async createBenefitRun(input: OffCycleBenefitRunInput): Promise<OffCyclePayrollRun> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendOffCycleRun>>(BASE_PATH, {
        payroll_group_id: input.payrollGroupId,
        benefit_type_id: input.benefitTypeId,
        proposed_payment_date: input.proposedPaymentDate,
        notes: input.notes.trim() || null,
        rows: input.rows.map((row) => ({
          employee_no: row.employeeNo,
          amount: row.amount.toFixed(2),
          notes: row.notes || null,
        })),
      })
      return toRun(response.data?.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not create the off-cycle payroll run.')
    }
  }

  async createThirteenthMonthRun(input: OffCycleThirteenthMonthRunInput): Promise<OffCyclePayrollRun> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendOffCycleRun>>(
        `${BASE_PATH}/thirteenth-month`,
        {
          payroll_group_id: input.payrollGroupId,
          benefit_type_id: input.benefitTypeId,
          thirteenth_month_run_id: input.thirteenthMonthRunId,
          proposed_payment_date: input.proposedPaymentDate,
          notes: input.notes.trim() || null,
        },
      )
      return toRun(response.data?.data)
    } catch (error) {
      return rethrowApiError(error, 'Could not create the 13th-month off-cycle run.')
    }
  }

  recalculateRun(runId: string): Promise<OffCyclePayrollRun> {
    return this.postAction(runId, 'recalculate', undefined, 'Could not recalculate the off-cycle run.')
  }

  submitRun(runId: string): Promise<OffCyclePayrollRun> {
    return this.postAction(runId, 'submit', undefined, 'Could not submit the off-cycle run.')
  }

  approveRun(runId: string): Promise<OffCyclePayrollRun> {
    return this.postAction(runId, 'approve', undefined, 'Could not approve the off-cycle run.')
  }

  rejectRun(runId: string, reason: string): Promise<OffCyclePayrollRun> {
    return this.postAction(runId, 'reject', { reason }, 'Could not reject the off-cycle run.')
  }

  markRunPaid(runId: string, actualPaymentDate: string): Promise<OffCyclePayrollRun> {
    return this.postAction(
      runId,
      'mark-paid',
      { actual_payment_date: actualPaymentDate },
      'Could not mark the off-cycle run as paid.',
    )
  }

  async deleteRun(runId: string): Promise<void> {
    try {
      await apiClient.delete(runPath(runId))
    } catch (error) {
      rethrowApiError(error, 'Could not delete the off-cycle run.')
    }
  }

  private async postAction(
    runId: string,
    action: string,
    body: object | undefined,
    fallback: string,
  ): Promise<OffCyclePayrollRun> {
    try {
      const response = await apiClient.post<ApiSuccessEnvelope<BackendOffCycleRun>>(runPath(runId, action), body)
      return toRun(response.data?.data)
    } catch (error) {
      return rethrowApiError(error, fallback)
    }
  }
}
