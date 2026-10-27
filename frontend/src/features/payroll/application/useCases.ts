import type { PayrollRepository } from './ports'
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
  ContributionBracket,
  ContributionBracketInput,
  ContributionSchedule,
  ContributionScheduleInput,
  EmployeeCompensation,
  EmployeeYtdTaxBalance,
  EarningRule,
  GrossPayRun,
  PayrollComponentCode,
  PayrollCutoffOption,
  PayrollEmployeeOption,
  PayrollGroupOption,
  PayrollSystemParameters,
  CutoffBenefit,
  CutoffBenefitInput,
  CutoffBenefitUploadRow,
  CutoffBenefitUploadResult,
  StatutoryProgram,
  ThirteenthMonthRun,
  WithholdingTaxBracket,
  WithholdingTaxBracketInput,
  WithholdingTaxSchedule,
  WithholdingTaxScheduleInput,
} from '../domain/payroll'
import type { EmploymentAssignment } from '../../../types/employeeRelated'

export class PayrollUseCases {
  private readonly repository: PayrollRepository

  constructor(repository: PayrollRepository) {
    this.repository = repository
  }

  listEmployees(): Promise<PayrollEmployeeOption[]> {
    return this.repository.listEmployees()
  }

  listCompanyEmploymentAssignments(companyId: string): Promise<EmploymentAssignment[]> {
    if (!companyId) throw new Error('Select a company before loading its employee assignments.')
    return this.repository.listCompanyEmploymentAssignments(companyId)
  }

  listPayrollGroups(companyId: string): Promise<PayrollGroupOption[]> {
    if (!companyId) throw new Error('Select a company before opening payroll.')
    return this.repository.listPayrollGroups(companyId)
  }

  listCutoffs(payrollGroupId: string): Promise<PayrollCutoffOption[]> {
    return this.repository.listCutoffs(payrollGroupId)
  }

  listCompensations(
    payrollGroupId: string,
    employeeId?: string,
  ): Promise<EmployeeCompensation[]> {
    return this.repository.listCompensations(payrollGroupId, employeeId)
  }

  createCompensation(input: CompensationInput): Promise<EmployeeCompensation> {
    this.validateCompensationInput(input)
    return this.repository.createCompensation(input)
  }

  updateCompensation(compensationId: string, input: CompensationInput): Promise<EmployeeCompensation> {
    if (!compensationId) throw new Error('Select a compensation record to update.')
    this.validateCompensationInput(input)
    return this.repository.updateCompensation(compensationId, input)
  }

  private validateCompensationInput(input: CompensationInput): void {
    if (input.baseRate <= 0 || !Number.isFinite(input.baseRate)) {
      throw new Error('Enter a rate greater than zero.')
    }
    if (input.effectiveTo && input.effectiveTo < input.effectiveFrom) {
      throw new Error('The end date must be on or after the start date.')
    }
  }

  listEarningRules(payrollGroupId: string): Promise<EarningRule[]> {
    return this.repository.listEarningRules(payrollGroupId)
  }

  saveEarningRule(
    payrollGroupId: string,
    componentCode: PayrollComponentCode,
    multiplier: number,
  ): Promise<EarningRule> {
    if (!Number.isFinite(multiplier) || multiplier < 0) {
      throw new Error('Multiplier must be zero or greater.')
    }
    return this.repository.saveEarningRule(payrollGroupId, componentCode, multiplier)
  }

  calculateGrossPay(cutoffId: string): Promise<GrossPayRun> {
    if (!cutoffId) throw new Error('Select a cutoff before calculating gross pay.')
    return this.repository.calculateGrossPay(cutoffId)
  }

  getCurrentGrossPayRun(cutoffId: string): Promise<GrossPayRun | null> {
    return this.repository.getCurrentGrossPayRun(cutoffId)
  }

  approvePayrollCutoff(cutoffId: string): Promise<void> {
    if (!cutoffId) throw new Error('Select a cutoff before approving payroll.')
    return this.repository.approvePayrollCutoff(cutoffId)
  }

  unlockPayrollCutoff(cutoffId: string): Promise<void> {
    if (!cutoffId) throw new Error('Select a cutoff before unlocking payroll.')
    return this.repository.unlockPayrollCutoff(cutoffId)
  }

  listBenefitTypes(payrollGroupId: string): Promise<BenefitType[]> {
    if (!payrollGroupId) throw new Error('Select a payroll group before loading its benefit types.')
    return this.repository.listBenefitTypes(payrollGroupId)
  }

