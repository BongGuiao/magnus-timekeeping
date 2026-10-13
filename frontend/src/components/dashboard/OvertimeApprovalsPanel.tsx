import { useState } from 'react'
import type { OvertimeApplication } from '../../lib/attendanceApi'

interface Props {
  requests: OvertimeApplication[]
  isLoading: boolean
  error: string | null
  savingId: string | null
  onDecision: (
    applicationId: string,
    decision: 'APPROVED' | 'REJECTED',
    approvedMinutes: number,
  ) => Promise<void>
}

function formatMinutes(minutes: number): string {
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function overtimeTypeLabel(type: OvertimeApplication['overtime_type']): string {
  switch (type) {
    case 'REGULAR_OVERTIME':
      return 'Regular OT'
    case 'NIGHT_DIFFERENTIAL_OVERTIME':
      return 'Night OT'
    case 'NIGHT_DIFFERENTIAL':
      return 'Night differential'
  }
}

export default function OvertimeApprovalsPanel({
  requests,
  isLoading,
  error,
  savingId,
  onDecision,
}: Props) {
  const [drafts, setDrafts] = useState<Record<string, number>>({})

  function getDraft(request: OvertimeApplication): number {
    return drafts[request.id] ?? request.requested_minutes
  }

  return (
    <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">Overtime applications</h2>
          <p className="mt-1 text-sm text-slate-500">
            Approve any amount up to the employee’s request. Final approved minutes become the payroll basis.
          </p>
        </div>
        <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
          {requests.length} pending
        </span>
      </div>

      {error && <p role="alert" className="mt-4 text-sm text-rose-700">{error}</p>}
      {isLoading ? (
        <p className="mt-5 text-sm text-slate-500">Loading overtime applications…</p>
      ) : requests.length === 0 ? (
        <p className="mt-5 rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
          There are no pending overtime applications.
        </p>
      ) : (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[1050px] text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-3">Employee / date</th>
                <th className="px-3 py-3">Application</th>
                <th className="px-3 py-3">Requested</th>
                <th className="px-3 py-3">Approve hours</th>
                <th className="px-3 py-3 text-right">Decision</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {requests.map((request) => {
                const isSaving = savingId === request.id
                return (
                  <tr key={request.id} className="align-top">
                    <td className="px-3 py-4">
                      <p className="font-semibold text-slate-900">{request.employee_name}</p>
                      <p className="mt-1 text-xs text-slate-500">
                        {request.employee_code} · {request.attendance_date}
                      </p>
                    </td>
                    <td className="px-3 py-4">
                      <p className="font-semibold text-slate-700">{overtimeTypeLabel(request.overtime_type)}</p>
                      <p className="mt-1 text-xs text-slate-500">{request.application_no}</p>
                      <p className="mt-1 max-w-sm text-xs text-slate-600">{request.reason}</p>
                    </td>
                    <td className="px-3 py-4 text-xs text-slate-600">
                      <p>{formatMinutes(request.requested_minutes)} requested</p>
                      <p>{formatMinutes(request.potential_ot_minutes)} calculated</p>
                    </td>
                    <td className="px-3 py-4">
                      <label className="text-xs text-slate-500">
                        Approved (hours)
                        <input
                          type="number"
                          min={0}
                          max={request.requested_minutes / 60}
                          step={0.25}
                          value={getDraft(request) / 60}
                          disabled={isSaving}
                          onChange={(event) => {
                            const value = Number(event.target.value)
                            setDrafts((current) => ({
                              ...current,
                              [request.id]: Math.min(
                                request.requested_minutes,
                                Math.max(0, Math.round((Number.isFinite(value) ? value : 0) * 60)),
                              ),
                            }))
                          }}
                          className="mt-1 block w-32 rounded border border-slate-300 px-2 py-1.5 text-xs text-slate-700 disabled:opacity-50"
                        />
                      </label>
                    </td>
                    <td className="px-3 py-4 text-right">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          disabled={isSaving}
                          onClick={() => void onDecision(request.id, 'APPROVED', getDraft(request))}
                          className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
                        >
                          Approve amount
                        </button>
                        <button
                          type="button"
                          disabled={isSaving}
                          onClick={() => void onDecision(request.id, 'REJECTED', 0)}
                          className="rounded-lg border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700 disabled:opacity-50"
                        >
                          Reject
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
