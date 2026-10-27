import type {
  BenefitCategory,
  BenefitTaxTreatment,
  BenefitType,
  BenefitWithholdingTiming,
} from './payroll'

export type OffCycleRunType = 'BENEFIT' | 'THIRTEENTH_MONTH'
export type OffCycleRunStatus = 'DRAFT' | 'PENDING' | 'APPROVED' | 'PAID' | 'REJECTED'
export type OffCycleRunAction =
  | 'RECALCULATE'
  | 'SUBMIT'
  | 'APPROVE'
  | 'REJECT'
  | 'MARK_PAID'
  | 'DELETE'

export const OFF_CYCLE_CASH_CATEGORIES: readonly BenefitCategory[] = [
  'ONE_TIME_BONUS',
  'CASH_ALLOWANCE',
  'REIMBURSEMENT',
]

// Mirrors backend OFF_CYCLE_ALLOWED_STATUSES so the UI only offers valid transitions.
const allowedStatuses: Record<OffCycleRunAction, readonly OffCycleRunStatus[]> = {
  RECALCULATE: ['DRAFT'],
  SUBMIT: ['DRAFT'],
  APPROVE: ['PENDING'],
  REJECT: ['PENDING', 'APPROVED'],
  MARK_PAID: ['APPROVED'],
  DELETE: ['DRAFT', 'REJECTED'],
}

export function isOffCycleActionAllowed(status: OffCycleRunStatus, action: OffCycleRunAction): boolean {
  return allowedStatuses[action].includes(status)
}

export function isOffCycleBenefitType(benefitType: BenefitType): boolean {
  return benefitType.isActive && OFF_CYCLE_CASH_CATEGORIES.includes(benefitType.category)
}

export function isThirteenthMonthBenefitType(benefitType: BenefitType): boolean {
  return (
    benefitType.isActive
    && benefitType.category === 'ONE_TIME_BONUS'
    && benefitType.taxTreatment === 'EXEMPT_LIMITED'
  )
}

export interface OffCyclePayrollLine {
  id: string
  employeeId: string
  employeeNo: string
  employeeName: string
  benefitCode: string
  benefitName: string
  category: BenefitCategory
  taxTreatment: BenefitTaxTreatment
  withholdingTiming: BenefitWithholdingTiming
  amount: number
  taxableAmount: number
  exemptLimitedAmount: number
  withholdingTax: number
  netAmount: number
  notes: string | null
  thirteenthMonthResultId: string | null
}

export interface OffCyclePayrollRun {
  id: string
  companyId: string
  payrollGroupId: string
  benefitTypeId: string
  benefitCode: string
  benefitName: string
  runType: OffCycleRunType
  status: OffCycleRunStatus
  proposedPaymentDate: string
  actualPaymentDate: string | null
  notes: string | null
  rejectionReason: string | null
  createdBy: string
  createdAt: string
  submittedAt: string | null
  approvedBy: string | null
  approvedAt: string | null
  paidBy: string | null
  paidAt: string | null
  thirteenthMonthRunId: string | null
  employeeCount: number
  totalAmount: number
  totalWithholdingTax: number
  totalNetAmount: number
  lines: OffCyclePayrollLine[]
}

export interface OffCycleUploadRow {
  rowNumber: number
  employeeNo: string
  amount: number
  notes: string
}

export interface OffCycleBenefitRunInput {
  payrollGroupId: string
  benefitTypeId: string
  proposedPaymentDate: string
  notes: string
  rows: OffCycleUploadRow[]
}

export interface OffCycleThirteenthMonthRunInput {
  payrollGroupId: string
  benefitTypeId: string
  thirteenthMonthRunId: string
  proposedPaymentDate: string
  notes: string
}

export interface ThirteenthMonthSource {
  id: string
  taxYear: number
  coveredPeriodFrom: string | null
  coveredPeriodTo: string | null
  calculatedAt: string
  resultCount: number
}