  createBenefitType(input: BenefitTypeInput): Promise<BenefitType> {
    this.validateBenefitType(input)
    return this.repository.createBenefitType(input)
  }

  updateBenefitType(benefitTypeId: string, input: BenefitTypeInput): Promise<BenefitType> {
    if (!benefitTypeId) throw new Error('Select a benefit type to update.')
    this.validateBenefitType(input)
    return this.repository.updateBenefitType(benefitTypeId, input)
  }

  setBenefitTypeActive(benefitTypeId: string, isActive: boolean): Promise<BenefitType> {
    if (!benefitTypeId) throw new Error('Select a benefit type to change its status.')
    return this.repository.setBenefitTypeActive(benefitTypeId, isActive)
  }

  listCutoffBenefits(cutoffId: string): Promise<CutoffBenefit[]> {
    if (!cutoffId) throw new Error('Select a cutoff before loading benefit entries.')
    return this.repository.listCutoffBenefits(cutoffId)
  }

  createCutoffBenefit(input: CutoffBenefitInput): Promise<CutoffBenefit> {
    this.validateCutoffBenefit(input)
    return this.repository.createCutoffBenefit(input)
  }

  updateCutoffBenefit(entryId: string, input: CutoffBenefitInput): Promise<CutoffBenefit> {
    if (!entryId) throw new Error('Select a cutoff benefit entry to update.')
    this.validateCutoffBenefit(input)
    return this.repository.updateCutoffBenefit(entryId, input)
  }

  uploadCutoffBenefits(
    cutoffId: string,
    rows: CutoffBenefitUploadRow[],
  ): Promise<CutoffBenefitUploadResult> {
    this.validateCutoffUpload(cutoffId, rows, 'benefit')
    return this.repository.uploadCutoffBenefits(cutoffId, rows)
  }

  uploadCutoffDeductions(
    cutoffId: string,
    rows: CutoffBenefitUploadRow[],
  ): Promise<CutoffBenefitUploadResult> {
    this.validateCutoffUpload(cutoffId, rows, 'deduction')
    return this.repository.uploadCutoffDeductions(cutoffId, rows)
  }

  private validateCutoffUpload(
    cutoffId: string,
    rows: CutoffBenefitUploadRow[],
    entryName: string,
  ): void {
    if (!cutoffId) throw new Error(`Select a cutoff before uploading ${entryName}s.`)
    if (rows.length === 0) throw new Error(`The upload must contain at least one ${entryName} row.`)
    if (rows.length > 1000) throw new Error(`A ${entryName} upload cannot contain more than 1,000 rows.`)
    const seen = new Set<string>()
    for (const [index, row] of rows.entries()) {
      const employeeNo = row.employeeNo.trim().toUpperCase()
      const benefitCode = row.benefitCode.trim().toUpperCase()
      if (!employeeNo || !benefitCode) {
        throw new Error(`Row ${index + 2}: employee number and ${entryName} code are required.`)
      }
      if (!Number.isFinite(row.amount) || row.amount <= 0) {
        throw new Error(`Row ${index + 2}: amount must be greater than zero.`)
      }
      if (row.notes && row.notes.length > 500) {
        throw new Error(`Row ${index + 2}: notes cannot exceed 500 characters.`)
      }
      const key = `${employeeNo}\u0000${benefitCode}`
      if (seen.has(key)) {
        throw new Error(`Row ${index + 2}: duplicate employee number and ${entryName} code in the upload.`)
      }
      seen.add(key)
    }
  }

  deleteCutoffBenefit(entryId: string): Promise<void> {
    if (!entryId) throw new Error('Select a cutoff benefit entry to delete.')
    return this.repository.deleteCutoffBenefit(entryId)
  }

  listEmployeeBenefitDeductions(payrollGroupId: string): Promise<EmployeeBenefitDeduction[]> {
    if (!payrollGroupId) throw new Error('Select a payroll group before loading recurring deductions.')
    return this.repository.listEmployeeBenefitDeductions(payrollGroupId)
  }

  createEmployeeBenefitDeduction(
    input: EmployeeBenefitDeductionInput,
  ): Promise<EmployeeBenefitDeduction> {
    this.validateEmployeeBenefitDeduction(input)
    return this.repository.createEmployeeBenefitDeduction(input)
  }

