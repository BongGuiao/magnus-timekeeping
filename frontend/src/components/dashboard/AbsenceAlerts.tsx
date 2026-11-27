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

export default function AbsenceAlerts() {
  const [alerts, setAlerts] = useState<AbsenceAlert[]>([])
  const [error, setError] = useState<string | null>(null)
  const [dismissing, setDismissing] = useState<string | null>(null)
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

  if (!alerts.length && !error) return null
  return (
    <section aria-label="Absence alerts" className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-4">
      <h2 className="font-bold text-amber-950">Consecutive absence alerts</h2>
      {alerts.map((alert) => (
        <div key={alert.id} className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm text-amber-950">
          <p>
            <strong>{alert.employee_name} ({alert.employee_no})</strong>: {alert.absence_dates.join(', ')}
            {alert.resolved_at ? ' — resolved after an attendance change' : ' — review these recorded absences'}
          </p>
          <button type="button" disabled={dismissing !== null} onClick={() => void dismiss(alert.id)} className="font-semibold underline disabled:opacity-50">
            {dismissing === alert.id ? 'Dismissing…' : 'Dismiss'}
          </button>
        </div>
      ))}
      {error && <p role="alert" className="mt-2 text-sm text-red-700">{error} <button type="button" className="underline" onClick={() => void refresh()}>Retry</button></p>}
    </section>
  )
}
