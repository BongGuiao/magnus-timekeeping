import { useEffect, useState } from 'react'
import Attendance from './Attendance'
import { enrollKiosk, fetchKioskStatus, kioskAttendanceTransport } from '../lib/kioskApi'
import type { KioskDevice, KioskPairing } from '../lib/kioskApi'

export default function Kiosk() {
  const [device, setDevice] = useState<KioskDevice | null>(null)
  const [pairing, setPairing] = useState<KioskPairing | null>(null)
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function checkStatus() {
    setBusy(true)
    setError('')
    try {
      setDevice(await fetchKioskStatus())
    } catch (cause) {
      setDevice(null)
      setError(cause instanceof Error ? cause.message : 'Could not verify this kiosk.')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    let active = true
    async function refresh() {
      try {
        const status = await fetchKioskStatus()
        if (active) {
          setDevice(status)
          setError('')
        }
      } catch (cause) {
        if (active) {
          setDevice(null)
          setError(cause instanceof Error ? cause.message : 'Kiosk authorization unavailable.')
        }
      }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 30_000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  async function register() {
    setBusy(true)
    setError('')
    try {
      setPairing(await enrollKiosk(name))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not register this kiosk.')
    } finally {
      setBusy(false)
    }
  }

  if (device?.status === 'APPROVED') {
    return (
      <>
        <header className="flex items-center justify-between bg-indigo-950 px-6 py-3 text-white">
          <strong>{device.device_name}</strong><span>Attendance kiosk</span>
        </header>
        <Attendance employeeName="" kioskTransport={kioskAttendanceTransport} />
      </>
    )
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
      <section className="w-full max-w-lg rounded-2xl bg-white p-6 shadow">
        <h1 className="text-2xl font-bold text-slate-900">Attendance kiosk</h1>
        <p className="mt-3 text-slate-600">Device not registered or not approved. A system administrator must authorize this browser before attendance can be recorded.</p>
        {error && <p role="alert" className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
        {pairing?.pairing_code && (
          <div role="status" className="mt-4 rounded-lg bg-indigo-50 p-4 text-indigo-950">
            <p>Give this pairing code to your system administrator:</p>
            <p className="my-2 break-all font-mono text-2xl font-bold">{pairing.pairing_code}</p>
            <p className="text-sm">Expires: {new Date(pairing.pairing_expires_at).toLocaleString()}. Approve under Settings → Kiosk Devices.</p>
          </div>
        )}
        {pairing?.status === 'REVOKED' && <p role="alert" className="mt-4 text-rose-700">This kiosk was revoked. Contact your administrator.</p>}
        <form className="mt-5 space-y-3" onSubmit={(event) => { event.preventDefault(); void register() }}>
          <label htmlFor="kiosk-name" className="block text-sm font-semibold">Station name</label>
          <input id="kiosk-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={100}
            placeholder="e.g. Main entrance PC" required className="w-full rounded-lg border p-3" />
          <button disabled={busy || !name.trim()} className="rounded-lg bg-indigo-600 px-4 py-3 font-semibold text-white disabled:opacity-50">
            {busy ? 'Please wait...' : 'Request kiosk registration / renew pairing code'}
          </button>
        </form>
        <button type="button" disabled={busy} onClick={() => void checkStatus()} className="mt-4 rounded-lg border px-4 py-3 font-semibold disabled:opacity-50">
          Check approval
        </button>
        <p className="mt-4 text-xs text-slate-500">Use HTTPS or localhost. Registration belongs to this browser profile; private windows and other browsers need separate approval. No administrator login is required on this screen.</p>
      </section>
    </main>
  )
}
