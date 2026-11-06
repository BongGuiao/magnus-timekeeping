import { useEffect, useState } from 'react'
import { apiClient } from '../../lib/apiClient'
import { getAttendanceErrorMessage } from '../../lib/attendanceApi'
import type { ApiSuccessEnvelope } from '../../types/auth'

interface Deadline {
  cutoff_id: string
  cutoff_code: string
  period_start: string
  period_end: string
  employee_filing_deadline: string | null
  attendance_deadline: string | null
  attendance_finalized_at: string | null
  locked_at: string | null
  status: string
}

export default function AttendanceDeadlines({ scope = 'own' }: { scope?: 'own' | 'team' }) {
  const [deadlines, setDeadlines] = useState<Deadline[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    let current = true
    apiClient.get<ApiSuccessEnvelope<Deadline[]>>('/attendance/reports/attendance-deadlines', { params: { scope } })
      .then(({ data }) => {
        if (!Array.isArray(data.data)) throw new Error('Invalid attendance deadlines response.')
        if (current) {
          setDeadlines(data.data)
          setError('')
          setLoading(false)
        }
      })
      .catch((cause: unknown) => {
        if (current) {
          setError(getAttendanceErrorMessage(cause, 'Could not load attendance deadlines.'))
          setLoading(false)
        }
      })
    const timer = window.setInterval(() => setNow(Date.now()), 60_000)
    return () => { current = false; window.clearInterval(timer) }
  }, [scope])

  if (error) return <p role="alert" className="mb-4 text-sm text-rose-700">{error}</p>
  if (loading) return <p role="status" className="mb-4 text-sm text-slate-500">Loading attendance deadlines...</p>
  if (!deadlines.length) return null

  function format(value: string | null) {
    return value ? new Date(value).toLocaleString('en-PH', { timeZone: 'Asia/Manila' }) : 'Not set'
  }

  return (
    <details className="mb-4 rounded-lg border border-indigo-100 bg-indigo-50 p-3 text-sm">
      <summary className="cursor-pointer font-semibold text-slate-800">Attendance filing and approval deadlines (Philippine time)</summary>
      <p className="mt-2 text-slate-600">
        Employees file before the filing deadline; assigned approvers decide before the approval deadline.
        Finalized or locked attendance cannot be changed.
      </p>
      <ul className="mt-2 max-h-48 space-y-2 overflow-y-auto">
        {deadlines.map((deadline) => {
          const filing = deadline.employee_filing_deadline ?? deadline.attendance_deadline
          const closed = Boolean(deadline.attendance_finalized_at || deadline.locked_at || deadline.status.toUpperCase() === 'LOCKED')
          const filingClosed = closed || Boolean(filing && now > new Date(filing).getTime())
          const approvalClosed = closed || Boolean(deadline.attendance_deadline && now > new Date(deadline.attendance_deadline).getTime())
          return (
            <li key={deadline.cutoff_id}>
              <strong>{deadline.cutoff_code}</strong> ({deadline.period_start} to {deadline.period_end})
              <div>Filing: {format(filing)} {filingClosed ? '(closed)' : ''} | Approval: {format(deadline.attendance_deadline)} {approvalClosed ? '(closed)' : ''}</div>
            </li>
          )
        })}
      </ul>
    </details>
  )
}
