import { useEffect, useRef, useState } from 'react'
import { apiClient } from '../../lib/apiClient'
import { getAttendanceErrorMessage } from '../../lib/attendanceApi'
import type { ApiSuccessEnvelope } from '../../types/auth'

interface AbsenceAlert {
  id: string
  employee_no: string
  employee_name: string
  absence_dates: string[]
  resolved_at: string | null
}

export function useAbsenceAlerts() {
  const [alerts, setAlerts] = useState<AbsenceAlert[]>([])
  const [error, setError] = useState<string | null>(null)
  const [dismissing, setDismissing] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const request = useRef(0)

  async function refresh() {
    const id = ++request.current
    try {
      const response = await apiClient.get<ApiSuccessEnvelope<AbsenceAlert[]>>('/attendance/absence-alerts')
      if (id === request.current) {
        setAlerts(response.data.data)
        setError(null)
      }
    } catch (reason) {
      if (id === request.current) setError(getAttendanceErrorMessage(reason, 'Could not load absence alerts.'))
    } finally {
      if (id === request.current) setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 5 * 60 * 1000)
    const focus = () => void refresh()
    window.addEventListener('focus', focus)
    return () => {
      request.current++
      window.clearInterval(timer)
      window.removeEventListener('focus', focus)
    }
  }, [])

  async function dismiss(id: string) {
    setDismissing(id)
    try {
      await apiClient.post(`/attendance/absence-alerts/${id}/dismiss`)
      await refresh()
    } catch (reason) {
      setError(getAttendanceErrorMessage(reason, 'Could not dismiss the absence alert.'))
    } finally {
      setDismissing(null)
    }
  }

  return { alerts, error, dismissing, loading, refresh, dismiss }
}

type AbsenceAlertState = ReturnType<typeof useAbsenceAlerts>

export default function AbsenceAlerts({ state, onClose }: {
  state: AbsenceAlertState
  onClose: () => void
}) {
  const { alerts, error, dismissing, loading, refresh, dismiss } = state
  return (
    <section id="absence-alerts-panel" aria-label="Consecutive absence alerts" className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">Consecutive absence alerts</h2>
          <p className="mt-1 text-sm text-slate-500">Three recorded absent workdays, eight hours after the third scheduled shift starts.</p>
        </div>
        <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50">Close</button>
      </div>
      {error && <p role="alert" className="mt-4 text-sm text-red-700">{error} <button type="button" className="underline" onClick={() => void refresh()}>Retry</button></p>}
      {loading ? <p className="mt-5 text-sm text-slate-500">Loading absence alerts…</p> : alerts.length === 0 && !error ? (
        <p className="mt-5 rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">No consecutive absence alerts.</p>
      ) : alerts.length > 0 && (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[600px] text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase text-slate-400">
              <tr><th className="px-3 py-3">Employee</th><th className="px-3 py-3">Absent dates</th><th className="px-3 py-3">Status</th><th className="px-3 py-3 text-right">Action</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {alerts.map((alert) => (
                <tr key={alert.id}>
                  <td className="px-3 py-3"><p className="font-semibold text-slate-800">{alert.employee_name}</p><p className="text-xs text-slate-500">{alert.employee_no}</p></td>
                  <td className="px-3 py-3 text-slate-600">{alert.absence_dates.join(', ')}</td>
                  <td className="px-3 py-3 text-slate-600">{alert.resolved_at ? 'Resolved after an attendance change' : 'Review recorded absences'}</td>
                  <td className="px-3 py-3 text-right"><button type="button" disabled={dismissing !== null} onClick={() => void dismiss(alert.id)} className="font-semibold text-amber-800 underline disabled:opacity-50">{dismissing === alert.id ? 'Dismissing…' : 'Dismiss'}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
