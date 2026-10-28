export type PayrollComponentCode =
  | 'REGULAR'
  | 'PAID_LEAVE'
  | 'OFFICIAL_BUSINESS'
  | 'REST_DAY'
  | 'SPECIAL_DAY'
  | 'HOLIDAY'
  | 'ORDINARY_OT'
  | 'REST_DAY_OT'
  | 'SPECIAL_DAY_OT'
  | 'HOLIDAY_OT'
  | 'NIGHT_REGULAR'
  | 'NIGHT_OT'

export interface PayrollEmployeeOption {
  id: string
  employeeNo: string
  fullName: string
  isActive: boolean
}

export interface PayrollGroupOption {
  id: string
  code: string
  name: string
}

export interface PayrollCutoffOption {
  id: string
  code: string
  periodStart: string
  periodEnd: string
  locked: boolean
  attendanceFinalized?: boolean
}

export interface EmployeeCompensation {
  id: string
  employeeId: string
  payrollGroupId: string
  baseRate: number
  currency: string
  effectiveFrom: string
  effectiveTo: string | null
  isActive: boolean
}

export interface EarningRule {
  componentCode: PayrollComponentCode
  multiplier: number
}

export interface GrossPayLine {
  componentCode: PayrollComponentCode | 'MONTHLY_BASE' | 'UNPAID_TIME_DEDUCTION'
  minutes: number
  multiplier: number
  amount: number
}

export interface GrossPayResult {
  employeeId: string
  cutoffResultId: string
  currency: string | null
  baseRate: number | null
  grossAmount: number | null
  status: 'HOLD' | 'READY'
  grossStatus: 'HOLD' | 'READY'
  holdReason: string | null
  lines: GrossPayLine[]
  sourceMinutes: Record<string, number>
  cashBenefitAmount: number
  nonCashBenefitAmount: number
  employeeBenefitDeductions: number
  exemptLimitedBenefitAmount: number | null
  taxableIncome: number | null
  employeeContributions: number | null
  employerContributions: number | null
  withholdingTax: number | null
  netAmount: number | null
  benefitLines: PayrollBenefitLine[]
  contributionLines: PayrollContributionLine[]
}

export interface PayrollBenefitLine {
  benefitCode: string
  benefitName: string
  category: BenefitCategory
  taxTreatment: BenefitTaxTreatment
  withholdingTiming: BenefitWithholdingTiming
  amount: number
}

export interface PayrollContributionLine {
  programCode: StatutoryProgram
  employeeAmount: number
  employerAmount: number
}

export interface GrossPayRun {
  id: string
  cutoffId: string
  calculationVersion: string
  calculatedAt: string
  calculatedBy: string
  results: GrossPayResult[]
}

export interface CompensationInput {
  employeeId: string
  payrollGroupId: string
  baseRate: number
  currency: string
  effectiveFrom: string
  effectiveTo: string | null
}

export type StatutoryProgram = 'SSS' | 'PHILHEALTH' | 'PAGIBIG'
export type StatutoryScheduleStatus = 'DRAFT' | 'ACTIVE' | 'RETIRED'

interface StatutoryScheduleBase {
  id: string
  scheduleName: string
  effectiveFrom: string
  effectiveTo: string | null
  sourceReference: string
  status: StatutoryScheduleStatus
  createdAt: string
  createdBy: string | null
  updatedAt: string
  updatedBy: string | null
  rowVersion: number
}

export interface ContributionSchedule extends StatutoryScheduleBase {
  programCode: StatutoryProgram
}

export interface WithholdingTaxSchedule extends StatutoryScheduleBase {
  taxExemptBenefitLimit: number
  calculationBasis: 'ANNUAL_YTD' | 'SEMI_MONTHLY'
}

export interface PayrollSystemParameters {
  yearEndWtaxReconciliationEnabled: boolean
  thirteenthMonthEnabled: boolean
  scheduleAssignmentApprovalRequired: boolean
  statutoryContributionTiming: 'PER_CUTOFF' | 'FINAL_CUTOFF'
}

