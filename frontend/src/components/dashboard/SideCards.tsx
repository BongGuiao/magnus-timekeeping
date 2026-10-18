import type { Announcement, Holiday, LeaveRequest } from '../../types/dashboard'
import type { SupervisorPendingLeave } from '../../lib/leaveApi'
import { formatLeaveBalance } from '../../lib/leaveApi'

export function LeaveRequestsCard({ requests, onApply }: { requests: LeaveRequest[]; onApply?: () => void }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-500">My Leave Requests</h2>
      <ul className="mt-3 space-y-1.5">
        {requests.length === 0 && <p className="text-sm text-slate-400">No leave requests yet.</p>}
        {requests.map((req) => (
          <li key={req.id} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-1.5">
            <div>
              <p className="text-xs font-medium text-slate-800">{req.type}</p>
              <p className="text-xs text-slate-500">
                {req.startDate} to {req.endDate}
              </p>
            </div>
            <span className={`rounded-full px-2 py-1 text-[11px] font-medium capitalize ${
              ['APPROVED'].includes(req.status.toUpperCase())
                ? 'bg-emerald-50 text-emerald-700'
                : ['REJECTED', 'CANCELLED', 'CANCELED'].includes(req.status.toUpperCase())
                  ? 'bg-rose-50 text-rose-700'
                  : ['DRAFT'].includes(req.status.toUpperCase())
                    ? 'bg-slate-100 text-slate-600'
                    : 'bg-amber-50 text-amber-700'
            }`}>
              {req.status.toLowerCase().replaceAll('_', ' ')}
            </span>
          </li>
        ))}
      </ul>
      {onApply && (
        <button
          type="button"
          onClick={onApply}
          className="mt-4 w-full rounded-lg border border-indigo-200 px-4 py-2 text-sm font-semibold text-indigo-600 transition hover:bg-indigo-50"
        >
          + Apply for Leave
        </button>
      )}
    </div>
  )
}

export function SupervisorPendingLeavesCard({
  applications,
  isLoading,
  error,
}: {
  applications: SupervisorPendingLeave[]
  isLoading: boolean
  error: string | null
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-500">Pending Team Leave</h2>
        <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-bold text-amber-700">
          {applications.length} pending
        </span>
      </div>
      {error && <p role="alert" className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p>}
      {isLoading ? (
        <p className="mt-3 text-sm text-slate-500">Loading pending leave applications…</p>
      ) : applications.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">No pending leave applications for your team.</p>
      ) : (
        <ul className="mt-3 max-h-[32rem] space-y-3 overflow-y-auto">
          {applications.map((application) => (
            <li key={application.id} className="rounded-lg border border-slate-100 p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-800">{application.employee_name}</p>
                  <p className="text-xs text-slate-500">{application.employee_no} · {application.application_no}</p>
                </div>
                <span className="shrink-0 rounded-full bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-700">
                  {application.status.toLowerCase().replaceAll('_', ' ')}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-700">
                {application.leave_type_name} · {formatLeaveBalance(application.requested_minutes, application.unit_type)}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {new Date(application.start_at).toLocaleString()} – {new Date(application.end_at).toLocaleString()}
              </p>
              <p className="mt-2 line-clamp-2 text-xs text-slate-600">{application.reason}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function HolidaysCard({
  holidays,
  isLoading = false,
  error,
}: {
  holidays: Holiday[]
  isLoading?: boolean
  error?: string | null
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-500">Upcoming Holidays</h2>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>
      ) : isLoading ? (
        <p className="mt-3 text-sm text-slate-500">Loading upcoming holidays…</p>
      ) : !Array.isArray(holidays) || holidays.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">No upcoming holidays.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {holidays.map((holiday) => {
            const date = new Date(`${holiday.date}T00:00:00+08:00`)
            const formattedDate = Number.isNaN(date.getTime())
              ? holiday.date
              : date.toLocaleDateString('en-PH', {
                timeZone: 'Asia/Manila',
                month: 'short',
                day: 'numeric',
                year: 'numeric',
              })
            return (
              <li key={`${holiday.date}-${holiday.name}`} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-slate-700">{holiday.name}</span>
                <span className="shrink-0 text-xs text-slate-400">{formattedDate}</span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export function AnnouncementsCard({
  announcements,
  isLoading = false,
  error,
}: {
  announcements: Announcement[]
  isLoading?: boolean
  error?: string | null
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-500">Announcements</h2>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>
      ) : isLoading ? (
        <p className="mt-3 text-sm text-slate-500">Loading announcements…</p>
      ) : !Array.isArray(announcements) || announcements.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">No announcements.</p>
      ) : (
        <ul className="mt-3 space-y-3">
          {announcements.map((announcement) => (
            <li key={announcement.id}>
              <p className="text-sm font-medium text-slate-800">{announcement.title}</p>
              {announcement.body && <p className="mt-1 whitespace-pre-line text-xs leading-5 text-slate-600">{announcement.body}</p>}
              <p className="text-xs text-slate-400">
                {new Date(announcement.postedAt).toLocaleDateString('en-PH', {
                  timeZone: 'Asia/Manila',
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                })}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
