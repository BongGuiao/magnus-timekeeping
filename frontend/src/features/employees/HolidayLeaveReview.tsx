import { useState, type FormEvent } from 'react'
import { getManilaDate } from '../../lib/employeeRelatedApi'
import { fetchHolidayLeaveReview, type HolidayLeaveReview } from '../../lib/leaveApi'

export default function HolidayLeaveReview() {
  const [open, setOpen] = useState(false)
  const [fromDate, setFromDate] = useState(() => `${getManilaDate().slice(0, 7)}-01`)
  const [toDate, setToDate] = useState(getManilaDate)
  const [result, setResult] = useState<HolidayLeaveReview | null>(null)
  const [offset, setOffset] = useState(0)
  const [loadedRange, setLoadedRange] = useState<{ from: string; to: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function load(from: string, to: string, pageOffset: number) {
    setLoading(true)
    setError('')
    try {
      const data = await fetchHolidayLeaveReview(from, to, pageOffset)
      setResult(data)
      setOffset(pageOffset)
      setLoadedRange({ from, to })
    } catch (cause) {
      setResult(null)
      setError(cause instanceof Error ? cause.message : 'Could not load the holiday leave review.')
    } finally {
      setLoading(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    void load(fromDate, toDate, 0)
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="font-semibold text-indigo-700">
        {open ? 'Hide' : 'Review'} potentially affected holiday leave
      </button>
      {open && <div className="mt-4 space-y-3">
        <p className="text-sm text-slate-600">
          Read-only review of approved, paid leave using currently published calendars and assignments.
          Dates are potential matches, not confirmed over-deductions. Older or missing calendar and assignment records
          may be unavailable, so results can be incomplete. No balances or payroll records are changed.
        </p>
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <label className="text-sm">From <input required type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} className="ml-1 rounded border p-1" /></label>
          <label className="text-sm">To <input required type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} className="ml-1 rounded border p-1" /></label>
          <button disabled={loading} className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">{loading ? 'Loading…' : 'Review'}</button>
        </form>
        {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
        {result && <>
          <p className="text-xs text-slate-500">Applications scanned {offset + 1} onward for {loadedRange?.from} to {loadedRange?.to}. A page may be empty even when later pages contain matches.</p>
          {result.items.length === 0 ? <p className="text-sm text-slate-500">No potential matches on this page.</p> : (
            <div className="overflow-x-auto"><table className="w-full text-left text-sm">
              <thead><tr><th>Application</th><th>Employee</th><th>Leave type</th><th>Holiday dates</th><th>Paid minutes</th><th>Review basis</th></tr></thead>
              <tbody>{result.items.map((item) => <tr key={item.application_no} className="border-t border-slate-100">
                <td>{item.application_no}</td><td>{item.employee_no} — {item.employee_name}</td>
                <td>{item.leave_type}</td><td>{item.holiday_dates.join(', ')}</td><td>{item.paid_minutes}</td>
                <td>{item.has_daily_breakdown ? 'Daily records' : 'Application dates; allocation unknown'}</td>
              </tr>)}</tbody>
            </table></div>
          )}
          <div className="flex gap-2">
            <button type="button" disabled={loading || offset === 0} onClick={() => loadedRange && void load(loadedRange.from, loadedRange.to, Math.max(0, offset - 25))} className="rounded border px-3 py-1 text-sm disabled:opacity-50">Previous</button>
            <button type="button" disabled={loading || result.next_offset === null} onClick={() => loadedRange && result.next_offset !== null && void load(loadedRange.from, loadedRange.to, result.next_offset)} className="rounded border px-3 py-1 text-sm disabled:opacity-50">Next</button>
          </div>
        </>}
      </div>}
    </section>
  )
}