  updateEmployeeBenefitDeduction(
    deductionId: string,
    input: EmployeeBenefitDeductionInput,
  ): Promise<EmployeeBenefitDeduction> {
    if (!deductionId) throw new Error('Select a recurring deduction to update.')
    this.validateEmployeeBenefitDeduction(input)
    return this.repository.updateEmployeeBenefitDeduction(deductionId, input)
  }

  setEmployeeBenefitDeductionActive(
    deductionId: string,
    isActive: boolean,
  ): Promise<EmployeeBenefitDeduction> {
    if (!deductionId) throw new Error('Select a recurring deduction to change its status.')
    return this.repository.setEmployeeBenefitDeductionActive(deductionId, isActive)
  }

  listEmployeeLoans(payrollGroupId: string): Promise<EmployeeLoan[]> {
    if (!payrollGroupId) throw new Error('Select a payroll group before loading employee loans.')
    return this.repository.listEmployeeLoans(payrollGroupId)
  }

  createEmployeeLoan(input: EmployeeLoanInput): Promise<EmployeeLoan> {
    this.validateEmployeeLoan(input)
    return this.repository.createEmployeeLoan(input)
  }

  retireEmployeeLoan(loanId: string): Promise<EmployeeLoan> {
    if (!loanId) throw new Error('Select a loan to retire.')
    return this.repository.retireEmployeeLoan(loanId)
  }

  restructureEmployeeLoan(
    loanId: string,
    input: EmployeeLoanRestructureInput,
  ): Promise<EmployeeLoan> {
    if (!loanId) throw new Error('Select a loan to restructure.')
    if (!input.referenceNumber.trim() || input.referenceNumber.trim().length > 50) {
      throw new Error('Loan reference number must contain 1 to 50 characters.')
    }
    if (!Number.isFinite(input.additionalPrincipal) || input.additionalPrincipal < 0) {
      throw new Error('Additional principal must be zero or greater.')
    }
    if (!Number.isFinite(input.installmentAmount) || input.installmentAmount <= 0) {
      throw new Error('Loan installment must be greater than zero.')
    }
    if (!['FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF'].includes(input.schedule)) {
      throw new Error('Select a valid loan deduction schedule.')
    }
    return this.repository.restructureEmployeeLoan(loanId, input)
  }

  private validateEmployeeLoan(input: EmployeeLoanInput): void {
    if (!input.employeeId || !input.payrollGroupId) {
      throw new Error('Select an employee and payroll group.')
    }
    if (!input.referenceNumber.trim() || input.referenceNumber.trim().length > 50) {
      throw new Error('Loan reference number must contain 1 to 50 characters.')
    }
    if (!Number.isFinite(input.principalAmount) || input.principalAmount <= 0) {
      throw new Error('Loan principal must be greater than zero.')
    }
    if (!Number.isFinite(input.installmentAmount) || input.installmentAmount <= 0) {
      throw new Error('Loan installment must be greater than zero.')
    }
    if (!['FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF'].includes(input.schedule)) {
      throw new Error('Select a valid loan deduction schedule.')
    }
  }

  getEmployeeYtdTaxBalance(
    employeeId: string,
    taxYear: number,
  ): Promise<EmployeeYtdTaxBalance | null> {
    if (!employeeId || !Number.isInteger(taxYear) || taxYear < 2000) {
      throw new Error('Select an employee and a valid tax year.')
    }
    return this.repository.getEmployeeYtdTaxBalance(employeeId, taxYear)
  }

  saveEmployeeYtdTaxBalance(balance: EmployeeYtdTaxBalance): Promise<EmployeeYtdTaxBalance> {
    if (!balance.employeeId || !Number.isInteger(balance.taxYear) || balance.taxYear < 2000) {
      throw new Error('Select an employee and a valid tax year.')
    }
    const amounts = [balance.taxableIncome, balance.taxWithheld, balance.exemptLimitedBenefits]
    if (amounts.some((amount) => !Number.isFinite(amount) || amount < 0)) {
      throw new Error('Year-to-date balance amounts must be valid and nonnegative.')
    }
    return this.repository.saveEmployeeYtdTaxBalance(balance)
  }

