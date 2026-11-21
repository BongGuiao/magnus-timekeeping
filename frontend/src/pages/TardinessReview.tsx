import { useEffect, useState } from 'react'
import { AlertTriangle, CalendarDays, ClipboardList, Clock3, FileSearch, Info, RefreshCw, UsersRound } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { fetchTardinessReview, type TardinessReview } from '../lib/tardinessReviewApi'
import { formatManilaDateTime } from '../lib/officialBusinessApi'
import NoticeTemplates from '../components/attendance/NoticeTemplates'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

function formatDate(value: string): string {
  const [year, month, day] = value.split('-')
  return `${month}/${day}/${year}`
}

function formatDateList(values: string[]): string {
  return values.map(formatDate).join(', ')
}

export default function TardinessReviewPage({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [review, setReview] = useState<TardinessReview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshVersion, setRefreshVersion] = useState(0)

  useEffect(() => {
    let active = true
    fetchTardinessReview()
      .then((result) => {
        if (active) setReview(result)
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : 'Could not load the tardiness review.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [refreshVersion])

  function refreshReview() {
    setLoading(true)
    setError('')
    setReview(null)
    setRefreshVersion((current) => current + 1)
  }

  const flaggedCount = review?.candidates.filter(
    (candidate) => candidate.duplicate_dates.length > 0 || candidate.pending_correction_dates.length > 0,
  ).length ?? 0

  return (
    <div className="min-h-screen bg-slate-50/80">
      <TopNav employeeName={employeeName} activeView="tardiness-review" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto max-w-7xl space-y-6 px-4 py-7 sm:px-6 sm:py-9 lg:px-8">
        <header className="flex flex-wrap items-end justify-between gap-5">
          <div className="flex items-start gap-4">
            <div className="hidden h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm sm:flex">
              <ClipboardList className="h-6 w-6" aria-hidden="true" />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-indigo-700">Attendance management</p>
              <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">Tardiness Review</h1>
              <p className="mt-1.5 text-sm text-slate-600">Review daily attendance for the previous calendar month.</p>
            </div>
          </div>
          <button type="button" onClick={refreshReview} disabled={loading} aria-label="Refresh review"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-indigo-300 hover:text-indigo-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:cursor-not-allowed disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
            Refresh
          </button>
        </header>
        <div className="flex items-start gap-3 rounded-xl border border-blue-100 bg-blue-50/80 px-4 py-3.5 text-sm text-blue-900">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" aria-hidden="true" />
          <p>
            <span className="font-semibold">Read-only preview.</span> Employees with at least four late work dates are shown for HR review.
            No notice or notification is created by this screen. Results can change after attendance corrections.
          </p>
        </div>
        <NoticeTemplates />
        {loading && (
          <div role="status" className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600 shadow-sm">
            <RefreshCw className="h-4 w-4 animate-spin text-indigo-600" aria-hidden="true" />
            Loading tardiness review...
          </div>
        )}
        {error && (
          <div role="alert" className="flex items-start gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <div><p className="font-semibold">Unable to load the review</p><p className="mt-1">{error}</p></div>
          </div>
        )}
        {!loading && review && (
          <>
            <section aria-label="Review summary" className="grid gap-3 sm:grid-cols-3">
              <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600"><CalendarDays className="h-5 w-5" aria-hidden="true" /></span>
                <div>
                  <p className="text-xs font-medium text-slate-500">Review period</p>
                  <p className="mt-1 text-sm font-semibold text-slate-900">{formatDate(review.period_start)} – {formatDate(review.period_end)}</p>
                  <p className="mt-1 text-xs text-slate-500">Calendar month, not payroll cutoff</p>
                </div>
              </div>
              <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-600"><UsersRound className="h-5 w-5" aria-hidden="true" /></span>
                <div>
                  <p className="text-xs font-medium text-slate-500">Employees to review</p>
                  <p className="mt-1 text-xl font-bold leading-none text-slate-900">{review.candidates.length}</p>
                  <p className="mt-1.5 text-xs text-slate-500">At least four late work dates</p>
                </div>
              </div>
              <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-600"><AlertTriangle className="h-5 w-5" aria-hidden="true" /></span>
                <div>
                  <p className="text-xs font-medium text-slate-500">Employees with flags</p>
                  <p className="mt-1 text-xl font-bold leading-none text-slate-900">{flaggedCount}</p>
                  <p className="mt-1.5 text-xs text-slate-500">Duplicates or pending corrections</p>
                </div>
              </div>
            </section>
            <div className="flex flex-wrap items-end justify-between gap-2 border-b border-slate-200 pb-3">
              <div>
                <h2 className="text-base font-bold text-slate-900">Employee attendance</h2>
                <p className="mt-1 text-sm text-slate-500">Review the records and resolve any flagged issues.</p>
              </div>
              <span className="text-xs font-medium text-slate-500">{review.candidates.length} employee{review.candidates.length === 1 ? '' : 's'}</span>
            </div>
            {review.candidates.length === 0 && (
              <div className="rounded-xl border border-dashed border-slate-300 bg-white px-5 py-12 text-center">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-500"><FileSearch className="h-6 w-6" aria-hidden="true" /></div>
                <p className="mt-4 font-semibold text-slate-900">No employees to review</p>
                <p className="mt-1 text-sm text-slate-500">No employees meet the threshold in this period.</p>
              </div>
            )}
            {review.candidates.map((candidate) => (
              <section key={candidate.employee_id} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                <div className="space-y-4 p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 items-start gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600"><UsersRound className="h-5 w-5" aria-hidden="true" /></div>
                      <div className="min-w-0">
                        <h3 className="break-words font-semibold text-slate-900">{candidate.employee_name}</h3>
                        <p className="mt-0.5 text-xs font-medium text-slate-500">Employee no. {candidate.employee_no}</p>
                      </div>
                    </div>
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700">
                      <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />{candidate.late_dates.length} late work dates
                    </span>
                  </div>
                  <p className="text-sm leading-6 text-slate-600">
                    <span className="font-medium text-slate-700">Late dates:</span> {formatDateList(candidate.late_dates)}
                  </p>
                  {(candidate.duplicate_dates.length > 0 || candidate.pending_correction_dates.length > 0) && (
                    <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden="true" />
                      <div className="space-y-1">
                        <p className="font-semibold">Resolve these attendance issues before issuing a notice.</p>
                        {candidate.duplicate_dates.length > 0 && <p>Duplicate records: {formatDateList(candidate.duplicate_dates)}</p>}
                        {candidate.pending_correction_dates.length > 0 && <p>Pending corrections: {formatDateList(candidate.pending_correction_dates)}</p>}
                      </div>
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-1 border-t border-slate-200 bg-slate-50/70 px-5 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">Attendance records</p>
                  <p className="text-xs text-slate-500">Times shown in Philippine time</p>
                </div>
                <div
                  role="region"
                  aria-label={`Attendance records for ${candidate.employee_name}`}
                  tabIndex={0}
                  className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-indigo-600"
                >
                  <table className="w-full min-w-[700px] text-left text-sm">
                    <caption className="sr-only">Attendance records for {candidate.employee_name}</caption>
                    <thead className="border-b border-slate-100 bg-white text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <tr><th scope="col" className="px-5 py-3">Work date</th><th scope="col" className="px-5 py-3">Scheduled start</th><th scope="col" className="px-5 py-3">Actual clock-in</th><th scope="col" className="px-5 py-3">Late minutes</th><th scope="col" className="px-5 py-3">Attendance mode</th></tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 text-slate-700">
                      {candidate.records.map((record) => (
                        <tr key={record.attendance_id} className="hover:bg-slate-50/70">
                          <td className="whitespace-nowrap px-5 py-3 font-medium text-slate-800">{formatDate(record.work_date)}</td>
                          <td className="whitespace-nowrap px-5 py-3">{record.expected_clock_in_at ? formatManilaDateTime(record.expected_clock_in_at) : '—'}</td>
                          <td className="whitespace-nowrap px-5 py-3">{record.clock_in_at ? formatManilaDateTime(record.clock_in_at) : '—'}</td>
                          <td className="px-5 py-3"><span className={record.late_minutes > 0 ? 'font-semibold text-amber-700' : 'text-slate-500'}>{record.late_minutes}</span></td>
                          <td className="px-5 py-3 text-slate-600">{record.attendance_mode === 'SCHEDULE_CREDITED' ? 'Schedule credited' : 'Punch required'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="border-t border-slate-100 px-5 py-2 text-xs text-slate-500 sm:hidden">Scroll horizontally to view all columns.</p>
              </section>
            ))}
          </>
        )}
      </main>
    </div>
  )
}
