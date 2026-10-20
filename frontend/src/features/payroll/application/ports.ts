import type {
  CompensationInput,
  BenefitType,
  BenefitTypeInput,
  EmployeeBenefitEntitlement,
  EmployeeBenefitEntitlementInput,
  EmployeeBenefitDeduction,
  EmployeeBenefitDeductionInput,
  CutoffBenefit,
  CutoffBenefitInput,
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
  StatutoryProgram,
  WithholdingTaxBracket,
  WithholdingTaxBracketInput,
  WithholdingTaxSchedule,
  WithholdingTaxScheduleInput,
} from '../domain/payroll'
import type { EmploymentAssignment } from '../../../types/employeeRelated'

export interface PayrollRepository {
  listEmployees(): Promise<PayrollEmployeeOption[]>
  listCompanyEmploymentAssignments(companyId: string): Promise<EmploymentAssignment[]>
  listPayrollGroups(companyId: string): Promise<PayrollGroupOption[]>
  listCutoffs(payrollGroupId: string): Promise<PayrollCutoffOption[]>
  listCompensations(payrollGroupId: string, employeeId?: string): Promise<EmployeeCompensation[]>
  createCompensation(input: CompensationInput): Promise<EmployeeCompensation>
  updateCompensation(compensationId: string, input: CompensationInput): Promise<EmployeeCompensation>
  listEarningRules(payrollGroupId: string): Promise<EarningRule[]>
  saveEarningRule(
    payrollGroupId: string,
    componentCode: PayrollComponentCode,
    multiplier: number,
  ): Promise<EarningRule>
  calculateGrossPay(cutoffId: string): Promise<GrossPayRun>
  getCurrentGrossPayRun(cutoffId: string): Promise<GrossPayRun | null>
  listContributionSchedules(programCode?: StatutoryProgram): Promise<ContributionSchedule[]>
  getContributionSchedule(scheduleId: string): Promise<ContributionSchedule>
  createContributionSchedule(input: ContributionScheduleInput): Promise<ContributionSchedule>
  updateContributionSchedule(scheduleId: string, input: ContributionScheduleInput): Promise<ContributionSchedule>
  deleteContributionSchedule(scheduleId: string): Promise<void>
  activateContributionSchedule(scheduleId: string): Promise<ContributionSchedule>
  retireContributionSchedule(scheduleId: string): Promise<ContributionSchedule>
  listContributionBrackets(scheduleId: string): Promise<ContributionBracket[]>
  getContributionBracket(bracketId: string): Promise<ContributionBracket>
  createContributionBracket(scheduleId: string, input: ContributionBracketInput): Promise<ContributionBracket>
  updateContributionBracket(bracketId: string, input: ContributionBracketInput): Promise<ContributionBracket>
  deleteContributionBracket(bracketId: string): Promise<void>
  listWithholdingTaxSchedules(): Promise<WithholdingTaxSchedule[]>
  getWithholdingTaxSchedule(scheduleId: string): Promise<WithholdingTaxSchedule>
  createWithholdingTaxSchedule(input: WithholdingTaxScheduleInput): Promise<WithholdingTaxSchedule>
  updateWithholdingTaxSchedule(scheduleId: string, input: WithholdingTaxScheduleInput): Promise<WithholdingTaxSchedule>
  deleteWithholdingTaxSchedule(scheduleId: string): Promise<void>
  activateWithholdingTaxSchedule(scheduleId: string): Promise<WithholdingTaxSchedule>
  retireWithholdingTaxSchedule(scheduleId: string): Promise<WithholdingTaxSchedule>
  listWithholdingTaxBrackets(scheduleId: string): Promise<WithholdingTaxBracket[]>
  getWithholdingTaxBracket(bracketId: string): Promise<WithholdingTaxBracket>
  createWithholdingTaxBracket(scheduleId: string, input: WithholdingTaxBracketInput): Promise<WithholdingTaxBracket>
  updateWithholdingTaxBracket(bracketId: string, input: WithholdingTaxBracketInput): Promise<WithholdingTaxBracket>
  deleteWithholdingTaxBracket(bracketId: string): Promise<void>
  listBenefitTypes(payrollGroupId: string): Promise<BenefitType[]>
  createBenefitType(input: BenefitTypeInput): Promise<BenefitType>
  updateBenefitType(benefitTypeId: string, input: BenefitTypeInput): Promise<BenefitType>
  setBenefitTypeActive(benefitTypeId: string, isActive: boolean): Promise<BenefitType>
  listEmployeeBenefitEntitlements(payrollGroupId: string): Promise<EmployeeBenefitEntitlement[]>
  createEmployeeBenefitEntitlement(input: EmployeeBenefitEntitlementInput): Promise<EmployeeBenefitEntitlement>
  updateEmployeeBenefitEntitlement(
    entitlementId: string,
    input: EmployeeBenefitEntitlementInput,
  ): Promise<EmployeeBenefitEntitlement>
  setEmployeeBenefitEntitlementActive(
    entitlementId: string,
    isActive: boolean,
  ): Promise<EmployeeBenefitEntitlement>
  listCutoffBenefits(cutoffId: string): Promise<CutoffBenefit[]>
  createCutoffBenefit(input: CutoffBenefitInput): Promise<CutoffBenefit>
  updateCutoffBenefit(entryId: string, input: CutoffBenefitInput): Promise<CutoffBenefit>
  deleteCutoffBenefit(entryId: string): Promise<void>
  listEmployeeBenefitDeductions(payrollGroupId: string): Promise<EmployeeBenefitDeduction[]>
  createEmployeeBenefitDeduction(input: EmployeeBenefitDeductionInput): Promise<EmployeeBenefitDeduction>
  updateEmployeeBenefitDeduction(
    deductionId: string,
    input: EmployeeBenefitDeductionInput,
  ): Promise<EmployeeBenefitDeduction>
  setEmployeeBenefitDeductionActive(
    deductionId: string,
    isActive: boolean,
  ): Promise<EmployeeBenefitDeduction>
  getEmployeeYtdTaxBalance(employeeId: string, taxYear: number): Promise<EmployeeYtdTaxBalance | null>
  saveEmployeeYtdTaxBalance(balance: EmployeeYtdTaxBalance): Promise<EmployeeYtdTaxBalance>
}