  private validateBenefitType(input: BenefitTypeInput): void {
    if (!input.payrollGroupId) throw new Error('Select a payroll group.')
    if (!input.code.trim() || input.code.trim().length > 30) {
      throw new Error('Benefit code must contain 1 to 30 characters.')
    }
    if (!input.name.trim() || input.name.trim().length > 120) {
      throw new Error('Benefit name must contain 1 to 120 characters.')
    }
    if (!['FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF'].includes(input.postingSchedule)) {
      throw new Error('Select a valid benefit posting schedule.')
    }
    if (
      input.withholdingTiming === 'YEAR_END'
      && (input.category !== 'ONE_TIME_BONUS' || input.taxTreatment !== 'TAXABLE')
    ) {
      throw new Error('Year-end withholding is available only for taxable one-time bonuses.')
    }
    if (input.category === 'EMPLOYEE_DEDUCTION' && input.taxTreatment !== 'EXEMPT') {
      throw new Error('Employee benefit deductions must use exempt tax treatment.')
    }
    if (input.category === 'EMPLOYEE_DEDUCTION' && input.attendanceBased) {
      throw new Error('Recurring employee deductions cannot be attendance-based.')
    }
    if (
      !input.attendanceBased
      && (input.deductForLate || input.deductForUndertime)
    ) {
      throw new Error('Enable attendance-based calculation before enabling time deductions.')
    }
  }

  listEmployeeBenefitEntitlements(payrollGroupId: string): Promise<EmployeeBenefitEntitlement[]> {
    if (!payrollGroupId) throw new Error('Select a payroll group.')
    return this.repository.listEmployeeBenefitEntitlements(payrollGroupId)
  }

  createEmployeeBenefitEntitlement(
    input: EmployeeBenefitEntitlementInput,
  ): Promise<EmployeeBenefitEntitlement> {
    this.validateEmployeeBenefitEntitlement(input)
    return this.repository.createEmployeeBenefitEntitlement(input)
  }

  updateEmployeeBenefitEntitlement(
    entitlementId: string,
    input: EmployeeBenefitEntitlementInput,
  ): Promise<EmployeeBenefitEntitlement> {
    if (!entitlementId) throw new Error('Select an employee benefit entitlement to update.')
    this.validateEmployeeBenefitEntitlement(input)
    return this.repository.updateEmployeeBenefitEntitlement(entitlementId, input)
  }

  setEmployeeBenefitEntitlementActive(
    entitlementId: string,
    isActive: boolean,
  ): Promise<EmployeeBenefitEntitlement> {
    if (!entitlementId) throw new Error('Select an employee benefit entitlement.')
    return this.repository.setEmployeeBenefitEntitlementActive(entitlementId, isActive)
  }

  private validateEmployeeBenefitEntitlement(input: EmployeeBenefitEntitlementInput): void {
    if (!input.employeeId || !input.benefitTypeId) {
      throw new Error('Select an employee and benefit type.')
    }
    if (!Number.isFinite(input.amountPerOccurrence) || input.amountPerOccurrence <= 0) {
      throw new Error('Benefit amount per occurrence must be greater than zero.')
    }
    if (input.effectiveTo && input.effectiveTo < input.effectiveFrom) {
      throw new Error('Benefit end date must be on or after its start date.')
    }
  }

  private validateEmployeeBenefitDeduction(input: EmployeeBenefitDeductionInput): void {
    if (!input.employeeId || !input.benefitTypeId) {
      throw new Error('Select an employee and employee-deduction benefit type.')
    }
    if (!Number.isFinite(input.amountPerOccurrence) || input.amountPerOccurrence <= 0) {
      throw new Error('Deduction amount per occurrence must be greater than zero.')
    }
    if (input.effectiveTo && input.effectiveTo < input.effectiveFrom) {
      throw new Error('Deduction end date must be on or after its start date.')
    }
  }

  private validateCutoffBenefit(input: CutoffBenefitInput): void {
    if (!input.cutoffId || !input.employeeId || !input.benefitTypeId) {
      throw new Error('Select a cutoff, employee, and benefit type.')
    }
    if (!Number.isFinite(input.amount) || input.amount <= 0) {
      throw new Error('Benefit amount must be greater than zero.')
    }
  }

  listContributionSchedules(programCode?: StatutoryProgram): Promise<ContributionSchedule[]> {
    return this.repository.listContributionSchedules(programCode)
  }

  getContributionSchedule(scheduleId: string): Promise<ContributionSchedule> {
    return this.repository.getContributionSchedule(scheduleId)
  }

