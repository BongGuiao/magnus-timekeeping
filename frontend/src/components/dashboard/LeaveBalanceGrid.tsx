import type { LeaveBalance } from '../../types/dashboard'
import { minutesToLeaveUnits } from '../../lib/leaveApi'

interface Props {
  balances: LeaveBalance[]
  isLoading?: boolean
  error?: string | null
  refreshedAt?: string | null
}

export default function LeaveBalanceGrid({ balances, isLoading = false, error, refreshedAt }: Props) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-500">Leave Balances</h2>
        {refreshedAt && <span className="text-[11px] text-slate-400">Updated {new Date(refreshedAt).toLocaleTimeString()}</span>}
      </div>
      {error && <p role="alert" className="mt-2 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p>}
      {isLoading ? (
        <p className="mt-2 text-sm text-slate-500">Loading leave balances…</p>
      ) : balances.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">No leave entitlements found for this year.</p>
      ) : <div className="mt-2 grid grid-cols-2 gap-2">
        {balances.map((leave) => {
          const remaining = leave.available ?? leave.allotted - leave.used
          const format = (minutes: number) => {
            if (!leave.unitType) return minutes.toLocaleString()
            const value = minutesToLeaveUnits(minutes, leave.unitType)
            const formattedValue = value.toLocaleString(undefined, { maximumFractionDigits: 3 })
            const unitLabel = leave.unitType === 'DAYS'
              ? 'days'
              : leave.unitType === 'HOURS'
                ? 'hours'
                : 'minutes'
            return `${formattedValue} ${unitLabel}`
          }
          return (
            <div key={leave.type} className="rounded-lg border border-slate-100 bg-slate-50 p-2 text-center">
              <p className="text-xs font-medium text-slate-500">{leave.label}</p>
              <p className="mt-1 text-lg font-bold text-slate-900">{format(remaining)}</p>
              <p className="text-[11px] text-slate-400">available · {format(leave.allotted)} total</p>
            </div>
          )
        })}
      </div>}
    </div>
  )
}
