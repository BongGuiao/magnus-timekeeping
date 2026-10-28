import { useEffect, useRef, useState } from 'react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { ScheduleUploadBatchDetails, ScheduleUploadStatusBadge } from '../components/scheduleUpload/ScheduleUploadParts'
import { useLogout } from '../hooks/useLogout'
import {
  cancelMyScheduleUpload,
  downloadScheduleUploadTemplate,
  fetchMyScheduleUpload,
  fetchMyScheduleUploads,
  previewScheduleUpload,
  submitScheduleUpload,
} from '../lib/scheduleUploadApi'
import type { ScheduleUploadBatch, ScheduleUploadBatchSummary, ScheduleUploadPreview } from '../lib/scheduleUploadApi'
import { formatDateTime, formatPeriod } from '../lib/scheduleUploadFormat'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const COLUMN_GUIDE: { name: string; required: boolean; description: string }[] = [
  { name: 'employee_code', required: true, description: 'Employee number of one of your direct reports.' },
  { name: 'schedule_code', required: true, description: 'Active schedule template code in the employee’s company.' },
  { name: 'assignment_type', required: true, description: 'For example REGULAR or TEMPORARY.' },
  { name: 'effective_from', required: true, description: 'YYYY-MM-DD, tomorrow or later.' },
  { name: 'effective_to', required: false, description: 'YYYY-MM-DD; leave blank for open-ended.' },
  { name: 'rest_day_pattern_code', required: false, description: 'Active rest day pattern code.' },
  { name: 'reason', required: false, description: 'Up to 500 characters.' },
]