  createContributionSchedule(input: ContributionScheduleInput): Promise<ContributionSchedule> {
    this.validateScheduleInput(input)
    return this.repository.createContributionSchedule(input)
  }

  updateContributionSchedule(
    scheduleId: string,
    input: ContributionScheduleInput,
  ): Promise<ContributionSchedule> {
    if (!scheduleId) throw new Error('Select a contribution schedule to update.')
    this.validateScheduleInput(input)
    return this.repository.updateContributionSchedule(scheduleId, input)
  }

  deleteContributionSchedule(scheduleId: string): Promise<void> {
    return this.repository.deleteContributionSchedule(scheduleId)
  }

  activateContributionSchedule(scheduleId: string): Promise<ContributionSchedule> {
    return this.repository.activateContributionSchedule(scheduleId)
  }

  retireContributionSchedule(scheduleId: string): Promise<ContributionSchedule> {
    return this.repository.retireContributionSchedule(scheduleId)
  }

  listContributionBrackets(scheduleId: string): Promise<ContributionBracket[]> {
    return this.repository.listContributionBrackets(scheduleId)
  }

  getContributionBracket(bracketId: string): Promise<ContributionBracket> {
    return this.repository.getContributionBracket(bracketId)
  }

  createContributionBracket(
    scheduleId: string,
    input: ContributionBracketInput,
  ): Promise<ContributionBracket> {
    this.validateContributionBracket(input)
    return this.repository.createContributionBracket(scheduleId, input)
  }

  updateContributionBracket(
    bracketId: string,
    input: ContributionBracketInput,
  ): Promise<ContributionBracket> {
    if (!bracketId) throw new Error('Select a contribution bracket to update.')
    this.validateContributionBracket(input)
    return this.repository.updateContributionBracket(bracketId, input)
  }

  deleteContributionBracket(bracketId: string): Promise<void> {
    return this.repository.deleteContributionBracket(bracketId)
  }

  listWithholdingTaxSchedules(): Promise<WithholdingTaxSchedule[]> {
    return this.repository.listWithholdingTaxSchedules()
  }

  getPayrollSystemParameters(companyId: string): Promise<PayrollSystemParameters> {
    return this.repository.getPayrollSystemParameters(companyId)
  }

  updatePayrollSystemParameters(
    companyId: string,
    parameters: PayrollSystemParameters,
  ): Promise<PayrollSystemParameters> {
    return this.repository.updatePayrollSystemParameters(companyId, parameters)
  }

  calculateThirteenthMonth(
    companyId: string,
    taxYear: number,
    coveredPeriodFrom: string,
    coveredPeriodTo: string,
  ): Promise<ThirteenthMonthRun> {
    if (!Number.isInteger(taxYear) || taxYear < 1900 || taxYear > 9999) {
      throw new Error('Enter a valid tax year.')
    }
    if (!coveredPeriodFrom || !coveredPeriodTo || coveredPeriodFrom > coveredPeriodTo) {
      throw new Error('Enter the start and end dates of the last covered payroll cutoff.')
    }
    if (
      !coveredPeriodFrom.startsWith(`${taxYear}-`)
      || !coveredPeriodTo.startsWith(`${taxYear}-`)
    ) {
      throw new Error('The covered payroll cutoff dates must be in the selected tax year.')
    }
    return this.repository.calculateThirteenthMonth(
      companyId,
      taxYear,
      coveredPeriodFrom,
      coveredPeriodTo,
    )
  }

  getWithholdingTaxSchedule(scheduleId: string): Promise<WithholdingTaxSchedule> {
    return this.repository.getWithholdingTaxSchedule(scheduleId)
  }

  createWithholdingTaxSchedule(input: WithholdingTaxScheduleInput): Promise<WithholdingTaxSchedule> {
    this.validateScheduleInput(input)
    if (input.taxExemptBenefitLimit < 0 || !Number.isFinite(input.taxExemptBenefitLimit)) {
      throw new Error('Tax-exempt benefit limit cannot be negative.')
    }
    return this.repository.createWithholdingTaxSchedule(input)
  }

  updateWithholdingTaxSchedule(
    scheduleId: string,
    input: WithholdingTaxScheduleInput,
  ): Promise<WithholdingTaxSchedule> {
    if (!scheduleId) throw new Error('Select a withholding tax schedule to update.')
    this.validateScheduleInput(input)
    if (input.taxExemptBenefitLimit < 0 || !Number.isFinite(input.taxExemptBenefitLimit)) {
      throw new Error('Tax-exempt benefit limit cannot be negative.')
    }
    return this.repository.updateWithholdingTaxSchedule(scheduleId, input)
  }

