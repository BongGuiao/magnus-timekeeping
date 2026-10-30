import { useState } from 'react'
import { fetchOfflineReviewEvents, reviewOfflineEvent, type OfflineReviewEvent } from '../../lib/offlineAttendanceApi'
import { apiClient } from '../../lib/apiClient'

export default function OfflineAttendanceReviewPanel() {
  const [events, setEvents] = useState<OfflineReviewEvent[]>([])
  const [opened, setOpened] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notes, setNotes] = useState<Record<string, string>>({})

  async function load() {
    setOpened(true)
    setBusy(true)
    setError(null)
    try {
      setEvents(await fetchOfflineReviewEvents())
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load offline attendance review.')
    } finally {
      setBusy(false)
    }
  }

  async function finish(eventId: string) {
    if (!notes[eventId]?.trim()) {
      setError('Enter the review outcome or HR correction reference before marking an event reviewed.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await reviewOfflineEvent(eventId, notes[eventId].trim())
      setEvents((current) => current.filter((event) => event.event_id !== eventId))
    } catch (reviewError) {
      setError(reviewError instanceof Error ? reviewError.message : 'Could not save this review.')
    } finally {
      setBusy(false)
    }
  }

  async function viewPhoto(eventId: string) {
    setError(null)
    try {
      const response = await apiClient.get<Blob>(`/attendance/offline/events/${eventId}/photo`, { responseType: 'blob' })
      const url = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = `offline-review-${eventId}.jpg`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (photoError) {
      setError(photoError instanceof Error ? photoError.message : 'Could not load the review photo.')
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-extrabold text-slate-900">Offline attendance review</h2>
        <button type="button" disabled={busy} onClick={() => void load()} className="rounded-lg bg-sky-50 px-4 py-2 text-sm font-bold text-sky-700 disabled:opacity-50">
          {busy ? 'Loading...' : opened ? 'Refresh' : 'Load pending events'}
        </button>
      </div>
      <p className="mt-2 text-sm text-slate-500">Conflicting, suspicious, and locked-payroll punches are preserved here without changing attendance or payroll. Use the existing HR correction process where appropriate, then record the outcome below. Marking reviewed does not approve or apply a punch and removes its retained face photo.</p>
      {error && <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}
      {opened && !busy && events.length === 0 && <p className="mt-3 text-sm text-slate-500">No pending offline review events.</p>}
      {events.map((event) => (
        <article key={event.event_id} className="mt-4 rounded-xl border border-slate-200 p-4">
          <h3 className="font-bold text-slate-800">{event.action.replaceAll('_', ' ')}</h3>
          <p className="mt-1 break-all text-xs text-slate-500">Employee user ID: {event.user_id} | Device: {event.payload.device_uuid}</p>
          <p className="mt-1 text-sm text-slate-600">Captured: {new Date(event.captured_at).toLocaleString()} | Received: {new Date(event.received_at).toLocaleString()}</p>
          <p className="mt-1 text-sm text-slate-600">GPS: {event.payload.latitude}, {event.payload.longitude} | Accuracy: {event.payload.accuracy} m</p>
          <p className="mt-2 text-sm text-amber-700">{event.reason}</p>
          <button type="button" onClick={() => void viewPhoto(event.event_id)} className="mt-2 text-sm font-bold text-sky-700">Download review photo</button>
          <label className="mt-3 block text-sm font-medium text-slate-700">
            Review outcome / HR correction reference
            <textarea maxLength={2000} value={notes[event.event_id] ?? ''} disabled={busy}
              onChange={(change) => setNotes((current) => ({ ...current, [event.event_id]: change.target.value }))}
              className="mt-1 block w-full rounded-lg border border-slate-300 p-2" />
          </label>
          <button type="button" disabled={busy} onClick={() => void finish(event.event_id)}
            className="mt-2 rounded-lg bg-sky-700 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">Mark reviewed (no payroll changes)</button>
        </article>
      ))}
      {events.length === 50 && <p className="mt-3 text-sm text-slate-500">Showing the first 50 events. Review these and refresh to load the next events.</p>}
    </section>
  )
}