function PreviewTable({ preview }: { preview: ScheduleUploadPreview }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full min-w-[900px] text-left text-xs">
        <thead className="bg-slate-50 uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2">Row</th>
            <th className="px-3 py-2">Employee</th>
            <th className="px-3 py-2">Schedule</th>
            <th className="px-3 py-2">Type</th>
            <th className="px-3 py-2">Period</th>
            <th className="px-3 py-2">Rest days</th>
            <th className="px-3 py-2">Result</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {preview.rows.map((row) => (
            <tr key={row.row_no} className={row.is_valid ? '' : 'bg-rose-50/60'}>
              <td className="px-3 py-2 align-top text-slate-500">{row.row_no}</td>
              <td className="px-3 py-2 align-top">
                <p className="font-medium text-slate-800">{row.employee_name ?? row.employee_code}</p>
                {row.employee_name && <p className="text-[11px] text-slate-500">{row.employee_code}</p>}
              </td>
              <td className="px-3 py-2 align-top">
                <p>{row.schedule_code}</p>
                {row.schedule_name && <p className="text-[11px] text-slate-500">{row.schedule_name}</p>}
              </td>
              <td className="px-3 py-2 align-top">{row.assignment_type}</td>
              <td className="whitespace-nowrap px-3 py-2 align-top">{formatPeriod(row.effective_from, row.effective_to)}</td>
              <td className="px-3 py-2 align-top">{row.rest_day_pattern_code ?? '—'}</td>
              <td className="px-3 py-2 align-top">
                {row.errors.length > 0 ? (
                  <ul className="list-disc space-y-0.5 pl-4 text-rose-700">
                    {row.errors.map((message) => <li key={message}>{message}</li>)}
                  </ul>
                ) : (
                  <>
                    <p className="font-semibold text-emerald-700">OK</p>
                    {row.effects.length > 0 && (
                      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-amber-700">
                        {row.effects.map((message) => <li key={message}>{message}</li>)}
                      </ul>
                    )}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function ScheduleUploads({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const fileInput = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ScheduleUploadPreview | null>(null)
  const [batches, setBatches] = useState<ScheduleUploadBatchSummary[]>([])
  const [selected, setSelected] = useState<ScheduleUploadBatch | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let isCurrent = true
    fetchMyScheduleUploads()
      .then((result) => {
        if (isCurrent) setBatches(result)
      })
      .catch((cause: unknown) => {
        if (isCurrent) setError(cause instanceof Error ? cause.message : 'Could not load your schedule uploads.')
      })
      .finally(() => {
        if (isCurrent) setLoading(false)
      })
    return () => {
      isCurrent = false
    }
  }, [refreshKey])

  const reloadBatches = () => setRefreshKey((current) => current + 1)

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

  function chooseFile(next: File | null) {
    setFile(next)
    setPreview(null)
    setError('')
    setSuccess('')
  }

  const downloadTemplate = () => run(async () => {
    const blob = await downloadScheduleUploadTemplate()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'schedule_upload_template.csv'
    link.click()
    URL.revokeObjectURL(url)
  })

  const checkFile = () => run(async () => {
    if (!file) return
    setPreview(await previewScheduleUpload(file))
  })

  const submitFile = () => run(async () => {
    if (!file) return
    const batch = await submitScheduleUpload(file)
    setSuccess(`Batch ${batch.batch_no} was approved and applied successfully.`)
    setFile(null)
    setPreview(null)
    if (fileInput.current) fileInput.current.value = ''
    setSelected(batch)
    reloadBatches()
  })

  const openBatch = (batchId: string) => run(async () => {
    setSelected(selected?.id === batchId ? null : await fetchMyScheduleUpload(batchId))
  })

  const cancelBatch = (batch: ScheduleUploadBatchSummary) => run(async () => {
    if (!window.confirm(`Cancel batch ${batch.batch_no}? It will not be applied.`)) return
    await cancelMyScheduleUpload(batch.id)
    setSuccess(`Batch ${batch.batch_no} was cancelled.`)
    setSelected(null)
    reloadBatches()
  })

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="schedule-uploads" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full space-y-4 px-4 py-6 sm:px-6 lg:px-8">
        <header>
          <h1 className="text-xl font-bold text-slate-900">Team Schedule Upload</h1>
          <p className="mt-1 text-xs text-slate-600">
            Upload schedules for your direct reports as a CSV file. After successful validation, the batch is approved
            and applied immediately. A new schedule ends or pauses the employee’s current schedule automatically.
          </p>
        </header>

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-bold text-slate-900">1. Prepare the file</h2>
              <p className="text-xs text-slate-500">One row per employee schedule. Save as CSV (UTF-8 or Excel CSV).</p>
            </div>
            <button
              type="button"
              onClick={() => void downloadTemplate()}
              disabled={busy}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Download template
            </button>
          </div>
          <ul className="mt-3 grid gap-1 text-xs text-slate-600 sm:grid-cols-2">
            {COLUMN_GUIDE.map((column) => (
              <li key={column.name}>
                <code className="font-semibold text-slate-800">{column.name}</code>
                {column.required ? <span className="text-rose-600"> *</span> : null} — {column.description}
              </li>
            ))}
          </ul>
        </section>

        <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div>
            <h2 className="text-sm font-bold text-slate-900">2. Check and submit</h2>
            <p className="text-xs text-slate-500">The whole file is rejected if any row has an error, so fix every row before submitting.</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
              className="text-xs file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-xs file:font-semibold"
            />
            <button
              type="button"
              onClick={() => void checkFile()}
              disabled={!file || busy}
              className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
            >
              Check file
            </button>
            <button
              type="button"
              onClick={() => void submitFile()}
              disabled={!file || !preview?.is_valid || busy}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              Submit and apply schedules
            </button>
          </div>
          {preview && (
            <div className="space-y-3">
              <p className={`text-xs font-semibold ${preview.is_valid ? 'text-emerald-700' : 'text-rose-700'}`}>
                {preview.is_valid
                  ? `All ${preview.rows.length} row(s) are valid. Review the effects below, then submit.`
                  : `${preview.error_count} error(s) found. Correct the file and check it again.`}
              </p>
              {preview.file_errors.length > 0 && (
                <ul className="list-disc space-y-0.5 rounded-lg border border-rose-200 bg-rose-50 py-2 pl-8 pr-3 text-xs text-rose-700">
                  {preview.file_errors.map((message) => <li key={message}>{message}</li>)}
                </ul>
              )}
              {preview.rows.length > 0 && <PreviewTable preview={preview} />}
            </div>
          )}
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-5 py-3">
            <h2 className="text-sm font-bold text-slate-900">My uploads</h2>
          </div>
          {loading ? (
            <p role="status" className="px-5 py-6 text-xs text-slate-500">Loading uploads…</p>
          ) : batches.length === 0 ? (
            <p className="px-5 py-6 text-xs text-slate-500">You have not uploaded any schedules yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-xs">
                <thead className="bg-slate-50 uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Batch</th>
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
                      <td className="break-all px-4 py-2">{batch.file_name}</td>
                      <td className="px-4 py-2">{batch.row_count}</td>
                      <td className="whitespace-nowrap px-4 py-2">{formatDateTime(batch.submitted_at)}</td>
                      <td className="px-4 py-2"><ScheduleUploadStatusBadge status={batch.status} /></td>
                      <td className="space-x-2 whitespace-nowrap px-4 py-2">
                        <button
                          type="button"
                          onClick={() => void openBatch(batch.id)}
                          disabled={busy}
                          className="rounded-md border border-slate-300 px-2.5 py-1 font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                        >
                          {selected?.id === batch.id ? 'Hide' : 'View'}
                        </button>
                        {batch.status === 'PENDING_APPROVAL' && (
                          <button
                            type="button"
                            onClick={() => void cancelBatch(batch)}
                            disabled={busy}
                            className="rounded-md border border-rose-200 px-2.5 py-1 font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                          >
                            Cancel
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {selected && (
            <div className="border-t border-slate-200 p-5">
              <ScheduleUploadBatchDetails batch={selected} />
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
