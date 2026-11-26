import { useState, type FormEvent } from 'react'
import { CalendarDays, ClipboardCheck, Info } from 'lucide-react'
import { getManilaDate } from '../../lib/employeeRelatedApi'
import { fetchApprovedLeaveForReversal, returnLeaveForApproval, type ApprovedLeaveReversalPage } from '../../lib/leaveApi'

export default function LeaveApprovalReversal() {
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
    <section id="hr-leave-reversal" className="mt-4 overflow-hidden rounded-xl border border-indigo-100 bg-white shadow-sm" aria-label="Return approved leave">
      <header className="flex items-start gap-3 border-b border-indigo-100 bg-gradient-to-r from-indigo-50 to-sky-50 px-5 py-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm">
          <ClipboardCheck size={19} aria-hidden="true" />
        </span>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-indigo-600">HR Admin · Leave approvals</p>
          <h2 className="mt-0.5 text-base font-bold text-indigo-950">Return approved leave for approval</h2>
          <p className="mt-1 text-sm text-slate-600">Find an application and return it to the approval queue.</p>
        </div>
      </header>
      <div className="space-y-5 p-5">
        <div className="flex gap-2 rounded-lg border border-sky-100 bg-sky-50 px-3 py-3 text-sm text-sky-900">
          <Info size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <p>Returning leave restores its paid balance and sends it to the current org-unit approver. Approval deadlines and finalized payroll cutoffs still apply. You cannot return your own leave.</p>
        </div>
        <form onSubmit={search} className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="mr-2 flex items-center gap-2 self-center text-sm font-semibold text-slate-700">
            <CalendarDays size={17} className="text-indigo-600" aria-hidden="true" /> Coverage
          </div>
          <label className="flex flex-col gap-1 text-xs font-semibold text-slate-600">
            From
            <input required type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-800 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100" />
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-slate-600">
            To
            <input required type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-800 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100" />
          </label>
          <button disabled={loading} className="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50">Search</button>
        </form>
        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</p>}
        {message && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{message}</p>}
        {page && <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-bold text-slate-800">Approved applications</h3>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">{page.items.length} on this page</span>
          </div>
          {page.items.length === 0 ? <p className="rounded-lg border border-dashed border-slate-200 px-4 py-6 text-center text-sm text-slate-500">No approved leave on this page.</p> :
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full min-w-[850px] text-left text-sm">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr><th scope="col" className="px-4 py-3">Application</th><th scope="col" className="px-4 py-3">Employee</th><th scope="col" className="px-4 py-3">Leave</th><th scope="col" className="px-4 py-3">Coverage</th><th scope="col" className="px-4 py-3">Paid minutes</th><th scope="col" className="px-4 py-3"><span className="sr-only">Action</span></th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">{page.items.map((item) => <tr key={item.id} className={selected === item.id ? 'bg-indigo-50' : 'transition hover:bg-slate-50'}>
                  <td className="px-4 py-3 font-medium text-indigo-700">{item.application_no}</td>
                  <td className="px-4 py-3"><span className="block font-semibold text-slate-800">{item.employee_name}</span><span className="text-xs text-slate-500">{item.employee_no}</span></td>
                  <td className="px-4 py-3 text-slate-700">{item.leave_type}</td>
                  <td className="px-4 py-3 text-slate-600">{new Date(item.start_at).toLocaleString('en-PH', { timeZone: 'Asia/Manila' })}<span className="mx-1 text-slate-400">–</span>{new Date(item.end_at).toLocaleString('en-PH', { timeZone: 'Asia/Manila' })}</td>
                  <td className="px-4 py-3 font-medium tabular-nums text-slate-700">{item.paid_minutes}</td>
                  <td className="px-4 py-3 text-right"><button type="button" disabled={loading} aria-label={`${selected === item.id ? 'Selected' : 'Select'} ${item.application_no}`} onClick={() => { setSelected(item.id); setReason('') }} className="rounded-lg border border-indigo-200 bg-white px-3 py-1.5 text-xs font-semibold text-indigo-700 transition hover:bg-indigo-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50">{selected === item.id ? 'Selected' : 'Select'}</button></td>
                </tr>)}</tbody>
              </table>
            </div>}
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-slate-500">Page {Math.floor(offset / 25) + 1}</span>
            <div className="flex gap-2">
              <button type="button" disabled={loading || offset === 0} onClick={() => range && void load(range.from, range.to, Math.max(0, offset - 25))} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-40">Previous</button>
              <button type="button" disabled={loading || page.next_offset === null} onClick={() => range && page.next_offset !== null && void load(range.from, range.to, page.next_offset)} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-40">Next</button>
            </div>
          </div>
          {selected && <div className="space-y-3 rounded-xl border border-indigo-200 bg-indigo-50/50 p-4">
            <div>
              <h3 className="text-sm font-bold text-indigo-950">Review selected application</h3>
              <p className="mt-1 text-xs text-slate-600">Provide a reason before returning this leave for approval.</p>
            </div>
            <label className="block text-sm font-semibold text-slate-700" htmlFor="leave-reversal-reason">Reason for returning {page.items.find((item) => item.id === selected)?.application_no}</label>
            <textarea id="leave-reversal-reason" rows={3} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} className="w-full rounded-lg border border-slate-300 bg-white p-3 text-sm text-slate-800 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100" />
            <button type="button" disabled={loading || !reason.trim()} onClick={() => void reverse()} className="rounded-lg bg-rose-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-rose-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50">Return for approval</button>
          </div>}
        </>}
      </div>
    </section>
  )
}
