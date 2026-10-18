import { useEffect, useState, type FormEvent } from 'react'
import { CalendarDays, Pencil, Plus, X } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { useCompanySetupSelection } from '../hooks/useCompanySetupSelection'
import { fetchCompanies } from '../lib/companyApi'
import {
  createHoliday,
  createHolidayCalendar,
  fetchHolidayCalendars,
  fetchHolidays,
  updateHoliday,
  updateHolidayCalendar,
} from '../lib/holidayCalendarApi'
import type {
  Holiday,
  HolidayCalendar,
  HolidayCalendarPayload,
  HolidayPayload,
  HolidayType,
} from '../lib/holidayCalendarApi'
import type { Company } from '../types/company'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const holidayTypes: HolidayType[] = ['REGULAR', 'SPECIAL_NONWORKING', 'SPECIAL_WORKING', 'LOCAL', 'COMPANY']
const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-100'
const labelClass = 'text-sm font-semibold text-slate-700'

function newCalendarForm(companyId: string, year: number): HolidayCalendarPayload {
  return {
    company_id: companyId,
    calendar_code: '',
    calendar_name: '',
    effective_year: year,
    province: null,
    city: null,
    status: 'DRAFT',
    is_active: true,
  }
}

function newHolidayForm(calendarId: string): HolidayPayload {
  return {
    holiday_calendar_id: calendarId,
    holiday_date: '',
    holiday_name: '',
    holiday_type: 'REGULAR',
    is_double_holiday: false,
    pay_rule_code: null,
    source_reference: null,
    status: 'ACTIVE',
    is_active: true,
  }
}

