import { useEffect, useState } from 'react'
import {
  decideOfficialBusinessRequest,
  fetchPendingOfficialBusinessRequests,
  formatDuration,
  formatManilaDateTime,
  type OfficialBusinessRequest,
} from '../../lib/officialBusinessApi'

interface Props {
  onPendingCountChange?: (count: number) => void
}

export default function OfficialBusinessApprovalsPanel({ onPendingCountChange }: Props) {
  const [requests, setRequests] = useState<OfficialBusinessRequest[]>([])
  const [drafts, setDrafts] = useState<Record<string, number>>({})
  const [isLoading, setIsLoading] = useState(true)
  const [savingId, setSavingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    fetchPendingOfficialBusinessRequests()
      .then((records) => {
        if (!current) return
        setRequests(records)
        onPendingCountChange?.(records.length)
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load pending official business requests.')
      })
      .finally(() => { if (current) setIsLoading(false) })
    return () => { current = false }
  }, [onPendingCountChange])

  function getDraft(request: OfficialBusinessRequest): number {
    return drafts[request.id] ?? request.requested_minutes
  }

  async function decide(request: OfficialBusinessRequest, decision: 'APPROVED' | 'REJECTED') {
    if (savingId) return
    const approvedMinutes = getDraft(request)
    if (decision === 'APPROVED' && (approvedMinutes < 1 || approvedMinutes > request.requested_minutes)) {
      setError(`Approved minutes for ${request.request_no} must be from 1 to ${request.requested_minutes}.`)
      return
    }
    setSavingId(request.id)
    setError(null)
    setSuccess(null)
    try {
      const result = await decideOfficialBusinessRequest(request.id, decision, approvedMinutes, request.row_version)
      const next = requests.filter((item) => item.id !== request.id)
      setRequests(next)
      onPendingCountChange?.(next.length)
      setSuccess(`${result.request_no} was ${result.status.toLowerCase()}.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the official business decision.')
    } finally {
      setSavingId(null)
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">Official business requests</h2>
          <p className="mt-1 text-sm text-slate-500">
            Approve the full request or a reduced number of minutes. Times are shown in Philippine time.
          </p>
        </div>
        <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">
          {requests.length} pending
        </span>
      </div>

      {error && <p role="alert" className="mt-4 text-sm text-rose-700">{error}</p>}
      {success && <p role="status" className="mt-4 text-sm text-emerald-700">{success}</p>}
      {isLoading ? (
        <p className="mt-5 text-sm text-slate-500">Loading official business requests…</p>
      ) : requests.length === 0 ? (
        <p className="mt-5 rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
          There are no pending official business requests.
        </p>
      ) : (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[1050px] text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-3">Employee</th>
                <th className="px-3 py-3">Schedule</th>
                <th className="px-3 py-3">Destination / purpose</th>
                <th className="px-3 py-3">Approve minutes</th>
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
                      <p className="mt-1 text-xs text-slate-500">{request.employee_code} · {request.request_no}</p>
                    </td>
                    <td className="px-3 py-4 text-xs text-slate-600">
                      <p>{formatManilaDateTime(request.start_at)}</p>
                      <p className="mt-1">to {formatManilaDateTime(request.end_at)}</p>
                      <p className="mt-1 font-semibold text-slate-700">{formatDuration(request.requested_minutes)} requested</p>
                    </td>
                    <td className="px-3 py-4 text-xs text-slate-600">
                      <p className="font-semibold text-slate-800">{request.destination}</p>
                      <p className="mt-1 max-w-sm whitespace-pre-line">{request.purpose}</p>
                      {[request.client_name, request.jo_reference && `JO ${request.jo_reference}`, request.geofence_name, request.vehicle_label]
                        .filter(Boolean).length > 0 && (
                        <p className="mt-1 text-slate-500">
                          {[request.client_name, request.jo_reference && `JO ${request.jo_reference}`, request.geofence_name, request.vehicle_label]
                            .filter(Boolean).join(' · ')}
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-4">
                      <label className="text-xs text-slate-500">
                        Approved minutes
                        <input
                          type="number"
                          min={1}
                          max={request.requested_minutes}
                          step={1}
                          value={getDraft(request)}
                          disabled={isSaving}
                          onChange={(event) => {
                            const value = Math.round(Number(event.target.value))
                            setDrafts((current) => ({
                              ...current,
                              [request.id]: Math.min(request.requested_minutes, Math.max(0, Number.isFinite(value) ? value : 0)),
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
                          onClick={() => void decide(request, 'APPROVED')}
                          className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          disabled={isSaving}
                          onClick={() => void decide(request, 'REJECTED')}
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