  deleteWithholdingTaxSchedule(scheduleId: string): Promise<void> {
    return this.repository.deleteWithholdingTaxSchedule(scheduleId)
  }

  activateWithholdingTaxSchedule(scheduleId: string): Promise<WithholdingTaxSchedule> {
    return this.repository.activateWithholdingTaxSchedule(scheduleId)
  }

  retireWithholdingTaxSchedule(scheduleId: string): Promise<WithholdingTaxSchedule> {
    return this.repository.retireWithholdingTaxSchedule(scheduleId)
  }

  listWithholdingTaxBrackets(scheduleId: string): Promise<WithholdingTaxBracket[]> {
    return this.repository.listWithholdingTaxBrackets(scheduleId)
  }

  getWithholdingTaxBracket(bracketId: string): Promise<WithholdingTaxBracket> {
    return this.repository.getWithholdingTaxBracket(bracketId)
  }

  createWithholdingTaxBracket(
    scheduleId: string,
    input: WithholdingTaxBracketInput,
  ): Promise<WithholdingTaxBracket> {
    this.validateWithholdingTaxBracket(input)
    return this.repository.createWithholdingTaxBracket(scheduleId, input)
  }

  updateWithholdingTaxBracket(
    bracketId: string,
    input: WithholdingTaxBracketInput,
  ): Promise<WithholdingTaxBracket> {
    if (!bracketId) throw new Error('Select a withholding tax bracket to update.')
    this.validateWithholdingTaxBracket(input)
    return this.repository.updateWithholdingTaxBracket(bracketId, input)
  }

  deleteWithholdingTaxBracket(bracketId: string): Promise<void> {
    return this.repository.deleteWithholdingTaxBracket(bracketId)
  }

  private validateScheduleInput(input: {
    scheduleName: string
    effectiveFrom: string
    effectiveTo: string | null
    sourceReference: string
  }): void {
    if (!input.scheduleName.trim()) throw new Error('Schedule name is required.')
    if (!input.sourceReference.trim()) throw new Error('A source reference is required.')
    if (input.effectiveTo && input.effectiveTo < input.effectiveFrom) {
      throw new Error('The end date must be on or after the start date.')
    }
  }

  private validateContributionBracket(input: ContributionBracketInput): void {
    const amounts = [
      input.compensationMin,
      input.compensationMax,
      input.contributionBase,
      input.employeeFixedAmount,
      input.employerFixedAmount,
      input.employerAdditionalFixedAmount,
      input.employeeContributionCap,
      input.employerContributionCap,
    ]
    if (amounts.some((amount) => amount !== null && (!Number.isFinite(amount) || amount < 0))) {
      throw new Error('Contribution bracket amounts must be valid and nonnegative.')
    }
    if (input.compensationMax !== null && input.compensationMax < input.compensationMin) {
      throw new Error('Maximum compensation must be on or above minimum compensation.')
    }
    if (![input.employeeRate, input.employerRate].every((rate) =>
      Number.isFinite(rate) && rate >= 0 && rate <= 1)) {
      throw new Error('Contribution rates must be between zero and one.')
    }
    if (!Number.isInteger(input.bracketNumber) || input.bracketNumber < 1) {
      throw new Error('Bracket number must be a positive integer.')
    }
  }

  private validateWithholdingTaxBracket(input: WithholdingTaxBracketInput): void {
    const amounts = [input.annualIncomeMin, input.annualIncomeMax, input.baseTax, input.excessOver]
    if (amounts.some((amount) => amount !== null && (!Number.isFinite(amount) || amount < 0))) {
      throw new Error('Withholding tax bracket amounts must be valid and nonnegative.')
    }
    if (input.annualIncomeMax !== null && input.annualIncomeMax < input.annualIncomeMin) {
      throw new Error('Maximum taxable income must be on or above minimum taxable income.')
    }
    if (!Number.isFinite(input.marginalRate) || input.marginalRate < 0 || input.marginalRate > 1) {
      throw new Error('Marginal tax rate must be between zero and one.')
    }
    if (!Number.isInteger(input.bracketNumber) || input.bracketNumber < 1) {
      throw new Error('Bracket number must be a positive integer.')
    }
  }
}
