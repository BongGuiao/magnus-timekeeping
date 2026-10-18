import { useEffect, useState, type FormEvent } from 'react'
import { ArrowDown, ArrowUp, ChevronsUpDown, ChevronDown, Pencil, Plus, Power, Search } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { useCompanySetupSelection } from '../hooks/useCompanySetupSelection'
import { fetchCompanies } from '../lib/companyApi'
import { fetchPayrollHolidayCalendars, type HolidayCalendarOption } from '../lib/payrollGroupApi'
import {
  createScheduleSegment,
  createScheduleTemplate,
  deleteScheduleSegment,
  deactivateScheduleTemplate,
  fetchScheduleSegments,
  fetchScheduleTemplates,
  updateScheduleSegment,
  updateScheduleTemplate,
  type ScheduleSegment,
  type ScheduleSegmentPayload,
  type ScheduleSegmentType,
  type BreakSlot,
  type ScheduleTemplate,
  type ScheduleTemplatePayload,
  type ScheduleType,
} from '../lib/scheduleTemplateApi'
import type { Company } from '../types/company'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

type TemplateForm = ScheduleTemplatePayload
type SegmentForm = ScheduleSegmentPayload & { id?: string }
type TemplateSortKey = 'schedule' | 'company' | 'type' | 'workRules' | 'effectivePeriod' | 'status'
type SortDirection = 'asc' | 'desc'

const scheduleTypes: ScheduleType[] = [
  'FIXED',
  'FLEXIBLE',
  'SHIFTING',
  'OVERNIGHT',
  'SPLIT',
  'COMPRESSED',
  'FIELD',
  'ON_CALL',
]

const blankForm: TemplateForm = {
  company_id: '',
  schedule_code: '',
  schedule_name: '',
  schedule_type: 'FIXED',
  required_minutes: 480,
  grace_minutes: 0,
  grace_method: 'NONE',
  is_overnight: false,
  ot_eligible: true,
  pre_shift_ot_allowed: false,
  minimum_ot_minutes: 0,
  holiday_calendar_id: null,
  effective_from: new Date().toISOString().slice(0, 10),
  effective_to: null,
  status: 'DRAFT',
  is_active: true,
}

