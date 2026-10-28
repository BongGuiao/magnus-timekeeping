import { useEffect, useState, type FormEvent } from 'react'
import { Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { fetchCompanies } from '../lib/companyApi'
import {
  createRestDayPattern,
  deleteRestDayPattern,
  fetchRestDayPatterns,
  updateRestDayPattern,
} from '../lib/restDayPatternApi'
import type {
  RestDayPattern,
  RestDayPatternDayPayload,
  RestDayPatternPayload,
} from '../lib/restDayPatternApi'
import { fetchScheduleTemplates } from '../lib/scheduleTemplateApi'
import type { ScheduleTemplate } from '../lib/scheduleTemplateApi'
import type { Company } from '../types/company'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

interface PatternForm {
  pattern_code: string
  pattern_name: string
  cycle_length_days: number
  description: string
  is_active: boolean
  days: RestDayPatternDayPayload[]
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-100'
const labelClass = 'text-sm font-semibold text-slate-700'

function blankDay(cycleDayNo: number): RestDayPatternDayPayload {
  return { cycle_day_no: cycleDayNo, is_workday: true, schedule_template_id: null }
}

function blankForm(): PatternForm {
  return {
    pattern_code: '',
    pattern_name: '',
    cycle_length_days: 7,
    description: '',
    is_active: true,
    days: Array.from({ length: 7 }, (_, index) => blankDay(index + 1)),
  }
}

function toForm(pattern: RestDayPattern): PatternForm {
  const dayByNumber = new Map(pattern.days.map((day) => [day.cycle_day_no, day]))
  return {
    pattern_code: pattern.pattern_code,
    pattern_name: pattern.pattern_name,
    cycle_length_days: pattern.cycle_length_days,
    description: pattern.description ?? '',
    is_active: pattern.is_active,
    days: Array.from({ length: pattern.cycle_length_days }, (_, index) => {
      const cycleDayNo = index + 1
      const day = dayByNumber.get(cycleDayNo)
      return day
        ? {
            cycle_day_no: cycleDayNo,
            is_workday: day.is_workday,
            schedule_template_id: day.schedule_template_id,
          }
        : blankDay(cycleDayNo)
    }),
  }
}

function errorText(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function scheduleLabel(template: ScheduleTemplate, companies: Company[]) {
  const company = companies.find((item) => item.id === template.company_id)
  const companyName = company ? company.company_code : 'Company unavailable'
  const inactiveLabel = template.is_active && template.status === 'ACTIVE'
    ? ''
    : ` (${template.status}${template.is_active ? '' : ', disabled'})`
  return `${companyName} · ${template.schedule_code} — ${template.schedule_name}${inactiveLabel}`
}

export default function RestDayPatterns({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [patterns, setPatterns] = useState<RestDayPattern[]>([])
  const [templates, setTemplates] = useState<ScheduleTemplate[]>([])
  const [companies, setCompanies] = useState<Company[]>([])
  const [form, setForm] = useState<PatternForm>(blankForm)
  const [editing, setEditing] = useState<RestDayPattern | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [workingId, setWorkingId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let current = true
    Promise.all([fetchRestDayPatterns(null), fetchScheduleTemplates(), fetchCompanies()])
      .then(([nextPatterns, nextTemplates, nextCompanies]) => {
        if (!current) return
        setPatterns(nextPatterns)
        setTemplates(nextTemplates)
        setCompanies(nextCompanies)
      })
      .catch((cause: unknown) => {
        if (current) setError(errorText(cause, 'Could not load rest-day pattern setup.'))
      })
      .finally(() => {
        if (current) setIsLoading(false)
      })
    return () => {
      current = false
    }
  }, [])

  function resetForm() {
    setForm(blankForm())
    setEditing(null)
    setIsFormOpen(false)
    setError('')
    setSuccess('')
  }

  function openCreate() {
    setError('')
    setSuccess('')
    setEditing(null)
    setForm(blankForm())
    setIsFormOpen(true)
  }

  function openEdit(pattern: RestDayPattern) {
    setError('')
    setSuccess('')
    setEditing(pattern)
    setForm(toForm(pattern))
    setIsFormOpen(true)
  }

  function setLength(length: number) {
    if (!Number.isInteger(length) || length < 1 || length > 366) return
    setForm((current) => {
      const existing = new Map(current.days.map((day) => [day.cycle_day_no, day]))
      return {
        ...current,
        cycle_length_days: length,
        days: Array.from({ length: Math.max(length, current.days.length) }, (_, index) => {
          const cycleDayNo = index + 1
          return existing.get(cycleDayNo) ?? blankDay(cycleDayNo)
        }),
      }
    })
  }

  function updateDay<K extends keyof RestDayPatternDayPayload>(
    cycleDayNo: number,
    key: K,
    value: RestDayPatternDayPayload[K],
  ) {
    setForm((current) => ({
      ...current,
      days: current.days.map((day) => day.cycle_day_no === cycleDayNo
        ? { ...day, [key]: value }
        : day),
    }))
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSuccess('')
    const cycleDays = form.days.slice(0, form.cycle_length_days)
    if (cycleDays.length !== form.cycle_length_days
      || cycleDays.some((day, index) => day.cycle_day_no !== index + 1)) {
      setError('Every cycle day must be configured before saving.')
      return
    }

    const payload: RestDayPatternPayload = {
      pattern_code: form.pattern_code.trim(),
      pattern_name: form.pattern_name.trim(),
      cycle_length_days: form.cycle_length_days,
      description: form.description.trim() || null,
      is_active: form.is_active,
      days: cycleDays.map((day) => ({
        ...day,
        schedule_template_id: day.is_workday ? day.schedule_template_id : null,
      })),
    }
    setIsSaving(true)
    try {
      const saved = editing
        ? await updateRestDayPattern(editing.id, payload)
        : await createRestDayPattern(payload)
      setPatterns((current) => editing
        ? current.map((pattern) => pattern.id === saved.id ? saved : pattern)
        : [...current, saved].sort((left, right) => left.pattern_code.localeCompare(right.pattern_code)))
      setSuccess(`Rest-day pattern ${editing ? 'updated' : 'created'} successfully.`)
      setIsFormOpen(false)
      setEditing(null)
    } catch (cause) {
      setError(errorText(cause, `Could not ${editing ? 'update' : 'create'} rest-day pattern.`))
    } finally {
      setIsSaving(false)
    }
  }

  async function removePattern(pattern: RestDayPattern) {
    if (!window.confirm(`Delete “${pattern.pattern_name}” and its ${pattern.days.length} cycle days?`)) return
    setError('')
    setSuccess('')
    setWorkingId(pattern.id)
    try {
      await deleteRestDayPattern(pattern.id)
      setPatterns((current) => current.filter((item) => item.id !== pattern.id))
      if (editing?.id === pattern.id) resetForm()
      setSuccess('Rest-day pattern deleted.')
    } catch (cause) {
      setError(errorText(cause, 'Could not delete rest-day pattern.'))
    } finally {
      setWorkingId(null)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="rest-day-patterns" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full space-y-4 px-4 py-6 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-bold uppercase text-indigo-600">Work Rules</p>
            <h1 className="mt-1 text-2xl font-extrabold text-slate-900">Rest Day Patterns</h1>
          </div>
          {!isFormOpen && (
            <button type="button" onClick={openCreate} className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700">
              <Plus className="h-4 w-4" aria-hidden="true" /> New pattern
            </button>
          )}
        </div>

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {!isFormOpen && success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}

        {isFormOpen && (
          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-lg font-bold text-slate-900">{editing ? 'Edit rest-day pattern' : 'Create rest-day pattern'}</h2>
              <button type="button" onClick={resetForm} aria-label="Close pattern form" className="rounded-md p-2 text-slate-500 hover:bg-slate-100">
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>
            <form onSubmit={(event) => void submit(event)} className="space-y-5">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <label className={labelClass}>Pattern code
                  <input className={inputClass} required maxLength={30} value={form.pattern_code} onChange={(event) => setForm((current) => ({ ...current, pattern_code: event.target.value }))} />
                </label>
                <label className={labelClass}>Pattern name
                  <input className={inputClass} required maxLength={100} value={form.pattern_name} onChange={(event) => setForm((current) => ({ ...current, pattern_name: event.target.value }))} />
                </label>
                <label className={labelClass}>Cycle length (days)
                  <input className={inputClass} type="number" min={1} max={366} step={1} required value={form.cycle_length_days} onChange={(event) => setLength(Number(event.target.value))} />
                </label>
                <label className={`${labelClass} flex items-end gap-2 pb-2`}>
                  <input type="checkbox" checked={form.is_active} onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))} className="h-4 w-4 accent-indigo-600" />
                  Active pattern
                </label>
                <label className={`${labelClass} sm:col-span-2 lg:col-span-4`}>Description
                  <textarea className={inputClass} rows={2} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} />
                </label>
              </div>

              <fieldset className="space-y-3">
                <div>
                  <legend className="text-sm font-bold text-slate-800">Cycle days</legend>
                  <p className="mt-1 text-xs text-slate-500">Configure each day in the cycle. Workdays may use a schedule template; rest days cannot.</p>
                </div>
                <div className="overflow-x-auto rounded-lg border border-slate-200">
                  <table className="min-w-full text-left text-sm">
                    <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                      <tr>
                        <th scope="col" className="px-3 py-2.5">Cycle day</th>
                        <th scope="col" className="px-3 py-2.5">Day type</th>
                        <th scope="col" className="px-3 py-2.5">Schedule template</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {form.days.map((day) => (
                        <tr key={day.cycle_day_no}>
                          <th scope="row" className="whitespace-nowrap px-3 py-2 font-semibold text-slate-700">Day {day.cycle_day_no}</th>
                          <td className="px-3 py-2">
                            <select
                              aria-label={`Day ${day.cycle_day_no} type`}
                              className={inputClass}
                              value={day.is_workday ? 'workday' : 'rest'}
                              onChange={(event) => {
                                const isWorkday = event.target.value === 'workday'
                                updateDay(day.cycle_day_no, 'is_workday', isWorkday)
                                if (!isWorkday) updateDay(day.cycle_day_no, 'schedule_template_id', null)
                              }}
                            >
                              <option value="workday">Workday</option>
                              <option value="rest">Rest day</option>
                            </select>
                          </td>
                          <td className="min-w-64 px-3 py-2">
                            <select
                              aria-label={`Day ${day.cycle_day_no} schedule template`}
                              className={inputClass}
                              value={day.schedule_template_id ?? ''}
                              disabled={!day.is_workday}
                              onChange={(event) => updateDay(day.cycle_day_no, 'schedule_template_id', event.target.value || null)}
                            >
                              <option value="">
                                {templates.length > 0
                                  ? 'Use employee’s assigned schedule'
                                  : 'No schedule templates found — create one first'}
                              </option>
                              {templates.map((template) => (
                                <option key={template.id} value={template.id}>{scheduleLabel(template, companies)}</option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </fieldset>

              <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 pt-4">
                <button type="button" onClick={resetForm} className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Cancel</button>
                <button type="submit" disabled={isSaving} className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60">
                  <Check className="h-4 w-4" aria-hidden="true" /> {isSaving ? 'Saving…' : editing ? 'Save changes' : 'Create pattern'}
                </button>
              </div>
            </form>
          </section>
        )}

        {!isFormOpen && (
          <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th scope="col" className="px-4 py-3">Pattern</th>
                    <th scope="col" className="px-4 py-3">Cycle</th>
                    <th scope="col" className="px-4 py-3">Work / rest days</th>
                    <th scope="col" className="px-4 py-3">Status</th>
                    <th scope="col" className="px-4 py-3"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {isLoading && <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">Loading rest-day patterns…</td></tr>}
                  {!isLoading && patterns.length === 0 && <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">No rest-day patterns configured.</td></tr>}
                  {patterns.map((pattern) => {
                    const workdayCount = pattern.days.filter((day) => day.is_workday).length
                    return (
                      <tr key={pattern.id}>
                        <td className="px-4 py-3">
                          <p className="font-bold text-slate-900">{pattern.pattern_name}</p>
                          <p className="text-xs text-slate-500">{pattern.pattern_code}</p>
                        </td>
                        <td className="px-4 py-3">{pattern.cycle_length_days} days</td>
                        <td className="px-4 py-3">{workdayCount} work · {pattern.days.length - workdayCount} rest</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${pattern.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
                            {pattern.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-right">
                          <button type="button" onClick={() => openEdit(pattern)} aria-label={`Edit ${pattern.pattern_name}`} className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700">
                            <Pencil className="h-4 w-4" aria-hidden="true" />
                          </button>
                          <button type="button" disabled={workingId === pattern.id} onClick={() => void removePattern(pattern)} aria-label={`Delete ${pattern.pattern_name}`} className="rounded-md p-2 text-rose-600 hover:bg-rose-50 disabled:opacity-50">
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </main>
    </div>
  )
}
