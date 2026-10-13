import type { TodayStatus } from '../../types/dashboard'

interface Props {
  status: TodayStatus
}

export default function TodayStatusCard({ status }: Props) {
  const hasClockedIn = Boolean(status.clockInAt)
  const hasClockedOut = Boolean(status.clockOutAt)

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-500">Today's Attendance</h2>
      <div className="mt-3 flex items-center justify-between">
        <div>
          <p className="text-xs text-slate-500">Time In</p>
          <p className="text-lg font-semibold text-slate-900">{status.clockInAt ?? '—'}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Time Out</p>
          <p className="text-lg font-semibold text-slate-900">{status.clockOutAt ?? '—'}</p>
        </div>
      </div>
      <button
        type="button"
        className="mt-4 w-full rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        disabled={hasClockedIn && hasClockedOut}
      >
        {!hasClockedIn ? 'Clock In' : !hasClockedOut ? 'Clock Out' : 'Done for Today'}
      </button>
    </div>
  )
}
