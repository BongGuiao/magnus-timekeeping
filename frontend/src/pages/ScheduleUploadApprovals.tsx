import { useEffect, useState } from 'react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { ScheduleUploadBatchDetails, ScheduleUploadStatusBadge } from '../components/scheduleUpload/ScheduleUploadParts'
import { useLogout } from '../hooks/useLogout'
import {
  SCHEDULE_UPLOAD_STATUS_LABELS,
  approveScheduleUpload,
  fetchScheduleUploadForReview,
  fetchScheduleUploadsForReview,
  rejectScheduleUpload,
} from '../lib/scheduleUploadApi'
import type { ScheduleUploadBatch, ScheduleUploadBatchStatus, ScheduleUploadBatchSummary } from '../lib/scheduleUploadApi'
import { formatDateTime } from '../lib/scheduleUploadFormat'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const STATUS_FILTERS: ScheduleUploadBatchStatus[] = ['PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'CANCELLED']
const MAX_REMARKS_LENGTH = 500

export default function ScheduleUploadApprovals({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [statusFilter, setStatusFilter] = useState<ScheduleUploadBatchStatus>('PENDING_APPROVAL')
  const [batches, setBatches] = useState<ScheduleUploadBatchSummary[]>([])
  const [selected, setSelected] = useState<ScheduleUploadBatch | null>(null)
  const [remarks, setRemarks] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let isCurrent = true
    fetchScheduleUploadsForReview(statusFilter)
      .then((result) => {
        if (isCurrent) setBatches(result)
      })
      .catch((cause: unknown) => {
        if (isCurrent) setError(cause instanceof Error ? cause.message : 'Could not load schedule uploads.')
      })
      .finally(() => {
        if (isCurrent) setLoading(false)
      })
    return () => {
      isCurrent = false
    }
  }, [statusFilter, refreshKey])

  const reloadBatches = () => setRefreshKey((current) => current + 1)

  function changeStatusFilter(status: ScheduleUploadBatchStatus) {
    if (status === statusFilter) return
    setSelected(null)
    setLoading(true)
    setStatusFilter(status)
  }

  async function run(action: () => Promise<void>) {
    setError('')
    setSuccess('')
    setBusy(true)
    try {
      await action()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  const openBatch = (batchId: string) => run(async () => {
    setRemarks('')
    setSelected(selected?.id === batchId ? null : await fetchScheduleUploadForReview(batchId))
  })

  const approve = (batch: ScheduleUploadBatch) => run(async () => {
    if (!window.confirm(`Approve batch ${batch.batch_no}? ${batch.row_count} schedule(s) will take effect immediately.`)) return
    await approveScheduleUpload(batch.id, remarks)
    setSuccess(`Batch ${batch.batch_no} was approved and the schedules were applied.`)
    setSelected(null)
    reloadBatches()
  })

  const reject = (batch: ScheduleUploadBatch) => run(async () => {
    if (!remarks.trim()) {
      setError('Enter the reason for rejecting this batch so the supervisor can correct it.')
      return
    }
    await rejectScheduleUpload(batch.id, remarks.trim())
    setSuccess(`Batch ${batch.batch_no} was rejected.`)
    setSelected(null)
    reloadBatches()
  })

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="schedule-upload-approvals" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] max-w-7xl space-y-4 py-6">
        <header>
          <h1 className="text-xl font-bold text-slate-900">Schedule Upload Approvals</h1>
          <p className="mt-1 text-xs text-slate-600">
            Review schedule batches uploaded by supervisors. Approving re-checks every row and applies the whole batch;
            the employees’ overlapping schedules are ended or paused automatically. You cannot approve your own uploads.
          </p>
        </header>

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}

        <div role="tablist" aria-label="Batch status" className="flex flex-wrap gap-2">
          {STATUS_FILTERS.map((status) => (
            <button
              key={status}
              type="button"
              role="tab"
              aria-selected={statusFilter === status}
              onClick={() => changeStatusFilter(status)}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
                statusFilter === status ? 'bg-slate-900 text-white' : 'border border-slate-300 bg-white text-slate-700'
              }`}
            >
              {SCHEDULE_UPLOAD_STATUS_LABELS[status]}
            </button>
          ))}
        </div>

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          {loading ? (
            <p role="status" className="px-5 py-6 text-xs text-slate-500">Loading batches…</p>
          ) : batches.length === 0 ? (
            <p className="px-5 py-6 text-xs text-slate-500">No batches with this status.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-xs">
                <thead className="bg-slate-50 uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Batch</th>
                    <th className="px-4 py-2">Supervisor</th>
                    <th className="px-4 py-2">File</th>
                    <th className="px-4 py-2">Rows</th>
                    <th className="px-4 py-2">Submitted</th>
                    <th className="px-4 py-2">Status</th>
                    <th className="px-4 py-2">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {batches.map((batch) => (
                    <tr key={batch.id} className={selected?.id === batch.id ? 'bg-indigo-50/50' : ''}>
                      <td className="px-4 py-2 font-semibold text-slate-800">{batch.batch_no}</td>
                      <td className="px-4 py-2">{batch.supervisor_name}</td>
                      <td className="break-all px-4 py-2">{batch.file_name}</td>
                      <td className="px-4 py-2">{batch.row_count}</td>
                      <td className="whitespace-nowrap px-4 py-2">{formatDateTime(batch.submitted_at)}</td>
                      <td className="px-4 py-2"><ScheduleUploadStatusBadge status={batch.status} /></td>
                      <td className="px-4 py-2">
                        <button
                          type="button"
                          onClick={() => void openBatch(batch.id)}
                          disabled={busy}
                          className="rounded-md border border-slate-300 px-2.5 py-1 font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                        >
                          {selected?.id === batch.id ? 'Hide' : batch.status === 'PENDING_APPROVAL' ? 'Review' : 'View'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {selected && (
            <div className="space-y-4 border-t border-slate-200 p-5">
              <ScheduleUploadBatchDetails batch={selected} />
              {selected.status === 'PENDING_APPROVAL' && (
                <div className="space-y-3">
                  <label className="block text-xs font-semibold text-slate-700" htmlFor="schedule-upload-remarks">
                    Remarks <span className="font-normal text-slate-500">(required when rejecting)</span>
                  </label>
                  <textarea
                    id="schedule-upload-remarks"
                    value={remarks}
                    maxLength={MAX_REMARKS_LENGTH}
                    onChange={(event) => setRemarks(event.target.value)}
                    rows={3}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                  <div className="flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={() => void approve(selected)}
                      disabled={busy}
                      className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                    >
                      Approve and apply
                    </button>
                    <button
                      type="button"
                      onClick={() => void reject(selected)}
                      disabled={busy}
                      className="rounded-lg border border-rose-300 bg-white px-4 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
