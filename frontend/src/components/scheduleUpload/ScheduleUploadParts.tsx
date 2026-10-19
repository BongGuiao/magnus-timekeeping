import type { ScheduleUploadBatch, ScheduleUploadBatchStatus } from '../../lib/scheduleUploadApi'
import { SCHEDULE_UPLOAD_STATUS_LABELS } from '../../lib/scheduleUploadApi'
import { formatDateTime, formatPeriod } from '../../lib/scheduleUploadFormat'

const STATUS_STYLES: Record<ScheduleUploadBatchStatus, string> = {
  PENDING_APPROVAL: 'bg-amber-50 text-amber-700 ring-amber-200',
  APPROVED: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  REJECTED: 'bg-rose-50 text-rose-700 ring-rose-200',
  CANCELLED: 'bg-slate-100 text-slate-600 ring-slate-200',
}

export function ScheduleUploadStatusBadge({ status }: { status: ScheduleUploadBatchStatus }) {
  return (
    <span className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${STATUS_STYLES[status]}`}>
      {SCHEDULE_UPLOAD_STATUS_LABELS[status]}
    </span>
  )
}

export function ScheduleUploadBatchDetails({ batch }: { batch: ScheduleUploadBatch }) {
  return (
    <div className="space-y-3">
      <dl className="grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-slate-500">Batch</dt>
          <dd className="font-semibold text-slate-800">{batch.batch_no}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Supervisor</dt>
          <dd className="font-semibold text-slate-800">{batch.supervisor_name}</dd>
        </div>
        <div>
          <dt className="text-slate-500">File</dt>
          <dd className="break-all font-semibold text-slate-800">{batch.file_name}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Status</dt>
          <dd><ScheduleUploadStatusBadge status={batch.status} /></dd>
        </div>
        <div>
          <dt className="text-slate-500">Submitted</dt>
          <dd className="text-slate-800">{formatDateTime(batch.submitted_at)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Reviewed</dt>
          <dd className="text-slate-800">{formatDateTime(batch.reviewed_at)}</dd>
        </div>
        {batch.review_remarks && (
          <div className="sm:col-span-2">
            <dt className="text-slate-500">Remarks</dt>
            <dd className="text-slate-800">{batch.review_remarks}</dd>
          </div>
        )}
      </dl>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full min-w-[760px] text-left text-xs">
          <thead className="bg-slate-50 uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Row</th>
              <th className="px-3 py-2">Employee</th>
              <th className="px-3 py-2">Schedule</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Period</th>
              <th className="px-3 py-2">Rest days</th>
              <th className="px-3 py-2">Reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {batch.rows.map((row) => (
              <tr key={row.row_no}>
                <td className="px-3 py-2 text-slate-500">{row.row_no}</td>
                <td className="px-3 py-2">
                  <p className="font-medium text-slate-800">{row.employee_name}</p>
                  <p className="text-[11px] text-slate-500">{row.employee_code}</p>
                </td>
                <td className="px-3 py-2">{row.schedule_code}</td>
                <td className="px-3 py-2">{row.assignment_type}</td>
                <td className="whitespace-nowrap px-3 py-2">{formatPeriod(row.effective_from, row.effective_to)}</td>
                <td className="px-3 py-2">{row.rest_day_pattern_code ?? '—'}</td>
                <td className="px-3 py-2 text-slate-600">{row.reason ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
