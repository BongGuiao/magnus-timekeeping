import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Briefcase, LoaderCircle, Pencil, Save, Send, X } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import {
  cancelOfficialBusinessRequest,
  createOfficialBusinessRequest,
  fetchMyOfficialBusinessRequests,
  fetchOfficialBusinessOptions,
  formatDuration,
  formatManilaDateTime,
  isoToManilaInput,
  manilaInputToIso,
  submitOfficialBusinessRequest,
  updateOfficialBusinessRequest,
  type OfficialBusinessInput,
  type OfficialBusinessOptions,
  type OfficialBusinessRequest,
  type OfficialBusinessStatus,
} from '../lib/officialBusinessApi'

interface Props {
  employeeName: string
  previewOnly?: boolean
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

interface FormState {
  startAt: string
  endAt: string
  destination: string
  purpose: string
  clientName: string
  geofenceId: string
  joReference: string
  vehicleId: string
  requestedMinutes: string
}

const emptyForm: FormState = {
  startAt: '', endAt: '', destination: '', purpose: '', clientName: '',
  geofenceId: '', joReference: '', vehicleId: '', requestedMinutes: '',
}
const inputClass = 'mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50'
const statusStyles: Record<OfficialBusinessStatus, string> = {
  DRAFT: 'bg-slate-100 text-slate-700',
  PENDING: 'bg-amber-50 text-amber-700',
  APPROVED: 'bg-emerald-50 text-emerald-700',
  REJECTED: 'bg-rose-50 text-rose-700',
  CANCELLED: 'bg-slate-100 text-slate-500',
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Could not load or save official business requests.'
}

function durationMinutes(startAt: string, endAt: string): number {
  if (!startAt || !endAt) return 0
  const start = Date.parse(manilaInputToIso(startAt))
  const end = Date.parse(manilaInputToIso(endAt))
  return Number.isFinite(start) && Number.isFinite(end) && end > start ? Math.floor((end - start) / 60000) : 0
}

function upsert(records: OfficialBusinessRequest[], record: OfficialBusinessRequest): OfficialBusinessRequest[] {
  const rest = records.filter((item) => item.id !== record.id)
  return [record, ...rest].sort((left, right) => right.start_at.localeCompare(left.start_at))
}

export default function OfficialBusiness({ employeeName, previewOnly = false, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [requests, setRequests] = useState<OfficialBusinessRequest[]>([])
  const [options, setOptions] = useState<OfficialBusinessOptions>({ geofences: [], vehicles: [] })
  const [form, setForm] = useState<FormState>(emptyForm)
  const [minutesEdited, setMinutesEdited] = useState(false)
  const [editing, setEditing] = useState<OfficialBusinessRequest | null>(null)
  const [loading, setLoading] = useState(!previewOnly)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (previewOnly) return
    let current = true
    Promise.all([fetchMyOfficialBusinessRequests(), fetchOfficialBusinessOptions()])
      .then(([records, choices]) => {
        if (!current) return
        setRequests(records)
        setOptions(choices)
        setLoaded(true)
      })
      .catch((cause: unknown) => { if (current) setError(errorText(cause)) })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [previewOnly])

  const duration = durationMinutes(form.startAt, form.endAt)
  const requestedMinutes = minutesEdited ? form.requestedMinutes : duration ? String(duration) : ''

  // Keep the selected option visible when editing a draft whose geofence/vehicle is no longer offered.
  const geofenceOptions = useMemo(() => {
    if (!editing?.geofence_id || options.geofences.some((item) => item.id === editing.geofence_id)) return options.geofences
    return [...options.geofences, { id: editing.geofence_id, label: editing.geofence_name ?? 'Unavailable geofence' }]
  }, [editing, options.geofences])
  const vehicleOptions = useMemo(() => {
    if (!editing?.vehicle_id || options.vehicles.some((item) => item.id === editing.vehicle_id)) return options.vehicles
    return [...options.vehicles, { id: editing.vehicle_id, label: editing.vehicle_label ?? 'Unavailable vehicle' }]
  }, [editing, options.vehicles])

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }))
    setSuccess('')
  }

  function resetForm() {
    setForm(emptyForm)
    setMinutesEdited(false)
    setEditing(null)
  }

  function startEdit(record: OfficialBusinessRequest) {
    setEditing(record)
    setForm({
      startAt: isoToManilaInput(record.start_at),
      endAt: isoToManilaInput(record.end_at),
      destination: record.destination,
      purpose: record.purpose,
      clientName: record.client_name ?? '',
      geofenceId: record.geofence_id ?? '',
      joReference: record.jo_reference ?? '',
      vehicleId: record.vehicle_id ?? '',
      requestedMinutes: String(record.requested_minutes),
    })
    setMinutesEdited(true)
    setError('')
    setSuccess('')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function buildPayload(): OfficialBusinessInput | null {
    const minutes = Number(requestedMinutes)
    if (!form.startAt || !form.endAt || duration <= 0) {
      setError('Enter a start and end date/time. The end must be later than the start.')
      return null
    }
    if (duration > 31 * 24 * 60) {
      setError('An official business request cannot exceed 31 days.')
      return null
    }
    if (!Number.isInteger(minutes) || minutes <= 0 || minutes > duration) {
      setError(`Requested minutes must be a whole number from 1 to ${duration}.`)
      return null
    }
    if (!form.destination.trim() || !form.purpose.trim()) {
      setError('Destination and purpose are required.')
      return null
    }
    return {
      start_at: manilaInputToIso(form.startAt),
      end_at: manilaInputToIso(form.endAt),
      destination: form.destination.trim(),
      purpose: form.purpose.trim(),
      client_name: form.clientName.trim() || null,
      geofence_id: form.geofenceId || null,
      jo_reference: form.joReference.trim() || null,
      vehicle_id: form.vehicleId || null,
      requested_minutes: minutes,
    }
  }

  async function save(submit: boolean) {
    if (saving || previewOnly || !loaded) return
    setError('')
    setSuccess('')
    const payload = buildPayload()
    if (!payload) return
    setSaving(true)
    try {
      let record: OfficialBusinessRequest
      if (editing) {
        record = await updateOfficialBusinessRequest(editing.id, payload, editing.row_version)
        if (submit) record = await submitOfficialBusinessRequest(record.id, record.row_version)
      } else {
        record = await createOfficialBusinessRequest(payload, submit)
      }
      setRequests((current) => upsert(current, record))
      resetForm()
      setSuccess(submit
        ? `${record.request_no} was submitted for supervisor approval.`
        : `${record.request_no} was saved as a draft.`)
    } catch (cause) {
      setError(errorText(cause))
    } finally {
      setSaving(false)
    }
  }

  async function runAction(record: OfficialBusinessRequest, action: 'submit' | 'cancel') {
    if (busyId || previewOnly) return
    if (action === 'cancel' && !window.confirm(`Cancel ${record.request_no}?`)) return
    setBusyId(record.id)
    setError('')
    setSuccess('')
    try {
      const next = action === 'submit'
        ? await submitOfficialBusinessRequest(record.id, record.row_version)
        : await cancelOfficialBusinessRequest(record.id, record.row_version)
      setRequests((current) => upsert(current, next))
      if (editing?.id === record.id) resetForm()
      setSuccess(action === 'submit'
        ? `${next.request_no} was submitted for supervisor approval.`
        : `${next.request_no} was cancelled.`)
    } catch (cause) {
      setError(errorText(cause))
    } finally {
      setBusyId(null)
    }
  }

  const disabled = previewOnly || !loaded || loading || saving

  return (
    <div className="min-h-svh bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="official-business" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] max-w-6xl space-y-5 py-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Employee self-service</p>
            <h1 className="mt-1 text-2xl font-extrabold text-slate-900">Official Business</h1>
            <p className="mt-2 text-sm text-slate-500">File work performed outside your usual workplace. All times are in Philippine time.</p>
          </div>
          <button type="button" onClick={() => onNavigate?.('dashboard')} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700">Back to dashboard</button>
        </div>
        {previewOnly && <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">Employee preview only. Use an employee-linked account to view and file official business requests.</p>}
        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</p>}
        {success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">{success}</p>}

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 text-base font-bold text-slate-900">
              <Briefcase className="h-5 w-5 text-indigo-600" aria-hidden="true" />
              {editing ? `Edit draft ${editing.request_no}` : 'New official business request'}
            </h2>
            {editing && (
              <button type="button" onClick={resetForm} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-600">
                <X className="h-3.5 w-3.5" aria-hidden="true" />Discard changes
              </button>
            )}
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500">Save as a draft to finish later, or submit it directly for supervisor approval. Overlapping draft, pending, or approved requests are not allowed.</p>
          {loading && <p role="status" className="mt-4 text-sm text-slate-500">Loading official business details...</p>}
          <form onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); void save(true) }} className="mt-5">
            <fieldset disabled={disabled} className="grid gap-4 sm:grid-cols-2">
              <legend className="sr-only">Official business details</legend>
              <label className="text-xs font-semibold text-slate-700">Start date and time
                <input required type="datetime-local" value={form.startAt} onChange={(event) => update('startAt', event.target.value)} className={inputClass} />
              </label>
              <label className="text-xs font-semibold text-slate-700">End date and time
                <input required type="datetime-local" min={form.startAt || undefined} value={form.endAt} onChange={(event) => update('endAt', event.target.value)} className={inputClass} />
              </label>
              <label className="text-xs font-semibold text-slate-700 sm:col-span-2">Destination
                <input required maxLength={300} value={form.destination} onChange={(event) => update('destination', event.target.value)} placeholder="e.g. ACME Corp. head office, Makati City" className={inputClass} />
              </label>
              <label className="text-xs font-semibold text-slate-700 sm:col-span-2">Purpose
                <textarea required maxLength={5000} rows={3} value={form.purpose} onChange={(event) => update('purpose', event.target.value)} className={inputClass} />
              </label>
              <label className="text-xs font-semibold text-slate-700">Client name (optional)
                <input maxLength={200} value={form.clientName} onChange={(event) => update('clientName', event.target.value)} className={inputClass} />
              </label>
              <label className="text-xs font-semibold text-slate-700">Job order reference (optional)
                <input maxLength={100} value={form.joReference} onChange={(event) => update('joReference', event.target.value)} className={inputClass} />
              </label>
              <label className="text-xs font-semibold text-slate-700">Geofence (optional)
                <select value={form.geofenceId} onChange={(event) => update('geofenceId', event.target.value)} className={inputClass}>
                  <option value="">No geofence</option>
                  {geofenceOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold text-slate-700">Company vehicle (optional)
                <select value={form.vehicleId} onChange={(event) => update('vehicleId', event.target.value)} className={inputClass}>
                  <option value="">{vehicleOptions.length ? 'No vehicle' : 'No vehicles available'}</option>
                  {vehicleOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold text-slate-700">Requested minutes
                <input required type="number" min={1} max={duration || undefined} step={1} value={requestedMinutes} onChange={(event) => { setMinutesEdited(true); update('requestedMinutes', event.target.value) }} className={inputClass} />
              </label>
              <div className="rounded-lg border border-indigo-100 bg-indigo-50 p-3">
                <p className="text-xs text-indigo-700">Scheduled period</p>
                <p className="mt-1 text-lg font-bold text-indigo-900">{duration ? formatDuration(duration) : '--'}</p>
                {minutesEdited && duration > 0 && (
                  <button type="button" onClick={() => setMinutesEdited(false)} className="mt-1 text-xs font-semibold text-indigo-700 underline">Use full period</button>
                )}
              </div>
              <div className="flex flex-wrap justify-end gap-2 sm:col-span-2">
                <button type="button" onClick={() => void save(false)} className="inline-flex items-center gap-2 rounded-lg border border-indigo-200 bg-white px-4 py-2.5 text-sm font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50">
                  <Save className="h-4 w-4" aria-hidden="true" />{editing ? 'Save draft' : 'Save as draft'}
                </button>
                <button type="submit" className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
                  {saving ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Send className="h-4 w-4" aria-hidden="true" />}
                  {saving ? 'Saving...' : 'Submit for approval'}
                </button>
              </div>
            </fieldset>
          </form>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <h2 className="text-base font-bold text-slate-900">My Official Business Requests</h2>
          {!loading && loaded && requests.length === 0 && <p className="mt-4 text-sm text-slate-500">No official business requests yet.</p>}
          {requests.length > 0 && <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-xs">
              <thead className="border-b border-slate-200 text-slate-500">
                <tr>{['Request', 'Schedule', 'Destination / purpose', 'Requested', 'Approved', 'Status', 'Actions'].map((heading) => <th key={heading} className="px-3 py-3">{heading}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-slate-100">{requests.map((record) => {
                const busy = busyId === record.id
                const editable = record.status === 'DRAFT' && !record.payroll_posted
                const cancellable = (record.status === 'DRAFT' || record.status === 'PENDING') && !record.payroll_posted
                return <tr key={record.id} className="align-top">
                  <td className="px-3 py-3 font-semibold text-slate-800">{record.request_no}</td>
                  <td className="px-3 py-3 text-slate-600"><p>{formatManilaDateTime(record.start_at)}</p><p className="mt-1">to {formatManilaDateTime(record.end_at)}</p></td>
                  <td className="px-3 py-3 text-slate-600">
                    <p className="font-semibold text-slate-800">{record.destination}</p>
                    <p className="mt-1 max-w-xs whitespace-pre-line">{record.purpose}</p>
                    {(record.client_name || record.jo_reference) && <p className="mt-1 text-slate-500">{[record.client_name, record.jo_reference && `JO ${record.jo_reference}`].filter(Boolean).join(' · ')}</p>}
                  </td>
                  <td className="px-3 py-3">{formatDuration(record.requested_minutes)}</td>
                  <td className="px-3 py-3">{record.approved_minutes === null ? '--' : formatDuration(record.approved_minutes)}</td>
                  <td className="px-3 py-3"><span className={`rounded-full px-2 py-1 font-semibold ${statusStyles[record.status]}`}>{record.status}</span></td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      {editable && <button type="button" disabled={busy || previewOnly} onClick={() => startEdit(record)} className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 font-semibold text-slate-700 disabled:opacity-50"><Pencil className="h-3 w-3" aria-hidden="true" />Edit</button>}
                      {editable && <button type="button" disabled={busy || previewOnly} onClick={() => void runAction(record, 'submit')} className="rounded bg-indigo-600 px-2 py-1 font-semibold text-white disabled:opacity-50">Submit</button>}
                      {cancellable && <button type="button" disabled={busy || previewOnly} onClick={() => void runAction(record, 'cancel')} className="rounded border border-rose-200 px-2 py-1 font-semibold text-rose-700 disabled:opacity-50">Cancel</button>}
                      {!editable && !cancellable && <span className="text-slate-400">--</span>}
                    </div>
                  </td>
                </tr>
              })}</tbody>
            </table>
          </div>}
        </section>
      </main>
    </div>
  )
}
