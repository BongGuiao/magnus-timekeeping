import { useEffect, useRef, useState } from 'react'
import type { NavView } from '../../components/dashboard/TopNav'
import {
  fetchUnresolvedApprovals,
  recoverUnresolvedApproval,
  type UnresolvedApproval,
  type UnresolvedApprovals,
  type ApprovalResourceType,
} from '../../lib/attendanceApi'
import { hasPermission } from '../../types/role'

interface Props {
  onNavigate?: (view: NavView) => void
}
const resourceLabels: Record<ApprovalResourceType, string> = {
  overtime_application: 'Overtime', leave_application: 'Leave', official_business_request: 'Official business',
  attendance_correction: 'Attendance correction', invalid_attendance: 'Invalid attendance',
  emergency_schedule_request: 'Emergency schedule', schedule_upload_batch: 'Schedule upload',
}

export default function UnresolvedAttendanceApprovals({ onNavigate }: Props) {
  const [records, setRecords] = useState<UnresolvedApproval[]>([])
  const [approvers, setApprovers] = useState<UnresolvedApprovals['approvers']>([])
  const [canManage, setCanManage] = useState(false)
  const [selections, setSelections] = useState<Record<string, string>>({})
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [loadError, setLoadError] = useState<string | null>(null)
  const [retryError, setRetryError] = useState<string | null>(null)
  const [retryingId, setRetryingId] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const requestVersion = useRef(0)

  useEffect(() => {
    let active = true
    async function refresh() {
      const version = ++requestVersion.current
      try {
        const next = await fetchUnresolvedApprovals()
        if (active && version === requestVersion.current) {
          setRecords(next.records)
          setApprovers(next.approvers)
          setCanManage(next.can_manage)
          setLoadError(null)
        }
      } catch (cause) {
        if (active && version === requestVersion.current) {
          setLoadError(cause instanceof Error ? cause.message : 'Could not load approval routing alerts.')
        }
      }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 30_000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [refreshKey])

  async function retry(attendanceId: string, manual = false) {
    setRetryingId(attendanceId)
    setRetryError(null)
    try {
      await recoverUnresolvedApproval(attendanceId, manual ? selections[attendanceId] : undefined, manual ? reasons[attendanceId] : undefined)
      setRecords((current) => current.filter((record) => record.id !== attendanceId))
    } catch (cause) {
      setRetryError(cause instanceof Error ? cause.message : 'Could not assign an independent approver.')
    } finally {
      requestVersion.current += 1
      setRefreshKey((current) => current + 1)
      setRetryingId(null)
    }
  }

  if (!records.length && !loadError && !retryError) return null

  return (
    <section className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4" aria-label="Approval routing alerts">
      <h2 className="font-bold text-amber-900">
        {records.length ? 'Requests need an approver' : 'Approval routing alerts unavailable'}
      </h2>
      <p className="mt-1 text-sm text-amber-900">
        {records.length
          ? canManage
            ? 'These requests are held pending with unresolved routing. Correct the organization and retry, or assign an independent active manager with an audit reason. This does not approve the request.'
            : 'Your requests are saved, but no independent org-unit manager could be assigned. Contact HR; approval remains pending until HR resolves the routing.'
          : 'The approval routing check could not be completed. This does not confirm that any requests are missing an approver.'}
      </p>
      {records.length > 0 && canManage && hasPermission('company.setup') && onNavigate && (
        <button type="button" onClick={() => onNavigate('org-units')} className="mt-2 text-sm font-semibold text-indigo-700 underline">
          Open org units
        </button>
      )}
      {(loadError || retryError) && (
        <p role="alert" className="mt-2 text-sm font-semibold text-rose-700">{retryError || loadError}</p>
      )}
      {loadError && (
        <button
          type="button"
          onClick={() => setRefreshKey((current) => current + 1)}
          className="mt-2 text-sm font-semibold text-indigo-700 underline"
        >
          Retry loading alerts
        </button>
      )}
      <ul className="mt-3 space-y-2">
        {records.map((record) => (
          <li key={record.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white p-3 text-sm">
            <div>
              <p className="font-semibold text-slate-900">{resourceLabels[record.resource_type]} — {record.employee_name} ({record.employee_code})</p>
              <p className="text-slate-600">{record.routing_error}</p>
            </div>
            {canManage && <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={retryingId !== null}
              onClick={() => void retry(record.id)}
              className="rounded-lg bg-indigo-600 px-3 py-2 font-semibold text-white disabled:opacity-50"
            >
              {retryingId === record.id ? 'Retrying…' : 'Retry routing'}
            </button>
            <select
              aria-label={`Independent approver for ${record.employee_code} ${resourceLabels[record.resource_type]}`}
              value={selections[record.id] ?? ''}
              onChange={(event) => setSelections((current) => ({ ...current, [record.id]: event.target.value }))}
              disabled={retryingId !== null}
              className="max-w-64 rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs"
            >
              <option value="">Select an independent manager</option>
              {approvers.map((approver) => <option key={approver.employee_id} value={approver.employee_id}>{approver.label}</option>)}
            </select>
            {selections[record.id] && <>
              <input
                aria-label={`Assignment reason for ${record.employee_code} ${resourceLabels[record.resource_type]}`}
                placeholder="Reason for exceptional assignment"
                value={reasons[record.id] ?? ''}
                onChange={(event) => setReasons((current) => ({ ...current, [record.id]: event.target.value }))}
                maxLength={1000}
                disabled={retryingId !== null}
                className="rounded-lg border border-slate-300 px-2 py-2 text-xs"
              />
              <button
                type="button"
                disabled={retryingId !== null || !(reasons[record.id] ?? '').trim()}
                onClick={() => void retry(record.id, true)}
                className="rounded-lg bg-indigo-600 px-3 py-2 font-semibold text-white disabled:opacity-50"
              >Assign approver</button>
            </>}
            </div>}
          </li>
        ))}
      </ul>
    </section>
  )
}
