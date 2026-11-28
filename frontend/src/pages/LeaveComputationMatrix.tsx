import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import TopNav, { type NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { fetchMatrixCompanies, fetchLeaveMatrix, saveLeaveMatrix, type LeaveMatrixRange, type MatrixCompany } from '../lib/leaveMatrixApi'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const inputClass = 'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100'

export default function LeaveComputationMatrix({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [company, setCompany] = useState<MatrixCompany | null>(null)
  const generation = useRef(0)
  const [ranges, setRanges] = useState<LeaveMatrixRange[]>([])
  const [version, setVersion] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let current = true
    generation.current++
    setCompany(null)
    setRanges([])
    setVersion(0)
    setLoaded(false)
    setError('')
    setSuccess('')
    setLoading(true)
    fetchMatrixCompanies()
      .then(async (companies) => {
        if (companies.length !== 1) throw new Error('Could not determine your assigned company. Contact HR.')
        if (!current) return
        const assignedCompany = companies[0]
        const matrix = await fetchLeaveMatrix(assignedCompany.id)
        if (current) { setCompany(assignedCompany); setRanges(matrix.ranges); setVersion(matrix.row_version); setLoaded(true) }
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load the leave matrix.')
      })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false; generation.current++ }
  }, [reloadKey])

  function updateRange(index: number, field: keyof LeaveMatrixRange, value: string) {
    setRanges((current) => current.map((row, i) => i === index ? { ...row, [field]: value } : row))
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!company || loading || saving || !loaded) return
    const requestGeneration = generation.current
    setError('')
    setSuccess('')
    setSaving(true)
    try {
      const saved = await saveLeaveMatrix(company.id, { row_version: version, ranges })
      if (generation.current === requestGeneration) {
        setRanges(saved.ranges)
        setVersion(saved.row_version)
        setSuccess('Matrix saved. It is not used in leave calculations.')
      }
    } catch (cause) {
      if (generation.current === requestGeneration) {
        setError(cause instanceof Error ? cause.message : 'Could not save the leave matrix.')
      }
    } finally {
      if (generation.current === requestGeneration) setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="leave-computation-matrix" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full space-y-4 px-4 py-6 sm:px-6 lg:px-8">
        <div>
          <p className="text-xs font-bold uppercase text-indigo-600">Work Rules</p>
          <h1 className="mt-1 text-2xl font-extrabold text-slate-900">Leave Computation Matrix</h1>
          <p className="mt-2 text-sm text-slate-600">Configuration only. These values do not affect leave calculations or balances.</p>
          {company && <p className="mt-2 text-sm font-semibold text-slate-700">Company: {company.company_code} — {company.legal_name}</p>}
        </div>
        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}
        {loading ? (
          <p className="text-sm text-slate-600">Loading your company and matrix...</p>
        ) : !loaded ? (
          <button type="button" onClick={() => setReloadKey((key) => key + 1)} className="text-sm font-semibold text-indigo-700 underline">Retry loading</button>
        ) : (
          <form onSubmit={(event) => void submit(event)} className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
            <p className="text-sm text-slate-600">Enter decimal hours. Both range endpoints are inclusive; ranges cannot overlap. Leave hours are a fixed value for each range.</p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
                  <tr><th className="px-2 py-3">Worked hours from</th><th className="px-2 py-3">Worked hours to</th><th className="px-2 py-3">Leave hours</th><th className="px-2 py-3">Action</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {ranges.map((row, index) => (
                    <tr key={index}>
                      {(['worked_from', 'worked_to', 'leave_hours'] as const).map((field) => (
                        <td key={field} className="px-2 py-2">
                          <input aria-label={`${field.replaceAll('_', ' ')} row ${index + 1}`} className={inputClass} type="number" min="0" max={field === 'leave_hours' ? '8' : '999'} step="0.01" required value={row[field]} disabled={saving}
                            onChange={(event) => updateRange(index, field, event.target.value)} />
                        </td>
                      ))}
                      <td className="px-2 py-2"><button type="button" disabled={saving} onClick={() => setRanges((current) => current.filter((_, i) => i !== index))} aria-label={`Remove row ${index + 1}`} className="rounded-lg p-2 text-rose-700 hover:bg-rose-50"><Trash2 size={18} /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {ranges.length === 0 && <p className="text-sm text-slate-500">No ranges configured for this company.</p>}
            <div className="flex flex-wrap gap-3">
              <button type="button" disabled={saving || ranges.length >= 100} onClick={() => setRanges((current) => [...current, { worked_from: '', worked_to: '', leave_hours: '' }])} className="inline-flex items-center gap-2 rounded-lg border border-indigo-300 px-3 py-2 text-sm font-semibold text-indigo-700 disabled:opacity-50"><Plus size={16} /> Add range</button>
              <button type="submit" disabled={saving} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">{saving ? 'Saving...' : 'Save matrix'}</button>
              <button type="button" disabled={saving} onClick={() => { if (window.confirm('Reload the saved matrix and discard unsaved changes?')) setReloadKey((key) => key + 1) }} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50">Reload saved matrix</button>
            </div>
          </form>
        )}
      </main>
    </div>
  )
}
