import { useEffect, useId, useState } from 'react'
import { AxiosError } from 'axios'
import { AlertCircle, CheckCircle2, CircleDot, Crosshair, Home, Info, LoaderCircle, MapPin, Save, ShieldCheck, Smartphone } from 'lucide-react'
import { apiClient } from '../../lib/apiClient'
import { fetchGeofences } from '../../lib/geofenceApi'
import { fetchEmploymentAssignments, getManilaDate } from '../../lib/employeeRelatedApi'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../../types/auth'
import type { Employee } from '../../types/employee'
import type { Geofence } from '../../types/geofence'

interface WfhRegistration {
  geofence_id: string
  latitude: number
  longitude: number
  is_active: boolean
}

const inputClassName = 'mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500'
const labelClassName = 'text-xs font-semibold text-slate-700'

function errorText(error: unknown): string {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    return body?.detail ?? 'Could not save or load the WFH registration.'
  }
  return error instanceof Error ? error.message : 'Could not save or load the WFH registration.'
}

export default function EmployeeWfhPanel({ employee }: { employee: Employee | null }) {
  const panelId = useId()
  const employeeId = employee?.id
  const [geofences, setGeofences] = useState<Geofence[]>([])
  const [geofenceId, setGeofenceId] = useState('')
  const [latitude, setLatitude] = useState('')
  const [longitude, setLongitude] = useState('')
  const [isActive, setIsActive] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [hasLoaded, setHasLoaded] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!employeeId) {
      return
    }
    let current = true
    Promise.all([
      apiClient.get<ApiSuccessEnvelope<WfhRegistration | null>>(`/employees/${employeeId}/wfh`),
      fetchGeofences(),
      fetchEmploymentAssignments(employeeId),
    ]).then(([response, fences, assignments]) => {
      if (!current) return
      const record = response.data.data
      const now = Date.now()
      const today = getManilaDate()
      const eligibleFences = fences.filter((fence) =>
        fence.is_active && fence.status === 'ACTIVE'
        && fence.radius_meters !== null && Number(fence.radius_meters) > 0
        && Date.parse(fence.effective_from) <= now
        && (!fence.effective_to || Date.parse(fence.effective_to) >= now)
        && assignments.some((assignment) =>
          assignment.company_id === fence.company_id && assignment.primary_location_id === fence.location_id
          && assignment.is_active && assignment.status === 'ACTIVE'
          && assignment.effective_from <= today
          && (!assignment.effective_to || assignment.effective_to >= today)
          && (!assignment.separation_date || assignment.separation_date >= today),
        ),
      )
      if (record && !eligibleFences.some((fence) => fence.id === record.geofence_id)) {
        const previous = fences.find((fence) => fence.id === record.geofence_id)
        if (previous) eligibleFences.push(previous)
      }
      setGeofences(eligibleFences)
      setGeofenceId(record?.geofence_id ?? '')
      setLatitude(record ? String(record.latitude) : '')
      setLongitude(record ? String(record.longitude) : '')
      setIsActive(record?.is_active ?? false)
      setHasLoaded(true)
    }).catch((cause: unknown) => {
      if (current) setError(errorText(cause))
    }).finally(() => {
      if (current) setIsLoading(false)
    })
    return () => { current = false }
  }, [employeeId])

  async function save() {
    if (!employeeId || !hasLoaded || isSaving) return
    setError('')
    setNotice('')
    const lat = Number(latitude)
    const lon = Number(longitude)
    if (!geofenceId || !latitude.trim() || !longitude.trim()
      || !Number.isFinite(lat) || lat < -90 || lat > 90
      || !Number.isFinite(lon) || lon < -180 || lon > 180) {
      setError('Select a geofence and enter valid home latitude (-90 to 90) and longitude (-180 to 180).')
      return
    }
    setIsSaving(true)
    try {
      await apiClient.put(`/employees/${employeeId}/wfh`, {
        geofence_id: geofenceId, latitude: lat, longitude: lon, is_active: isActive,
      })
      setNotice('WFH registration saved.')
    } catch (cause) {
      setError(errorText(cause))
    } finally {
      setIsSaving(false)
    }
  }

  if (!employee) return (
    <div className="flex flex-col items-center rounded-xl border border-dashed border-slate-300 bg-slate-50 px-6 py-10 text-center">
      <span className="mb-3 rounded-xl border border-slate-200 bg-white p-3 text-indigo-600"><Home className="h-6 w-6" aria-hidden="true" /></span>
      <h3 className="text-sm font-bold text-slate-900">Create the employee first</h3>
      <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">Save the employee record, then reopen it to register a work-from-home location.</p>
    </div>
  )
  const selected = geofences.find((fence) => fence.id === geofenceId)
  return (
    <div className="mx-auto max-w-5xl space-y-5" aria-busy={isLoading || isSaving} onKeyDown={(event) => {
      if (event.key === 'Enter' && event.target instanceof HTMLInputElement) event.preventDefault()
    }}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="rounded-xl bg-indigo-50 p-2.5 text-indigo-600"><Home className="h-5 w-5" aria-hidden="true" /></span>
          <div>
            <h3 className="text-base font-bold text-slate-900">Work-from-home location</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">Register a home attendance area for {employee.first_name} {employee.last_name}.</p>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1.5 text-[11px] font-semibold text-indigo-700">
          <Smartphone className="h-3.5 w-3.5" aria-hidden="true" />Mobile app only
        </span>
      </div>

      {isLoading && <p role="status" className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600"><LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />Loading WFH registration...</p>}
      {error && <p role="alert" className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-xs leading-5 text-rose-700"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />{error}</p>}
      {notice && <p role="status" className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs text-emerald-800"><CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />{notice}</p>}

      <fieldset disabled={!hasLoaded || isLoading || isSaving} className="min-w-0 space-y-5">
        <legend className="sr-only">WFH location registration</legend>
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(240px,0.65fr)]">
          <section className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white">
            <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50/70 px-5 py-3">
              <MapPin className="h-4 w-4 text-indigo-600" aria-hidden="true" />
              <h4 className="text-xs font-bold text-slate-800">Location details</h4>
            </div>
            <div className="space-y-5 p-5">
              <label className={`block ${labelClassName}`}>Geofence policy <span className="font-normal text-slate-400">(required)</span>
                <select value={geofenceId} onChange={(event) => setGeofenceId(event.target.value)} aria-describedby={`${panelId}-policy-help`} className={inputClassName}>
                  <option value="">Select an assigned office geofence</option>
                  {geofences.map((fence) => <option key={fence.id} value={fence.id}>{fence.geofence_code} - {fence.geofence_name}</option>)}
                </select>
              </label>
              <p id={`${panelId}-policy-help`} className="-mt-3 text-[11px] leading-5 text-slate-500">Uses the selected office geofence's radius and accuracy limits. Its office center point stays unchanged.</p>
              {hasLoaded && geofences.length === 0 && <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">No eligible geofence found. Configure a geofence with a radius for an active office assignment first.</p>}
              <div className="border-t border-slate-100 pt-4">
                <div className="mb-3 flex items-center gap-2">
                  <Crosshair className="h-4 w-4 text-slate-400" aria-hidden="true" />
                  <h5 className="text-xs font-semibold text-slate-800">Home center point</h5>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className={labelClassName}>Latitude <span className="font-normal text-slate-400">(required)</span>
                    <input type="number" min="-90" max="90" step="any" placeholder="e.g. 14.5547" value={latitude} onChange={(event) => setLatitude(event.target.value)} aria-describedby={`${panelId}-latitude-help`} className={`${inputClassName} tabular-nums`} />
                    <span id={`${panelId}-latitude-help`} className="mt-1.5 block text-[11px] font-normal text-slate-400">Between -90 and 90</span>
                  </label>
                  <label className={labelClassName}>Longitude <span className="font-normal text-slate-400">(required)</span>
                    <input type="number" min="-180" max="180" step="any" placeholder="e.g. 121.0244" value={longitude} onChange={(event) => setLongitude(event.target.value)} aria-describedby={`${panelId}-longitude-help`} className={`${inputClassName} tabular-nums`} />
                    <span id={`${panelId}-longitude-help`} className="mt-1.5 block text-[11px] font-normal text-slate-400">Between -180 and 180</span>
                  </label>
                </div>
                <p className="mt-3 text-[11px] leading-5 text-slate-500">Enter decimal-degree coordinates for the employee's approved home location.</p>
              </div>
            </div>
          </section>

          <aside className="min-w-0 space-y-4">
            <section className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50/70">
              <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
                <ShieldCheck className="h-4 w-4 text-indigo-600" aria-hidden="true" />
                <h4 className="text-xs font-bold text-slate-800">Inherited attendance limits</h4>
              </div>
              <div className="p-4">
                <p className="break-words text-xs font-semibold text-slate-700">{selected?.geofence_name ?? 'No policy selected'}</p>
                <dl className="mt-4 grid grid-cols-2 gap-3">
                  <div className="rounded-lg border border-slate-200 bg-white p-3">
                    <dt className="flex items-center gap-1.5 text-[11px] text-slate-500"><CircleDot className="h-3.5 w-3.5" aria-hidden="true" />Radius</dt>
                    <dd className="mt-2 text-lg font-bold tabular-nums text-slate-900">{selected?.radius_meters != null ? Number(selected.radius_meters).toLocaleString() : '--'} <span className="text-xs font-medium text-slate-400">m</span></dd>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-white p-3">
                    <dt className="text-[11px] text-slate-500">Max GPS accuracy</dt>
                    <dd className="mt-2 text-lg font-bold tabular-nums text-slate-900">{selected ? selected.maximum_gps_accuracy_meters.toLocaleString() : '--'} <span className="text-xs font-medium text-slate-400">m</span></dd>
                  </div>
                </dl>
                <p className="mt-3 text-[11px] leading-5 text-slate-500">Read-only limits managed in Geofencing. Changes to that policy also apply to this WFH location.</p>
              </div>
            </section>
            <div className="flex items-start gap-2 rounded-lg border border-indigo-100 bg-indigo-50/60 p-4">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" aria-hidden="true" />
              <div className="text-[11px] leading-5 text-indigo-900">
                <p className="font-semibold">How attendance is validated</p>
                <p className="mt-1">Approved mobile devices may punch from the office or this home area. GPS uncertainty must fit inside the radius. Browser attendance rules are unchanged.</p>
              </div>
            </div>
          </aside>
        </div>

        <label className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition ${isActive ? 'border-indigo-200 bg-indigo-50/50' : 'border-slate-200 bg-slate-50/50'}`}>
          <input type="checkbox" checked={isActive} onChange={(event) => setIsActive(event.target.checked)} className="mt-0.5 h-4 w-4 shrink-0 rounded accent-indigo-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2" />
          <span>
            <span className="block text-xs font-semibold text-slate-900">Approve WFH at this location</span>
            <span className="mt-1 block text-[11px] leading-5 text-slate-500">Enable to authorize mobile attendance here. Disable to remove home authorization after saving.</span>
          </span>
        </label>
        <div className="flex flex-col gap-3 border-t border-slate-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[11px] leading-5 text-slate-500">Changes take effect after you save this registration.</p>
          <button type="button" onClick={() => void save()} className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-xs font-semibold text-white shadow-sm transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50">
            {isSaving ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Save className="h-4 w-4" aria-hidden="true" />}
            {isLoading ? 'Loading...' : isSaving ? 'Saving...' : 'Save WFH registration'}
          </button>
        </div>
      </fieldset>
    </div>
  )
}