export interface ThirteenthMonthResult {
  employeeId: string
  employeeNo: string
  employeeName: string
  basicSalaryEarned: number
  thirteenthMonthPay: number
  taxExemptAmount: number
  taxableAmount: number
  sourcePayrollPeriods: number
}

export interface ThirteenthMonthRun {
  id: string
  taxYear: number
  coveredPeriodFrom: string
  coveredPeriodTo: string
  calculatedAt: string
  results: ThirteenthMonthResult[]
}

export interface ContributionBracket {
  id: string
  scheduleId: string
  bracketNumber: number
  compensationMin: number
  compensationMax: number | null
  contributionBase: number
  employeeRate: number
  employerRate: number
  employeeFixedAmount: number
  employerFixedAmount: number
  employerAdditionalFixedAmount: number
  employeeContributionCap: number | null
  employerContributionCap: number | null
}

export interface WithholdingTaxBracket {
  id: string
  scheduleId: string
  bracketNumber: number
  annualIncomeMin: number
  annualIncomeMax: number | null
  baseTax: number
  marginalRate: number
  excessOver: number
}

export interface ContributionScheduleInput {
  programCode: StatutoryProgram
  scheduleName: string
  effectiveFrom: string
  effectiveTo: string | null
  sourceReference: string
}

export interface ContributionBracketInput {
  bracketNumber: number
  compensationMin: number
  compensationMax: number | null
  contributionBase: number
  employeeRate: number
  employerRate: number
  employeeFixedAmount: number
  employerFixedAmount: number
  employerAdditionalFixedAmount: number
  employeeContributionCap: number | null
  employerContributionCap: number | null
}

export interface WithholdingTaxScheduleInput {
  scheduleName: string
  effectiveFrom: string
  effectiveTo: string | null
  taxExemptBenefitLimit: number
  calculationBasis: 'ANNUAL_YTD' | 'SEMI_MONTHLY'
  sourceReference: string
}

export interface WithholdingTaxBracketInput {
  bracketNumber: number
  annualIncomeMin: number
  annualIncomeMax: number | null
  baseTax: number
  marginalRate: number
  excessOver: number
}

export type BenefitCategory =
  | 'CASH_ALLOWANCE'
  | 'ONE_TIME_BONUS'
  | 'REIMBURSEMENT'
  | 'EMPLOYER_PAID_INSURANCE'
  | 'NON_CASH'
  | 'EMPLOYEE_DEDUCTION'
export type BenefitTaxTreatment = 'TAXABLE' | 'EXEMPT' | 'EXEMPT_LIMITED'
export type BenefitWithholdingTiming = 'PAY_PERIOD' | 'YEAR_END'
export type BenefitPostingSchedule = 'FIRST_HALF' | 'SECOND_HALF' | 'EVERY_CUTOFF'

export interface BenefitType {
  id: string
  payrollGroupId: string
  code: string
  name: string
  category: BenefitCategory
  taxTreatment: BenefitTaxTreatment
  withholdingTiming: BenefitWithholdingTiming
  attendanceBased: boolean
  deductForLate: boolean
  deductForUndertime: boolean
  postingSchedule: BenefitPostingSchedule
  isActive: boolean
  createdAt: string
  createdBy: string
  updatedAt: string
  updatedBy: string
  rowVersion: number
}

export interface CutoffBenefit {
  id: string
  cutoffId: string
  employeeId: string
  benefitTypeId: string
  benefitCode: string
  benefitName: string
  category: BenefitCategory
  taxTreatment: BenefitTaxTreatment
  withholdingTiming: BenefitWithholdingTiming
  amount: number
  notes: string | null
  attendanceBased: boolean
  deductForLate: boolean
  deductForUndertime: boolean
}

export interface BenefitTypeInput {
  payrollGroupId: string
  code: string
  name: string
  category: BenefitCategory
  taxTreatment: BenefitTaxTreatment
  withholdingTiming: BenefitWithholdingTiming
  attendanceBased: boolean
  deductForLate: boolean
  deductForUndertime: boolean
  postingSchedule: BenefitPostingSchedule
}

