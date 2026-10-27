import type {
  OffCycleBenefitRunInput,
  OffCyclePayrollRun,
  OffCycleRunStatus,
  OffCycleThirteenthMonthRunInput,
  ThirteenthMonthSource,
} from '../domain/offCycle'

export interface OffCycleRunFilter {
  companyId: string
  payrollGroupId?: string
  status?: OffCycleRunStatus
}

export interface OffCyclePayrollRepository {
  listRuns(filter: OffCycleRunFilter): Promise<OffCyclePayrollRun[]>
  getRun(runId: string): Promise<OffCyclePayrollRun>
  listThirteenthMonthSources(payrollGroupId: string): Promise<ThirteenthMonthSource[]>
  createBenefitRun(input: OffCycleBenefitRunInput): Promise<OffCyclePayrollRun>
  createThirteenthMonthRun(input: OffCycleThirteenthMonthRunInput): Promise<OffCyclePayrollRun>
  recalculateRun(runId: string): Promise<OffCyclePayrollRun>
  submitRun(runId: string): Promise<OffCyclePayrollRun>
  approveRun(runId: string): Promise<OffCyclePayrollRun>
  rejectRun(runId: string, reason: string): Promise<OffCyclePayrollRun>
  markRunPaid(runId: string, actualPaymentDate: string): Promise<OffCyclePayrollRun>
  deleteRun(runId: string): Promise<void>
}
