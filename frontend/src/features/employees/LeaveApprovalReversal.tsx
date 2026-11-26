import { useState, type FormEvent } from 'react'
import { getManilaDate } from '../../lib/employeeRelatedApi'
import { fetchApprovedLeaveForReversal, returnLeaveForApproval, type ApprovedLeaveReversalPage } from '../../lib/leaveApi'

export default function LeaveApprovalReversal() {
  const [open, setOpen] = useState(false)
  const [fromDate, setFromDate] = useState(() => `${getManilaDate().slice(0, 7)}-01`)
  const [toDate, setToDate] = useState(getManilaDate)
  const [range, setRange] = useState<{ from: string; to: string } | null>(null)
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<ApprovedLeaveReversalPage | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function load(from: string, to: string, nextOffset: number) {
    setLoading(true)
    setError('')
    try {
      const result = await fetchApprovedLeaveForReversal(from, to, nextOffset)
      setPage(result)
      setRange({ from, to })
      setOffset(nextOffset)
      setSelected(null)
      setReason('')
    } catch (cause) {
      setPage(null)
      setError(cause instanceof Error ? cause.message : 'Could not load approved leave.')
    } finally {
      setLoading(false)
    }
  }

  function search(event: FormEvent) {
    event.preventDefault()
    setMessage('')
    void load(fromDate, toDate, 0)
  }

  async function reverse() {
    const item = page?.items.find((entry) => entry.id === selected)
    if (!item || !reason.trim() || loading) return
    if (!window.confirm(`Return ${item.application_no} for approval and restore its paid leave balance?`)) return
    setLoading(true)
    setError('')
    setMessage('')
    try {
      await returnLeaveForApproval(item.id, reason.trim())
      setPage((current) => current && { ...current, items: current.items.filter((entry) => entry.id !== item.id) })
      setSelected(null)
      setReason('')
      setMessage(`${item.application_no} was returned for approval. Recalculate affected payroll results if needed.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not return the application.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="mt-4 rounded-xl border border-indigo-200 bg-white p-4 shadow-sm" aria-label="Return approved leave">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="font-bold text-slate-900">
        Return approved leave for approval <span className="ml-2 text-sm font-medium text-indigo-700">{open ? 'Hide' : 'View'}</span>
      </button>
      {open && <div className="mt-3 space-y-3">
        <p className="text-sm text-slate-600">Returning leave restores its paid balance and sends it to the current org-unit approver. Approval deadlines and finalized payroll cutoffs still apply. You cannot return your own leave.</p>
        <form onSubmit={search} className="flex flex-wrap items-end gap-3">
          <label className="text-sm">From <input required type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} className="ml-1 rounded border p-1" /></label>
          <label className="text-sm">To <input required type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} className="ml-1 rounded border p-1" /></label>
          <button disabled={loading} className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">Search</button>
        </form>
        {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
        {message && <p role="status" className="text-sm text-emerald-700">{message}</p>}
        {page && <>
          {page.items.length === 0 ? <p className="text-sm text-slate-500">No approved leave on this page.</p> :
            <div className="overflow-x-auto"><table className="w-full min-w-[700px] text-left text-sm">
              <thead><tr><th>Application</th><th>Employee</th><th>Leave</th><th>Coverage</th><th>Paid minutes</th><th /></tr></thead>
              <tbody>{page.items.map((item) => <tr key={item.id} className="border-t border-slate-100">
                <td>{item.application_no}</td><td>{item.employee_name} ({item.employee_no})</td><td>{item.leave_type}</td>
                <td>{new Date(item.start_at).toLocaleString('en-PH', { timeZone: 'Asia/Manila' })} – {new Date(item.end_at).toLocaleString('en-PH', { timeZone: 'Asia/Manila' })}</td>
                <td>{item.paid_minutes}</td>
                <td><button type="button" disabled={loading} onClick={() => { setSelected(item.id); setReason('') }} className="text-indigo-700 underline">Select</button></td>
              </tr>)}</tbody>
            </table></div>}
          <div className="flex gap-2">
            <button type="button" disabled={loading || offset === 0} onClick={() => range && void load(range.from, range.to, Math.max(0, offset - 25))} className="rounded border px-3 py-1 text-sm disabled:opacity-50">Previous</button>
            <button type="button" disabled={loading || page.next_offset === null} onClick={() => range && page.next_offset !== null && void load(range.from, range.to, page.next_offset)} className="rounded border px-3 py-1 text-sm disabled:opacity-50">Next</button>
          </div>
          {selected && <div className="space-y-2 rounded border p-3">
            <label className="block text-sm" htmlFor="leave-reversal-reason">Reason for returning {page.items.find((item) => item.id === selected)?.application_no}</label>
            <textarea id="leave-reversal-reason" maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} className="w-full rounded border p-2" />
            <button type="button" disabled={loading || !reason.trim()} onClick={() => void reverse()} className="rounded bg-rose-700 px-3 py-1 text-sm text-white disabled:opacity-50">Return for approval</button>
          </div>}
        </>}
      </div>}
    </section>
  )
}