function blankSegment(sequence: number): SegmentForm {
  return {
    segment_sequence: sequence,
    segment_type: 'WORK',
    start_time: '',
    end_time: '',
    end_day_offset: 0,
    paid_minutes: 0,
    punch_required: false,
    auto_deduct: false,
    flex_start_minutes: 0,
    break_slot: null,
    work_segment_sequence: null,
    break_minutes: 0,
  }
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
const labelClass = 'text-sm font-semibold text-slate-700'

function companyLabel(companyId: string, companies: Company[]) {
  const company = companies.find((item) => item.id === companyId)
  return company ? `${company.company_code} — ${company.legal_name}` : 'Company unavailable'
}

function calendarLabel(calendarId: string | null, calendars: HolidayCalendarOption[]) {
  if (!calendarId) return 'None'
  const calendar = calendars.find((item) => item.id === calendarId)
  return calendar ? `${calendar.calendar_code} — ${calendar.calendar_name}` : 'Assigned'
}

function formatMinutes(minutes: number) {
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`
}

export default function ScheduleTemplates({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const { companyId } = useCompanySetupSelection()
  const [companies, setCompanies] = useState<Company[]>([])
  const [calendars, setCalendars] = useState<HolidayCalendarOption[]>([])
  const [templates, setTemplates] = useState<ScheduleTemplate[]>([])
  const [form, setForm] = useState<TemplateForm>(blankForm)
  const [segments, setSegments] = useState<SegmentForm[]>([])
  const [expandedSegmentIndexes, setExpandedSegmentIndexes] = useState<number[]>([])
  const [originalSegments, setOriginalSegments] = useState<ScheduleSegment[]>([])
  const [editing, setEditing] = useState<ScheduleTemplate | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [isLoadingSegments, setIsLoadingSegments] = useState(false)
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<TemplateSortKey>('schedule')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [workingId, setWorkingId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  async function reloadTemplates() {
    if (!companyId) {
      setTemplates([])
      return
    }
    const nextTemplates = await fetchScheduleTemplates({
      companyId,
    })
    setTemplates(nextTemplates)
  }

  useEffect(() => {
    let current = true
    fetchCompanies()
      .then((nextCompanies) => {
        if (!current) return
        setCompanies(nextCompanies)
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load schedule configuration.')
      })
    return () => {
      current = false
    }
  }, [])

  useEffect(() => {
    setEditing(null)
    setIsFormOpen(false)
    setSegments([])
    setExpandedSegmentIndexes([])
    setOriginalSegments([])
  }, [companyId])

  useEffect(() => {
    let current = true
    if (!companyId) {
      setTemplates([])
      setLoading(false)
      return () => {
        current = false
      }
    }
    setLoading(true)
    fetchScheduleTemplates({
      companyId,
    })
      .then((items) => {
        if (current) setTemplates(items)
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load schedule templates.')
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
  }, [companyId])

  useEffect(() => {
    if (!form.company_id) {
      setCalendars([])
      return
    }
    let current = true
    fetchPayrollHolidayCalendars(form.company_id)
      .then((items) => {
        if (current) setCalendars(items)
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load holiday calendars.')
      })
    return () => {
      current = false
    }
  }, [form.company_id])

  function setField<K extends keyof TemplateForm>(key: K, value: TemplateForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function setOvernight(isOvernight: boolean) {
    setField('is_overnight', isOvernight)
    setSegments((current) => current.map((segment) => ({
      ...segment,
      end_day_offset: isOvernight ? 1 : 0,
    })))
  }

  function resetForm() {
    setEditing(null)
    setIsFormOpen(false)
    setSegments([])
    setExpandedSegmentIndexes([])
    setOriginalSegments([])
    setForm({
      ...blankForm,
      company_id: companyId,
    })
    setError('')
    setSuccess('')
  }

  async function beginEdit(template: ScheduleTemplate) {
    setError('')
    setSuccess('')
    setIsLoadingSegments(true)
    try {
      const nextSegments = await fetchScheduleSegments(template.id)
      setEditing(template)
      setIsFormOpen(true)
      setForm({
        company_id: template.company_id,
        schedule_code: template.schedule_code,
        schedule_name: template.schedule_name,
        schedule_type: template.schedule_type,
        required_minutes: template.required_minutes,
        grace_minutes: template.grace_minutes,
        grace_method: template.grace_method,
        is_overnight: template.is_overnight,
        ot_eligible: template.ot_eligible,
        pre_shift_ot_allowed: template.pre_shift_ot_allowed,
        minimum_ot_minutes: template.minimum_ot_minutes,
        holiday_calendar_id: template.holiday_calendar_id,
        effective_from: template.effective_from,
        effective_to: template.effective_to,
        status: template.status,
        is_active: template.is_active,
      })
      setOriginalSegments(nextSegments)
      setSegments(nextSegments.map(({ id, schedule_template_id: _templateId, ...segment }) => ({
        ...segment,
        end_day_offset: template.is_overnight ? 1 : 0,
        id,
      })))
      setExpandedSegmentIndexes([])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load schedule template segments.')
    } finally {
      setIsLoadingSegments(false)
    }
  }

  function updateSegment(index: number, values: Partial<SegmentForm>) {
    setSegments((current) => {
      const updated = current.map((segment, segmentIndex) => {
        if (segmentIndex !== index) return segment
        const next = { ...segment, ...values }
        if (next.segment_type === 'WORK') {
          return { ...next, break_slot: null, work_segment_sequence: null, break_minutes: 0 }
        }
        if (next.segment_type === 'PAID_BREAK') next.auto_deduct = false
        next.punch_required = !next.auto_deduct
        return next
      })
      return updated.map((segment) => {
        if (segment.segment_type === 'WORK') return segment
        const oldParent = current[index]
        const sequence = oldParent.segment_type === 'WORK'
          && segment.work_segment_sequence === oldParent.segment_sequence
          ? updated[index].segment_sequence : segment.work_segment_sequence
        const work = updated.find((item) =>
          item.segment_type === 'WORK' && item.segment_sequence === sequence,
        )
        return work ? {
          ...segment, work_segment_sequence: sequence,
          start_time: work.start_time, end_time: work.end_time, end_day_offset: work.end_day_offset,
        } : segment
      })
    })
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSuccess('')
    if (segments.length === 0) {
      setError('Add at least one schedule segment before saving the template.')
      return
    }
    const invalidWorkSegmentIndex = segments.findIndex((segment) =>
      segment.segment_type === 'WORK'
      && (
        !segment.start_time
        || !segment.end_time
        || !Number.isInteger(segment.paid_minutes)
        || segment.paid_minutes < 0
        || !Number.isInteger(segment.flex_start_minutes)
        || segment.flex_start_minutes < 0
      ),
    )
    if (invalidWorkSegmentIndex >= 0) {
      setExpandedSegmentIndexes((current) => [...new Set([...current, invalidWorkSegmentIndex])])
      setError(`Complete the work hours and minute settings for segment ${segments[invalidWorkSegmentIndex].segment_sequence}.`)
      return
    }
    const sequences = segments.map((segment) => Number(segment.segment_sequence))
    if (sequences.some((sequence) => !Number.isInteger(sequence) || sequence < 1 || sequence > 32767)) {
      setError('Segment sequence must be a whole number between 1 and 32767.')
      return
    }
    if (new Set(sequences).size !== sequences.length) {
      setError('Each schedule segment must have a unique sequence number.')
      return
    }
    const breaks = segments.filter((segment) => segment.segment_type !== 'WORK')
    const invalidBreakIndex = segments.findIndex((segment) =>
      segment.segment_type !== 'WORK'
      && (
        !segment.break_slot
        || !Number.isInteger(segment.break_minutes)
        || segment.break_minutes <= 0
        || !segments.some((work) => work.segment_type === 'WORK'
          && work.segment_sequence === segment.work_segment_sequence)
      ),
    )
    if (invalidBreakIndex >= 0) {
      setExpandedSegmentIndexes((current) => [...new Set([...current, invalidBreakIndex])])
      setError('Each break needs an attendance break slot, a WORK segment, and positive break minutes.')
      return
    }
    if (new Set(breaks.map((segment) => segment.break_slot)).size !== breaks.length) {
      setError('Each attendance break slot can have only one break segment.')
      return
    }
    setSaving(true)
    try {
      const isCreating = !editing
      const payload: TemplateForm = {
        ...form,
        schedule_code: form.schedule_code.trim(),
        schedule_name: form.schedule_name.trim(),
        grace_method: form.grace_method.trim(),
        required_minutes: Number(form.required_minutes),
        grace_minutes: Number(form.grace_minutes),
        minimum_ot_minutes: Number(form.minimum_ot_minutes),
      }
      const savedTemplate = editing
        ? await updateScheduleTemplate(editing.id, payload)
        : await createScheduleTemplate(payload)
      const templateId = savedTemplate.id
      if (isCreating) setEditing(savedTemplate)

      const persistedSegments = [...segments]
      const saveOrder = persistedSegments.map((segment, index) => ({ segment, index }))
        .sort((a, b) => Number(a.segment.segment_type !== 'WORK') - Number(b.segment.segment_type !== 'WORK'))
      for (const { index, segment } of saveOrder) {
        const { id, ...segmentPayload } = segment
        const normalizedPayload: ScheduleSegmentPayload = {
          ...segmentPayload,
          segment_sequence: Number(segmentPayload.segment_sequence),
          end_day_offset: Number(segmentPayload.end_day_offset),
          paid_minutes: Number(segmentPayload.paid_minutes),
          flex_start_minutes: Number(segmentPayload.flex_start_minutes),
          break_minutes: Number(segmentPayload.break_minutes),
        }
        if (id) await updateScheduleSegment(templateId, id, normalizedPayload)
        else {
          const createdSegment = await createScheduleSegment(templateId, normalizedPayload)
          persistedSegments[index] = { ...segment, id: createdSegment.id }
          setSegments([...persistedSegments])
        }
      }
      const retainedSegmentIds = new Set(persistedSegments.flatMap((segment) => segment.id ? [segment.id] : []))
      for (const oldSegment of [...originalSegments].sort((a, b) =>
        Number(a.segment_type === 'WORK') - Number(b.segment_type === 'WORK'),
      )) {
        if (!retainedSegmentIds.has(oldSegment.id)) {
          await deleteScheduleSegment(templateId, oldSegment.id)
          setOriginalSegments((current) => current.filter((segment) => segment.id !== oldSegment.id))
        }
      }
      await reloadTemplates()
      resetForm()
      setSuccess(isCreating ? 'Schedule template created.' : 'Schedule template updated.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the schedule template.')
    } finally {
      setSaving(false)
    }
  }

  async function deactivate(template: ScheduleTemplate) {
    if (!window.confirm(`Deactivate schedule template ${template.schedule_code}?`)) return
    setError('')
    setSuccess('')
    setWorkingId(template.id)
    try {
      await deactivateScheduleTemplate(template.id)
      await reloadTemplates()
      setSuccess('Schedule template deactivated.')
      if (editing?.id === template.id) resetForm()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not deactivate the schedule template.')
    } finally {
      setWorkingId(null)
    }
  }

  const activeCompanies = companies.filter((company) => company.is_active || company.id === form.company_id)
  const activeCalendars = calendars.filter((calendar) =>
    (calendar.is_active && calendar.status === 'PUBLISHED')
    || calendar.id === form.holiday_calendar_id,
  )
  const normalizedSearch = search.trim().toLowerCase()
  const filteredTemplates = normalizedSearch
    ? templates.filter((template) => [
      template.schedule_code,
      template.schedule_name,
      companyLabel(template.company_id, companies),
      template.schedule_type,
      template.status,
      template.effective_from,
      template.effective_to,
    ].some((value) => String(value ?? '').toLowerCase().includes(normalizedSearch)))
    : templates
  const visibleTemplates = [...filteredTemplates].sort((left, right) => {
    const sortValues: Record<TemplateSortKey, [string | number, string | number]> = {
      schedule: [`${left.schedule_code} ${left.schedule_name}`, `${right.schedule_code} ${right.schedule_name}`],
      company: [companyLabel(left.company_id, companies), companyLabel(right.company_id, companies)],
      type: [left.schedule_type, right.schedule_type],
      workRules: [left.required_minutes, right.required_minutes],
      effectivePeriod: [`${left.effective_from} ${left.effective_to ?? ''}`, `${right.effective_from} ${right.effective_to ?? ''}`],
      status: [`${left.is_active} ${left.status}`, `${right.is_active} ${right.status}`],
    }
    const [leftValue, rightValue] = sortValues[sortKey]
    const comparison = typeof leftValue === 'number' && typeof rightValue === 'number'
      ? leftValue - rightValue
      : String(leftValue).localeCompare(String(rightValue), undefined, { numeric: true })
    return sortDirection === 'asc' ? comparison : -comparison
  })

  function changeSort(key: TemplateSortKey) {
    if (sortKey === key) {
      setSortDirection((direction) => direction === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
  }

  function sortHeader(label: string, key: TemplateSortKey) {
    const active = sortKey === key
    const direction = active ? sortDirection : null
    return (
      <button
        type="button"
        onClick={() => changeSort(key)}
        aria-label={`Sort by ${label}${direction ? `, ${direction === 'asc' ? 'ascending' : 'descending'}` : ''}`}
        className="inline-flex items-center gap-1.5 text-left hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
      >
        {label}
        {!active
          ? <ChevronsUpDown className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
          : direction === 'asc'
            ? <ArrowUp className="h-3.5 w-3.5 text-indigo-600" aria-hidden="true" />
            : <ArrowDown className="h-3.5 w-3.5 text-indigo-600" aria-hidden="true" />}
      </button>
    )
  }

  function addSegment() {
    const nextIndex = segments.length
    const nextSegment = {
      ...blankSegment(segments.reduce((highest, segment) => Math.max(highest, segment.segment_sequence), 0) + 1),
      end_day_offset: form.is_overnight ? 1 : 0,
    }
    setSegments((current) => [...current, nextSegment])
    setExpandedSegmentIndexes((current) => [...new Set([...current, nextIndex])])
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="schedule-templates" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] max-w-7xl space-y-3 py-6">
        {!isFormOpen && <p className="text-xs text-slate-500">Define work schedule rules, grace periods, overtime eligibility, and effective dates.</p>}

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {!isFormOpen && success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}

        {isFormOpen && <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-bold text-slate-900">{editing ? 'Edit schedule template' : 'Create schedule template'}</h2>
          </div>
          <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className={labelClass}>Company
              <select className={inputClass} required disabled={Boolean(companyId)} value={form.company_id} onChange={(event) => {
                setField('company_id', event.target.value)
                setField('holiday_calendar_id', null)
              }}>
                <option value="">Select company</option>
                {activeCompanies.filter((company) => !companyId || company.id === companyId).map((company) => <option key={company.id} value={company.id}>{company.company_code} — {company.legal_name}</option>)}
              </select>
            </label>
            <label className={labelClass}>Schedule code
              <input className={inputClass} maxLength={30} required value={form.schedule_code} onChange={(event) => setField('schedule_code', event.target.value)} />
            </label>
            <label className={labelClass}>Schedule name
              <input className={inputClass} maxLength={150} required value={form.schedule_name} onChange={(event) => setField('schedule_name', event.target.value)} />
            </label>
            <label className={labelClass}>Schedule type
              <select className={inputClass} required value={form.schedule_type} onChange={(event) => setField('schedule_type', event.target.value as ScheduleType)}>
                {scheduleTypes.map((type) => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}
              </select>
            </label>
            <label className={labelClass}>Required work minutes
              <input className={inputClass} type="number" min={1} required value={form.required_minutes} onChange={(event) => setField('required_minutes', Number(event.target.value))} />
            </label>
            <label className={labelClass}>Grace minutes
              <input className={inputClass} type="number" min={0} required value={form.grace_minutes} onChange={(event) => setField('grace_minutes', Number(event.target.value))} />
            </label>
            <label className={labelClass}>Grace method
              <input className={inputClass} maxLength={30} required value={form.grace_method} onChange={(event) => setField('grace_method', event.target.value)} />
            </label>
            <label className={labelClass}>Minimum overtime minutes
              <input className={inputClass} type="number" min={0} required value={form.minimum_ot_minutes} onChange={(event) => setField('minimum_ot_minutes', Number(event.target.value))} />
            </label>
            <label className={labelClass}>Holiday calendar
              <select className={inputClass} value={form.holiday_calendar_id ?? ''} onChange={(event) => setField('holiday_calendar_id', event.target.value || null)}>
                <option value="">No holiday calendar</option>
                {activeCalendars.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.calendar_code} — {calendar.calendar_name} ({calendar.effective_year})</option>)}
              </select>
            </label>
            <label className={labelClass}>Effective from
              <input className={inputClass} type="date" required value={form.effective_from} onChange={(event) => setField('effective_from', event.target.value)} />
            </label>
            <label className={labelClass}>Effective to
              <input className={inputClass} type="date" min={form.effective_from} value={form.effective_to ?? ''} onChange={(event) => setField('effective_to', event.target.value || null)} />
            </label>
            <label className={labelClass}>Status
              <select className={inputClass} value={form.status} onChange={(event) => setField('status', event.target.value)}>
                <option value="DRAFT">Draft</option>
                <option value="ACTIVE">Active</option>
                <option value="INACTIVE">Inactive</option>
              </select>
            </label>
            <div className="grid gap-2 sm:col-span-2 lg:col-span-4 sm:grid-cols-3">
              <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700">
                <input type="checkbox" checked={form.is_overnight} onChange={(event) => setOvernight(event.target.checked)} className="h-4 w-4 accent-indigo-600" />
                Overnight schedule
              </label>
              <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700">
                <input type="checkbox" checked={form.ot_eligible} onChange={(event) => setField('ot_eligible', event.target.checked)} className="h-4 w-4 accent-indigo-600" />
                Overtime eligible
              </label>
              <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700">
                <input type="checkbox" checked={form.pre_shift_ot_allowed} onChange={(event) => setField('pre_shift_ot_allowed', event.target.checked)} className="h-4 w-4 accent-indigo-600" />
                Allow pre-shift overtime
              </label>
            </div>
            {editing && (
              <label className="flex items-center gap-2 self-center text-sm font-medium text-slate-700">
                <input type="checkbox" checked={form.is_active} onChange={(event) => setField('is_active', event.target.checked)} className="h-4 w-4 accent-indigo-600" />
                Enabled for use
              </label>
            )}
            <fieldset className="space-y-3 rounded-lg border border-slate-200 p-4 sm:col-span-2 lg:col-span-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <legend className="px-1 text-sm font-bold text-slate-800">Schedule segments</legend>
                  <p className="mt-1 text-xs text-slate-500">
                    {segments.filter((segment) => segment.segment_type === 'WORK').length} work
                    {' · '}
                    {segments.filter((segment) => segment.segment_type !== 'WORK').length} breaks
                    {' · '}Expand a segment to edit its settings.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={addSegment}
                  className="inline-flex items-center gap-1 rounded-lg border border-indigo-200 px-3 py-1.5 text-sm font-semibold text-indigo-700 hover:bg-indigo-50"
                >
                  <Plus className="h-4 w-4" /> Add segment
                </button>
              </div>
              {segments.length === 0 && (
                <p className="text-sm text-rose-700">At least one segment is required. Add work or break segments to define the template’s daily schedule.</p>
              )}
              {segments.map((segment, index) => {
                const isExpanded = expandedSegmentIndexes.includes(index)
                const isWork = segment.segment_type === 'WORK'
                const breakLabel = segment.break_slot ? {
                  FIRST_BREAK: 'First break',
                  MEAL_BREAK: 'Meal break',
                  SECOND_BREAK: 'Second break',
                  OT_BREAK: 'Overtime break',
                }[segment.break_slot] : undefined
                const summary = isWork
                  ? `${segment.start_time || 'Set start'}–${segment.end_time || 'Set end'}${segment.end_day_offset ? ' (+1 day)' : ''} · ${formatMinutes(segment.paid_minutes)} paid`
                  : `${breakLabel ?? 'Choose break'} · ${segment.segment_type === 'PAID_BREAK' ? `${segment.break_minutes} min paid allowance` : `${segment.break_minutes} min unpaid`}`
                return (
                <section key={segment.id ?? `new-segment-${index}`} className="overflow-hidden rounded-lg border border-slate-200 bg-white">
                  <div className="flex items-center gap-2 bg-slate-50">
                    <button
                      type="button"
                      aria-expanded={isExpanded}
                      aria-controls={`segment-settings-${index}`}
                      onClick={() => setExpandedSegmentIndexes((current) =>
                        isExpanded ? current.filter((item) => item !== index) : [...current, index],
                      )}
                      className="flex min-w-0 flex-1 items-center gap-3 px-3 py-3 text-left hover:bg-slate-100"
                    >
                      <ChevronDown className={`h-4 w-4 shrink-0 text-slate-500 transition-transform ${isExpanded ? 'rotate-180' : ''}`} aria-hidden="true" />
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700">
                        {segment.segment_sequence}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold text-slate-800">
                          {isWork ? 'Work segment' : breakLabel ?? 'Break segment'}
                          <span className={`ml-2 inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${isWork ? 'bg-indigo-100 text-indigo-700' : segment.segment_type === 'PAID_BREAK' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'}`}>
                            {isWork ? 'Work' : segment.segment_type === 'PAID_BREAK' ? 'Paid' : 'Unpaid'}
                          </span>
                        </span>
                        <span className="block truncate text-xs text-slate-500">{summary}</span>
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setSegments((current) => current.filter((_, segmentIndex) => segmentIndex !== index))
                        setExpandedSegmentIndexes((current) => current
                          .filter((item) => item !== index)
                          .map((item) => item > index ? item - 1 : item))
                      }}
                      className="mr-3 rounded-lg border border-rose-200 px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50"
                      aria-label={`Remove segment ${segment.segment_sequence}`}
                    >
                      Remove
                    </button>
                  </div>
                  <fieldset id={`segment-settings-${index}`} disabled={!isExpanded} className={`grid gap-3 p-3 sm:grid-cols-2 lg:grid-cols-4 ${isExpanded ? '' : 'hidden'}`}>
                    <label className={labelClass}>Sequence
                      <input className={inputClass} type="number" min={1} max={32767} step={1} required value={segment.segment_sequence} onChange={(event) => updateSegment(index, { segment_sequence: Number(event.target.value) })} />
                    </label>
                    <label className={labelClass}>Segment type
                      <select className={inputClass} required value={segment.segment_type} disabled={['FIRST_BREAK', 'SECOND_BREAK', 'OT_BREAK'].includes(segment.break_slot ?? '')} onChange={(event) => updateSegment(index, { segment_type: event.target.value as ScheduleSegmentType })}>
                        <option value="WORK">Work</option>
                        <option value="PAID_BREAK">Paid break</option>
                        <option value="UNPAID_BREAK">Unpaid break</option>
                      </select>
                    </label>
                    {isWork && <>
                      <label className={labelClass}>Start time
                        <input className={inputClass} type="time" required value={segment.start_time} onChange={(event) => updateSegment(index, { start_time: event.target.value })} />
                      </label>
                      <label className={labelClass}>End time
                        <input className={inputClass} type="time" required value={segment.end_time} onChange={(event) => updateSegment(index, { end_time: event.target.value })} />
                      </label>
                      <label className={labelClass}>Paid minutes
                        <input className={inputClass} type="number" min={0} step={1} required value={segment.paid_minutes} onChange={(event) => updateSegment(index, { paid_minutes: Number(event.target.value) })} />
                      </label>
                      <label className={labelClass}>Early clock-in allowance (minutes)
                        <input className={inputClass} type="number" min={0} step={1} required value={segment.flex_start_minutes} onChange={(event) => updateSegment(index, { flex_start_minutes: Number(event.target.value) })} />
                        <span className="mt-1 block text-xs font-normal text-slate-500">Only the first WORK segment controls shift clock-in. Zero allows no early punches.</span>
                      </label>
                      <label className="flex items-center gap-2 self-end pb-2 text-sm font-medium text-slate-700">
                        <input type="checkbox" checked={segment.punch_required} onChange={(event) => updateSegment(index, { punch_required: event.target.checked })} className="h-4 w-4 accent-indigo-600" />
                        Punch required
                      </label>
                    </>}
                    {!isWork && <>
                      <label className={labelClass}>Attendance break
                        <select className={inputClass} required value={segment.break_slot ?? ''} onChange={(event) => {
                          const breakSlot = event.target.value as BreakSlot
                          updateSegment(index, ['FIRST_BREAK', 'SECOND_BREAK', 'OT_BREAK'].includes(breakSlot)
                            ? { break_slot: breakSlot, segment_type: 'PAID_BREAK', auto_deduct: false }
                            : { break_slot: breakSlot })
                        }}>
                          <option value="">Select a break</option>
                          <option value="FIRST_BREAK">First break</option>
                          <option value="MEAL_BREAK">Meal break</option>
                          <option value="SECOND_BREAK">Second break</option>
                          <option value="OT_BREAK">Overtime break</option>
                        </select>
                      </label>
                      <label className={labelClass}>Linked WORK segment
                        <select className={inputClass} required value={segment.work_segment_sequence ?? ''} onChange={(event) => updateSegment(index, { work_segment_sequence: Number(event.target.value) || null })}>
                          <option value="">Select WORK segment</option>
                          {segments.filter((item) => item.segment_type === 'WORK').map((item) =>
                            <option key={item.segment_sequence} value={item.segment_sequence}>Work #{item.segment_sequence}: {item.start_time} - {item.end_time}</option>,
                          )}
                        </select>
                      </label>
                      <label className={labelClass}>{segment.segment_type === 'PAID_BREAK' ? 'Allowed paid break minutes' : 'Required unpaid break minutes'}
                        <input className={inputClass} type="number" min={1} step={1} required value={segment.break_minutes} onChange={(event) => updateSegment(index, { break_minutes: Number(event.target.value) })} />
                      </label>
                      {segment.segment_type === 'UNPAID_BREAK' && <label className="flex items-center gap-2 self-end pb-2 text-sm font-medium text-slate-700">
                        <input type="checkbox" checked={segment.auto_deduct} onChange={(event) => updateSegment(index, { auto_deduct: event.target.checked })} className="h-4 w-4 accent-indigo-600" />
                        Auto deduct when not punched
                      </label>}
                      <p className="text-xs text-slate-500 sm:col-span-2 lg:col-span-4">
                        {segment.break_slot === 'OT_BREAK'
                          ? 'Paid up to this allowance; only excess minutes are deducted from worked time.'
                          : 'Breaks inherit the linked WORK segment hours. Paid breaks are paid up to the allowance; unpaid meal time is deducted from worked time.'}
                      </p>
                    </>}
                    {!isWork && <label className="text-sm font-medium text-slate-700">
                      Break hours
                      <span className={`${inputClass} block cursor-not-allowed bg-slate-100 text-slate-500`}>
                        {segment.start_time || '—'}–{segment.end_time || '—'}
                        {segment.end_day_offset ? ' (+1 day)' : ''}
                      </span>
                    </label>}
                  </fieldset>
                </section>
                )
              })}
            </fieldset>
            <div className="flex items-end justify-end gap-2 sm:col-span-2 lg:col-span-4">
              <button type="button" onClick={resetForm} className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">Cancel</button>
              <button type="submit" disabled={saving || isLoadingSegments || !form.company_id || segments.length === 0} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60">
                <Plus className="h-4 w-4" />{saving ? 'Saving…' : editing ? 'Save changes' : 'Create template'}
              </button>
            </div>
          </form>
        </section>}

        {!isFormOpen && <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-col gap-3 border-b border-slate-200 bg-slate-100 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <label className="relative block w-full sm:max-w-sm">
              <span className="sr-only">Search schedule templates</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search schedule templates" className="w-full rounded-md border border-slate-300 bg-white py-1.5 pl-9 pr-3 text-sm text-slate-900 shadow-sm outline-none placeholder:text-slate-400 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
            </label>
            <div className="flex flex-wrap items-center gap-2 sm:justify-end">
              {!isFormOpen && <button type="button" disabled={!companyId} onClick={() => {
                setEditing(null)
                setForm({ ...blankForm, company_id: companyId })
                setError('')
                setSuccess('')
                setSegments([{ ...blankSegment(1), end_day_offset: blankForm.is_overnight ? 1 : 0 }])
                setExpandedSegmentIndexes([0])
                setOriginalSegments([])
                setIsFormOpen(true)
              }} className="inline-flex items-center gap-2 whitespace-nowrap rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"><Plus className="h-4 w-4" /> New template</button>}
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" aria-sort={sortKey === 'schedule' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3 font-semibold">{sortHeader('Schedule', 'schedule')}</th>
                  <th scope="col" aria-sort={sortKey === 'company' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3 font-semibold">{sortHeader('Company', 'company')}</th>
                  <th scope="col" aria-sort={sortKey === 'type' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3 font-semibold">{sortHeader('Type', 'type')}</th>
                  <th scope="col" aria-sort={sortKey === 'workRules' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3 font-semibold">{sortHeader('Work rules', 'workRules')}</th>
                  <th scope="col" aria-sort={sortKey === 'effectivePeriod' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3 font-semibold">{sortHeader('Effective period', 'effectivePeriod')}</th>
                  <th scope="col" aria-sort={sortKey === 'status' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3 font-semibold">{sortHeader('Status', 'status')}</th>
                  <th className="px-4 py-3 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading ? (
                  <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-500">Loading schedule templates…</td></tr>
                ) : visibleTemplates.length === 0 ? (
                  <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-500">{normalizedSearch ? 'No schedule templates match your search.' : 'No schedule templates configured.'}</td></tr>
                ) : visibleTemplates.map((template) => (
                  <tr key={template.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <p className="font-bold text-slate-900">{template.schedule_code}</p>
                      <p className="text-slate-500">{template.schedule_name}</p>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">{companyLabel(template.company_id, companies)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">{template.schedule_type.replaceAll('_', ' ')}</td>
                    <td className="min-w-52 px-4 py-3 text-slate-600">
                      <p>{formatMinutes(template.required_minutes)} required · {template.grace_minutes}m grace</p>
                      <p className="text-xs text-slate-500">{template.ot_eligible ? `OT from ${template.minimum_ot_minutes}m` : 'No overtime'}{template.is_overnight ? ' · Overnight' : ''}</p>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">{template.effective_from} – {template.effective_to ?? 'No end date'}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${
                        template.is_active && template.status === 'ACTIVE'
                          ? 'bg-emerald-50 text-emerald-700'
                          : 'bg-slate-100 text-slate-600'
                      }`}>
                        {template.status}{!template.is_active ? ' · INACTIVE' : ''}
                      </span>
                      <p className="mt-1 max-w-48 truncate text-xs text-slate-400">{calendarLabel(template.holiday_calendar_id, calendars)}</p>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button type="button" onClick={() => beginEdit(template)} className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100">
                          <Pencil className="h-3.5 w-3.5" /> Edit
                        </button>
                        {template.is_active && (
                          <button type="button" disabled={workingId === template.id} onClick={() => void deactivate(template)} className="inline-flex items-center gap-1 rounded-md border border-rose-200 px-2.5 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50">
                            <Power className="h-3.5 w-3.5" />{workingId === template.id ? 'Working…' : 'Deactivate'}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>}
      </main>
    </div>
  )
}