export interface EmployeeBenefitEntitlement {
  id: string
  employeeId: string
  benefitTypeId: string
  benefitCode: string
  benefitName: string
  amountPerOccurrence: number
  schedule: BenefitPostingSchedule
  effectiveFrom: string
  effectiveTo: string | null
  isActive: boolean
}

export interface EmployeeBenefitEntitlementInput {
  employeeId: string
  benefitTypeId: string
  amountPerOccurrence: number
  schedule: BenefitPostingSchedule
  effectiveFrom: string
  effectiveTo: string | null
}

export type BenefitDeductionSchedule = 'FIRST_HALF' | 'SECOND_HALF' | 'EVERY_CUTOFF'

export interface EmployeeBenefitDeduction {
  id: string
  employeeId: string
  benefitTypeId: string
  benefitCode: string
  benefitName: string
  amountPerOccurrence: number
  schedule: BenefitDeductionSchedule
  effectiveFrom: string
  effectiveTo: string | null
  isActive: boolean
}

export interface EmployeeBenefitDeductionInput {
  employeeId: string
  benefitTypeId: string
  amountPerOccurrence: number
  schedule: BenefitDeductionSchedule
  effectiveFrom: string
  effectiveTo: string | null
}

export type EmployeeLoanSchedule = 'FIRST_HALF' | 'SECOND_HALF' | 'EVERY_CUTOFF'
export type EmployeeLoanStatus = 'ACTIVE' | 'RETIRED' | 'PAID_OFF'

export interface EmployeeLoanRepayment {
  id: string
  loanId: string
  cutoffId: string
  grossPayRunId: string
  amount: number
  createdAt: string
  cutoffCode: string
}

export interface EmployeeLoan {
  id: string
  employeeId: string
  payrollGroupId: string
  referenceNumber: string
  principalAmount: number
  installmentAmount: number
  schedule: EmployeeLoanSchedule
  effectiveFrom: string
  outstandingBalance: number
  status: EmployeeLoanStatus
  previousLoanId: string | null
  createdAt: string
  repayments: EmployeeLoanRepayment[]
}

export interface EmployeeLoanInput {
  employeeId: string
  payrollGroupId: string
  referenceNumber: string
  principalAmount: number
  installmentAmount: number
  schedule: EmployeeLoanSchedule
  effectiveFrom: string
}

export interface EmployeeLoanRestructureInput {
  referenceNumber: string
  additionalPrincipal: number
  installmentAmount: number
  schedule: EmployeeLoanSchedule
  effectiveFrom: string
}

export interface CutoffBenefitInput {
  cutoffId: string
  employeeId: string
  benefitTypeId: string
  amount: number
  notes: string | null
}

export interface CutoffBenefitUploadRow {
  employeeNo: string
  benefitCode: string
  amount: number
  notes: string | null
}

export interface CutoffBenefitUploadResult {
  created: number
  updated: number
}

export interface EmployeeYtdTaxBalance {
  employeeId: string
  taxYear: number
  taxableIncome: number
  taxWithheld: number
  exemptLimitedBenefits: number
}

export const payrollComponentCodes: PayrollComponentCode[] = [
  'REGULAR',
  'PAID_LEAVE',
  'OFFICIAL_BUSINESS',
  'REST_DAY',
  'SPECIAL_DAY',
  'HOLIDAY',
  'ORDINARY_OT',
  'REST_DAY_OT',
  'SPECIAL_DAY_OT',
  'HOLIDAY_OT',
  'NIGHT_REGULAR',
  'NIGHT_OT',
]

export const payrollComponentLabels: Record<PayrollComponentCode, string> = {
  REGULAR: 'Regular time',
  PAID_LEAVE: 'Paid leave',
  OFFICIAL_BUSINESS: 'Official business',
  REST_DAY: 'Rest-day work',
  SPECIAL_DAY: 'Special-day work',
  HOLIDAY: 'Holiday work',
  ORDINARY_OT: 'Ordinary overtime',
  REST_DAY_OT: 'Rest-day overtime',
  SPECIAL_DAY_OT: 'Special-day overtime',
  HOLIDAY_OT: 'Holiday overtime',
  NIGHT_REGULAR: 'Night differential',
  NIGHT_OT: 'Night overtime differential',
}
