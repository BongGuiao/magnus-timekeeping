import { useEffect, useState } from 'react'
import TopNav, { type NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { fetchLocations } from '../lib/locationApi'
import { getAttendanceErrorMessage } from '../lib/attendanceApi'
import { approveKiosk, fetchKioskCompany, listKioskDevices, revokeKiosk, type KioskDevice } from '../lib/kioskApi'
import type { Location } from '../types/location'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

export default function KioskDevices({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [company, setCompany] = useState<{ id: string; legal_name: string } | null>(null)
  const [locations, setLocations] = useState<Location[]>([])
  const [devices, setDevices] = useState<KioskDevice[]>([])
  const companyId = company?.id ?? ''
  const [locationId, setLocationId] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    Promise.all([fetchKioskCompany(), listKioskDevices()])
      .then(([nextCompany, nextDevices]) => {
        if (active) { setCompany(nextCompany); setDevices(nextDevices) }
      })
      .catch((cause) => { if (active) setError(getAttendanceErrorMessage(cause, 'Could not load kiosk devices.')) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    if (companyId) {
      fetchLocations(companyId)
        .then((next) => { if (active) setLocations(next) })
        .catch((cause) => { if (active) setError(getAttendanceErrorMessage(cause, 'Could not load locations.')) })
    }
    return () => { active = false }
  }, [companyId])

  async function manage(action: () => Promise<void>, message: string) {
    if (busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await action()
      setNotice(message)
      setDevices(await listKioskDevices())
    } catch (cause) {
      setError(getAttendanceErrorMessage(cause, 'Could not update kiosk devices.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="kiosk-devices" onNavigate={onNavigate} onSignOut={logout} />
      <main className="space-y-5 p-6">
        <h1 className="text-2xl font-bold">Kiosk Devices</h1>
        <p>Open <a href="/kiosk" target="_blank" rel="noreferrer" className="text-indigo-700 underline">/kiosk</a> on the attendance PC, request registration, and enter its pairing code here. Verify the station with IT before approving.</p>
        {error && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-rose-700">{error}</p>}
        {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-emerald-700">{notice}</p>}
        <form className="flex flex-wrap items-end gap-4 rounded-xl bg-white p-5 shadow-sm"
          onSubmit={(event) => {
            event.preventDefault()
            if (!companyId || !locations.some((location) => location.id === locationId && location.is_active && location.status === 'ACTIVE')) {
              setError('Your active company and a valid location are required.')
              return
            }
            void manage(() => approveKiosk(code, locationId), 'Kiosk approved. Select Check approval on the station.')
          }}>
          <label className="flex flex-col gap-2 text-sm font-semibold">Pairing code
            <input value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} required
              pattern="[A-Fa-f0-9]{16}" maxLength={16} className="rounded-lg border p-2 font-mono" />
          </label>
          <label className="flex flex-col gap-2 text-sm font-semibold">Company
            <input value={company?.legal_name ?? 'Company unavailable'} readOnly className="rounded-lg border bg-slate-50 p-2" />
          </label>
          <label className="flex flex-col gap-2 text-sm font-semibold">Location
            <select value={locationId} onChange={(event) => setLocationId(event.target.value)} required className="rounded-lg border p-2">
              <option value="">Select location</option>
              {locations.filter((location) => location.is_active && location.status === 'ACTIVE').map((location) =>
                <option key={location.id} value={location.id}>{location.location_name}</option>)}
            </select>
          </label>
          <button disabled={busy || !companyId || !locationId} className="rounded-lg bg-indigo-600 px-4 py-2 font-semibold text-white disabled:opacity-50">Approve kiosk</button>
        </form>
        <div className="overflow-x-auto rounded-xl bg-white p-5 shadow-sm">
          <table className="w-full text-left text-sm">
            <thead><tr><th className="p-2">Station</th><th className="p-2">Company / location</th><th className="p-2">Status</th><th className="p-2">Last seen</th><th className="p-2">Action</th></tr></thead>
            <tbody>{devices.map((device) => (
              <tr key={device.id} className="border-t">
                <td className="p-2">{device.device_name}</td>
                <td className="p-2">{company?.legal_name ?? device.company_id}<br />{device.location_name ?? device.location_id}</td>
                <td className="p-2">{device.status}</td>
                <td className="p-2">{device.last_seen_at ? new Date(device.last_seen_at).toLocaleString() : 'Not yet used'}</td>
                <td className="p-2">{device.status === 'APPROVED' && <button type="button" disabled={busy}
                  onClick={() => {
                    if (window.confirm(`Revoke attendance access for ${device.device_name}?`)) {
                      void manage(() => revokeKiosk(device.id), 'Kiosk authorization revoked.')
                    }
                  }} className="rounded border border-rose-200 px-3 py-2 text-rose-700 disabled:opacity-50">Revoke</button>}</td>
              </tr>
            ))}</tbody>
          </table>
          {!devices.length && <p className="mt-4 text-slate-500">No approved or revoked kiosks.</p>}
        </div>
      </main>
    </div>
  )
}