function errorText(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

export default function Calendar({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const { companyId } = useCompanySetupSelection()
  const [companies, setCompanies] = useState<Company[]>([])
  const [year, setYear] = useState(new Date().getFullYear())
  const [calendars, setCalendars] = useState<HolidayCalendar[]>([])
  const [calendarId, setCalendarId] = useState('')
  const [holidays, setHolidays] = useState<Holiday[]>([])
  const [calendarForm, setCalendarForm] = useState<HolidayCalendarPayload>(() => newCalendarForm('', new Date().getFullYear()))
  const [holidayForm, setHolidayForm] = useState<HolidayPayload>(() => newHolidayForm(''))
  const [editingCalendar, setEditingCalendar] = useState<HolidayCalendar | null>(null)
  const [editingHoliday, setEditingHoliday] = useState<Holiday | null>(null)
  const [isCalendarFormOpen, setIsCalendarFormOpen] = useState(false)
  const [isHolidayFormOpen, setIsHolidayFormOpen] = useState(false)
  const [isLoadingCalendars, setIsLoadingCalendars] = useState(false)
  const [isLoadingHolidays, setIsLoadingHolidays] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let current = true
    fetchCompanies()
      .then((items) => {
        if (current) setCompanies(items)
      })
      .catch((cause: unknown) => {
        if (current) setError(errorText(cause, 'Could not load company details.'))
      })
    return () => {
      current = false
    }
  }, [])

  useEffect(() => {
    let current = true
    setCalendars([])
    setCalendarId('')
    setHolidays([])
    setIsCalendarFormOpen(false)
    setIsHolidayFormOpen(false)
    setEditingCalendar(null)
    setEditingHoliday(null)
    setCalendarForm(newCalendarForm(companyId, year))
    setError('')
    setSuccess('')
    if (!companyId) {
      setIsLoadingCalendars(false)
      return () => {
        current = false
      }
    }

    setIsLoadingCalendars(true)
    setError('')
    fetchHolidayCalendars(companyId, year)
      .then((items) => {
        if (!current) return
        setCalendars(items)
        setCalendarId(items[0]?.id ?? '')
      })
      .catch((cause: unknown) => {
        if (current) setError(errorText(cause, 'Could not load calendars for the selected company.'))
      })
      .finally(() => {
        if (current) setIsLoadingCalendars(false)
      })
    return () => {
      current = false
    }
  }, [companyId, year])

  useEffect(() => {
    let current = true
    setHolidays([])
    setHolidayForm(newHolidayForm(calendarId))
    setIsHolidayFormOpen(false)
    setEditingHoliday(null)
    if (!calendarId) {
      setIsLoadingHolidays(false)
      return () => {
        current = false
      }
    }
    setIsLoadingHolidays(true)
    fetchHolidays(calendarId)
      .then((items) => {
        if (current) setHolidays(items)
      })
      .catch((cause: unknown) => {
        if (current) setError(errorText(cause, 'Could not load dates for the selected calendar.'))
      })
      .finally(() => {
        if (current) setIsLoadingHolidays(false)
      })
    return () => {
      current = false
    }
  }, [calendarId])

  const selectedCompany = companies.find((company) => company.id === companyId)
  const selectedCalendar = calendars.find((calendar) => calendar.id === calendarId) ?? null

  function setCalendarField<K extends keyof HolidayCalendarPayload>(key: K, value: HolidayCalendarPayload[K]) {
    setCalendarForm((current) => ({ ...current, [key]: value }))
  }

  function setHolidayField<K extends keyof HolidayPayload>(key: K, value: HolidayPayload[K]) {
    setHolidayForm((current) => ({ ...current, [key]: value }))
  }

  function startCreateCalendar() {
    setError('')
    setSuccess('')
    setEditingCalendar(null)
    setCalendarForm(newCalendarForm(companyId, year))
    setIsCalendarFormOpen(true)
  }

  function startEditCalendar(calendar: HolidayCalendar) {
    setError('')
    setSuccess('')
    setEditingCalendar(calendar)
    setCalendarForm({
      company_id: companyId,
      calendar_code: calendar.calendar_code,
      calendar_name: calendar.calendar_name,
      effective_year: calendar.effective_year,
      province: calendar.province,
      city: calendar.city,
      status: calendar.status,
      is_active: calendar.is_active,
    })
    setIsCalendarFormOpen(true)
  }

  async function submitCalendar(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!companyId || isSaving) return
    setError('')
    setSuccess('')
    setIsSaving(true)
    try {
      const payload = { ...calendarForm, company_id: companyId, effective_year: year }
      const saved = editingCalendar
        ? await updateHolidayCalendar(editingCalendar.id, payload)
        : await createHolidayCalendar(payload)
      const nextCalendars = await fetchHolidayCalendars(companyId, year)
      setCalendars(nextCalendars)
      setCalendarId(saved.id)
      setEditingCalendar(null)
      setIsCalendarFormOpen(false)
      setSuccess(`Calendar ${saved.calendar_code} ${editingCalendar ? 'updated' : 'created'} for ${selectedCompany?.company_code ?? 'the selected company'}.`)
    } catch (cause: unknown) {
      setError(errorText(cause, 'Could not save the calendar.'))
    } finally {
      setIsSaving(false)
    }
  }

  function startCreateHoliday() {
    if (!calendarId) return
    setError('')
    setSuccess('')
    setEditingHoliday(null)
    setHolidayForm(newHolidayForm(calendarId))
    setIsHolidayFormOpen(true)
  }

  function startEditHoliday(holiday: Holiday) {
    setError('')
    setSuccess('')
    setEditingHoliday(holiday)
    setHolidayForm({
      holiday_calendar_id: calendarId,
      holiday_date: holiday.holiday_date,
      holiday_name: holiday.holiday_name,
      holiday_type: holiday.holiday_type,
      is_double_holiday: holiday.is_double_holiday,
      pay_rule_code: holiday.pay_rule_code,
      source_reference: holiday.source_reference,
      status: holiday.status,
      is_active: holiday.is_active,
    })
    setIsHolidayFormOpen(true)
  }

  async function submitHoliday(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!calendarId || isSaving) return
    setError('')
    setSuccess('')
    setIsSaving(true)
    try {
      const payload = { ...holidayForm, holiday_calendar_id: calendarId }
      const saved = editingHoliday
        ? await updateHoliday(editingHoliday.id, payload)
        : await createHoliday(payload)
      setHolidays(await fetchHolidays(calendarId))
      setEditingHoliday(null)
      setIsHolidayFormOpen(false)
      setHolidayForm(newHolidayForm(calendarId))
      setSuccess(`Date ${saved.holiday_name} ${editingHoliday ? 'updated' : 'added'}.`)
    } catch (cause: unknown) {
      setError(errorText(cause, 'Could not save the calendar date.'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="calendar" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] max-w-7xl space-y-6 py-6">
        <header>
          <p className="text-sm font-semibold uppercase tracking-wide text-indigo-600">Company setup</p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">Calendar</h1>
          <p className="mt-1 text-sm text-slate-500">Manage holiday calendars and dates for the selected company.</p>
        </header>
        {!companyId && (
          <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            Select the default company using the Company Setup selector in the top navigation to load or add calendar dates.
          </p>
        )}
        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{success}</p>}

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="grid flex-1 gap-4 sm:grid-cols-2">
              <label className={labelClass}>Company
                <input className={inputClass} readOnly value={selectedCompany ? `${selectedCompany.company_code} — ${selectedCompany.legal_name}` : ''} placeholder="Select a company in the top navigation" />
              </label>
              <label className={labelClass}>Calendar year
                <input className={inputClass} type="number" min={2000} max={2200} value={year} onChange={(event) => setYear(Number(event.target.value))} disabled={!companyId} />
              </label>
            </div>
            <button type="button" onClick={startCreateCalendar} disabled={!companyId || isLoadingCalendars} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">
              <Plus className="h-4 w-4" />New calendar
            </button>
          </div>

          {isCalendarFormOpen && (
            <form onSubmit={(event) => void submitCalendar(event)} className="mt-5 rounded-lg border border-indigo-100 bg-indigo-50/40 p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-bold text-slate-800">{editingCalendar ? 'Edit calendar' : 'Create calendar'}</h2>
                <button type="button" onClick={() => setIsCalendarFormOpen(false)} aria-label="Close calendar form" className="rounded p-1 text-slate-500 hover:bg-white"><X className="h-4 w-4" /></button>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <label className={labelClass}>Calendar code<input className={inputClass} maxLength={30} required value={calendarForm.calendar_code} onChange={(event) => setCalendarField('calendar_code', event.target.value.toUpperCase())} /></label>
                <label className={labelClass}>Calendar name<input className={inputClass} maxLength={150} required value={calendarForm.calendar_name} onChange={(event) => setCalendarField('calendar_name', event.target.value)} /></label>
                <label className={labelClass}>Effective year<input className={inputClass} type="number" value={year} readOnly /></label>
                <label className={labelClass}>Province<input className={inputClass} maxLength={100} value={calendarForm.province ?? ''} onChange={(event) => setCalendarField('province', event.target.value || null)} /></label>
                <label className={labelClass}>City<input className={inputClass} maxLength={100} value={calendarForm.city ?? ''} onChange={(event) => setCalendarField('city', event.target.value || null)} /></label>
                <label className={labelClass}>Status
                  <select className={inputClass} value={calendarForm.status} onChange={(event) => setCalendarField('status', event.target.value as HolidayCalendarPayload['status'])}>
                    <option value="DRAFT">Draft</option><option value="PUBLISHED">Published</option><option value="CLOSED">Closed</option>
                  </select>
                </label>
              </div>
              <div className="mt-4 flex items-center justify-between">
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-700"><input type="checkbox" checked={calendarForm.is_active} onChange={(event) => setCalendarField('is_active', event.target.checked)} />Active</label>
                <button type="submit" disabled={isSaving} className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">{isSaving ? 'Saving…' : editingCalendar ? 'Save calendar' : 'Create calendar'}</button>
              </div>
            </form>
          )}

          <div className="mt-5 grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <label className={labelClass}>Calendar
              <select className={inputClass} value={calendarId} onChange={(event) => setCalendarId(event.target.value)} disabled={!companyId || isLoadingCalendars}>
                <option value="">{isLoadingCalendars ? 'Loading calendars…' : calendars.length ? 'Select a calendar' : 'No calendars for this company and year'}</option>
                {calendars.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.calendar_code} — {calendar.calendar_name} ({calendar.status})</option>)}
              </select>
            </label>
            {selectedCalendar && <button type="button" onClick={() => startEditCalendar(selectedCalendar)} className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"><Pencil className="h-4 w-4" />Edit calendar</button>}
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="font-bold text-slate-900">Calendar dates</h2>
              <p className="mt-1 text-xs text-slate-500">{selectedCalendar ? `${selectedCalendar.calendar_name} · ${selectedCalendar.effective_year}` : 'Select a calendar for the selected company.'}</p>
            </div>
            <button type="button" onClick={startCreateHoliday} disabled={!calendarId || isLoadingHolidays} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"><Plus className="h-4 w-4" />Add date</button>
          </div>

          {isHolidayFormOpen && (
            <form onSubmit={(event) => void submitHoliday(event)} className="border-b border-indigo-100 bg-indigo-50/40 p-5">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-bold text-slate-800">{editingHoliday ? 'Edit calendar date' : 'Add calendar date'}</h3>
                <button type="button" onClick={() => setIsHolidayFormOpen(false)} aria-label="Close date form" className="rounded p-1 text-slate-500 hover:bg-white"><X className="h-4 w-4" /></button>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <label className={labelClass}>Date<input className={inputClass} type="date" required value={holidayForm.holiday_date} onChange={(event) => setHolidayField('holiday_date', event.target.value)} /></label>
                <label className={labelClass}>Name<input className={inputClass} maxLength={150} required value={holidayForm.holiday_name} onChange={(event) => setHolidayField('holiday_name', event.target.value)} /></label>
                <label className={labelClass}>Type
                  <select className={inputClass} value={holidayForm.holiday_type} onChange={(event) => setHolidayField('holiday_type', event.target.value as HolidayType)}>
                    {holidayTypes.map((type) => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}
                  </select>
                </label>
                <label className={labelClass}>Pay rule code<input className={inputClass} maxLength={30} value={holidayForm.pay_rule_code ?? ''} onChange={(event) => setHolidayField('pay_rule_code', event.target.value || null)} /></label>
                <label className={labelClass}>Source reference<input className={inputClass} maxLength={300} value={holidayForm.source_reference ?? ''} onChange={(event) => setHolidayField('source_reference', event.target.value || null)} /></label>
                <label className={labelClass}>Status
                  <select className={inputClass} value={holidayForm.status} onChange={(event) => setHolidayField('status', event.target.value as HolidayPayload['status'])}>
                    <option value="ACTIVE">Active</option><option value="CANCELLED">Cancelled</option><option value="SUPERSEDED">Superseded</option>
                  </select>
                </label>
              </div>
              <div className="mt-4 flex items-center justify-between">
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-700"><input type="checkbox" checked={holidayForm.is_double_holiday} onChange={(event) => setHolidayField('is_double_holiday', event.target.checked)} />Double holiday</label>
                <button type="submit" disabled={isSaving} className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">{isSaving ? 'Saving…' : editingHoliday ? 'Save date' : 'Add date'}</button>
              </div>
            </form>
          )}

          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr><th className="px-5 py-3">Date</th><th className="px-5 py-3">Name</th><th className="px-5 py-3">Type</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Double holiday</th><th className="px-5 py-3"><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {isLoadingHolidays && <tr><td colSpan={6} className="px-5 py-4 text-slate-500">Loading dates…</td></tr>}
                {!isLoadingHolidays && !calendarId && <tr><td colSpan={6} className="px-5 py-4 text-slate-500">Choose or create a calendar to view its dates.</td></tr>}
                {!isLoadingHolidays && calendarId && holidays.length === 0 && <tr><td colSpan={6} className="px-5 py-4 text-slate-500">No dates have been added to this calendar.</td></tr>}
                {holidays.map((holiday) => (
                  <tr key={holiday.id}>
                    <td className="whitespace-nowrap px-5 py-3">{holiday.holiday_date}</td>
                    <td className="px-5 py-3 font-semibold text-slate-900">{holiday.holiday_name}</td>
                    <td className="px-5 py-3">{holiday.holiday_type.replaceAll('_', ' ')}</td>
                    <td className="px-5 py-3">{holiday.status}</td>
                    <td className="px-5 py-3">{holiday.is_double_holiday ? 'Yes' : 'No'}</td>
                    <td className="px-5 py-3 text-right"><button type="button" onClick={() => startEditHoliday(holiday)} aria-label={`Edit ${holiday.holiday_name}`} className="rounded-md p-1.5 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700"><Pencil className="h-4 w-4" /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <p className="flex items-center gap-2 text-xs text-slate-500"><CalendarDays className="h-4 w-4" />Dates are retrieved and saved only under the selected company&apos;s calendar.</p>
      </main>
    </div>
  )
}
