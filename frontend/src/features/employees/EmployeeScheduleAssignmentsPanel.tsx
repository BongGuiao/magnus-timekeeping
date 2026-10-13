import { useEffect, useState } from 'react'
import { Check, Pencil, Plus, Power, X } from 'lucide-react'
import {
  approveEmployeeScheduleAssignment,
  createEmployeeScheduleAssignment,
  deactivateEmployeeScheduleAssignment,
  fetchEmployeeScheduleAssignments,
  updateEmployeeScheduleAssignment,
} from '../../lib/employeeScheduleAssignmentApi'
import type {
  EmployeeScheduleAssignment,
  EmployeeScheduleAssignmentPayload,
} from '../../lib/employeeScheduleAssignmentApi'
import { fetchCurrentEmploymentAssignment, getManilaDate } from '../../lib/employeeRelatedApi'
import { fetchRestDayPatterns } from '../../lib/restDayPatternApi'
import type { RestDayPattern } from '../../lib/restDayPatternApi'
import { fetchScheduleTemplates } from '../../lib/scheduleTemplateApi'
import type { ScheduleTemplate } from '../../lib/scheduleTemplateApi'
import type { Employee } from '../../types/employee'

interface Props {
  employee: Employee | null
}

type AssignmentForm = Omit<EmployeeScheduleAssignmentPayload, 'employee_id'>

const inputClassName = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-100'
const labelClassName = 'text-xs font-semibold text-slate-700'

function emptyAssignment(): AssignmentForm {
  return {
    schedule_template_id: '',
    rest_day_pattern_id: null,
    assignment_type: '',
    effective_from: getManilaDate(),
    effective_to: null,
    reason: null,
  }
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Could not load employee schedule assignments.'
}

export default function EmployeeScheduleAssignmentsPanel({ employee }: Props) {
  const employeeId = employee?.id ?? ''
  const [assignments, setAssignments] = useState<EmployeeScheduleAssignment[]>([])
  const [templates, setTemplates] = useState<ScheduleTemplate[]>([])
  const [patterns, setPatterns] = useState<RestDayPattern[]>([])
  const [form, setForm] = useState<AssignmentForm>(emptyAssignment)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(Boolean(employeeId))
  const [isSaving, setIsSaving] = useState(false)
  const [workingId, setWorkingId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  useEffect(() => {
    if (!employeeId) {
      setAssignments([])
      setTemplates([])
      setPatterns([])
      setIsLoading(false)
      return
    }
    let current = true
    setIsLoading(true)
    setErrorMessage('')
    fetchCurrentEmploymentAssignment(employeeId)
      .then(async (employmentAssignment) => {
        const [nextAssignments, nextTemplates, nextPatterns] = await Promise.all([
          fetchEmployeeScheduleAssignments(employeeId),
          employmentAssignment
            ? fetchScheduleTemplates({ companyId: employmentAssignment.company_id })
            : Promise.resolve([]),
          fetchRestDayPatterns(),
        ])
        if (!current) return
        if (!Array.isArray(nextAssignments)) {
          throw new Error('Employee schedule assignments response was not a list.')
        }
        if (!Array.isArray(nextTemplates)) {
          throw new Error('Schedule templates response was not a list.')
        }
        if (!Array.isArray(nextPatterns)) {
          throw new Error('Rest-day patterns response was not a list.')
        }
        setAssignments(nextAssignments)
        const assignedTemplateIds = new Set(nextAssignments.map((assignment) => assignment.schedule_template_id))
        setTemplates(nextTemplates.filter((template) =>
          (template.is_active && template.status === 'ACTIVE') || assignedTemplateIds.has(template.id),
        ))
        setPatterns(nextPatterns)
        if (!employmentAssignment) {
          setErrorMessage('No active employment assignment found. Add one before assigning a schedule.')
        }
      })
      .catch((error: unknown) => {
        if (current) setErrorMessage(errorText(error))
      })
      .finally(() => {
        if (current) setIsLoading(false)
      })
    return () => {
      current = false
    }
  }, [employeeId])

  if (!employee) {
    return (
      <div className="space-y-4">
        <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Schedule assignments</h3>
        <p className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Create and save the employee record first, then reopen it to assign a schedule.
        </p>
      </div>
    )
  }

  function updateField<K extends keyof AssignmentForm>(key: K, value: AssignmentForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function startEdit(item: EmployeeScheduleAssignment) {
    setEditingId(item.id)
    setForm({
      schedule_template_id: item.schedule_template_id,
      rest_day_pattern_id: item.rest_day_pattern_id,
      assignment_type: item.assignment_type,
      effective_from: item.effective_from,
      effective_to: item.effective_to,
      reason: item.reason,
    })
    setErrorMessage('')
    setSuccessMessage('')
  }

  function resetForm() {
    setEditingId(null)
    setForm(emptyAssignment())
    setErrorMessage('')
    setSuccessMessage('')
  }

  async function saveAssignment() {
    setErrorMessage('')
    setSuccessMessage('')
    if (!form.schedule_template_id || !form.assignment_type.trim() || !form.effective_from) {
      setErrorMessage('Schedule template, assignment type, and effective-from date are required.')
      return
    }
    if (form.effective_to && form.effective_to < form.effective_from) {
      setErrorMessage('Effective-to date must be on or after effective-from date.')
      return
    }
    setIsSaving(true)
    try {
      const payload: EmployeeScheduleAssignmentPayload = {
        employee_id: employeeId,
        ...form,
        assignment_type: form.assignment_type.trim(),
        reason: form.reason?.trim() || null,
      }
      const saved = editingId
        ? await updateEmployeeScheduleAssignment(editingId, payload)
        : await createEmployeeScheduleAssignment(payload)
      setAssignments((current) => current.some((item) => item.id === saved.id)
        ? current.map((item) => item.id === saved.id ? saved : item)
        : [saved, ...current])
      setSuccessMessage(`Schedule assignment ${editingId ? 'updated' : 'created'} successfully.`)
      setEditingId(null)
      setForm(emptyAssignment())
    } catch (error) {
      setErrorMessage(errorText(error))
    } finally {
      setIsSaving(false)
    }
  }

  async function approve(item: EmployeeScheduleAssignment) {
    setErrorMessage('')
    setSuccessMessage('')
    setWorkingId(item.id)
    try {
      const saved = await approveEmployeeScheduleAssignment(item.id)
      setAssignments((current) => current.map((assignment) => assignment.id === saved.id ? saved : assignment))
      setSuccessMessage('Schedule assignment approved.')
    } catch (error) {
      setErrorMessage(errorText(error))
    } finally {
      setWorkingId(null)
    }
  }

  async function deactivate(item: EmployeeScheduleAssignment) {
    setErrorMessage('')
    setSuccessMessage('')
    setWorkingId(item.id)
    try {
      const saved = await deactivateEmployeeScheduleAssignment(item.id)
      setAssignments((current) => current.map((assignment) => assignment.id === saved.id ? saved : assignment))
      setSuccessMessage('Schedule assignment deactivated.')
      if (editingId === item.id) resetForm()
    } catch (error) {
      setErrorMessage(errorText(error))
    } finally {
      setWorkingId(null)
    }
  }

  const templateName = (id: string) => {
    const template = templates.find((item) => item.id === id)
    return template ? `${template.schedule_code} — ${template.schedule_name}` : 'Template unavailable'
  }
  const patternName = (id: string | null) => {
    if (!id) return 'No rest-day pattern'
    const pattern = patterns.find((item) => item.id === id)
    return pattern ? `${pattern.pattern_code} — ${pattern.pattern_name}` : 'Pattern unavailable'
  }

  return (
    <div className="space-y-4">
      <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Employee schedule assignments</h3>
      {errorMessage && <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
      {successMessage && <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{successMessage}</p>}

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Schedule template</th>
              <th className="px-3 py-2">Rest-day pattern</th>
              <th className="px-3 py-2">Type / effective period</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {isLoading && <tr><td colSpan={5} className="px-3 py-3 text-slate-500">Loading schedule assignments…</td></tr>}
            {!isLoading && assignments.length === 0 && <tr><td colSpan={5} className="px-3 py-3 text-slate-500">No schedule assignments yet.</td></tr>}
            {assignments.map((item) => (
              <tr key={item.id} className={editingId === item.id ? 'bg-indigo-50' : ''}>
                <td className="px-3 py-2 font-semibold text-slate-900">{templateName(item.schedule_template_id)}</td>
                <td className="px-3 py-2">{patternName(item.rest_day_pattern_id)}</td>
                <td className="px-3 py-2"><p>{item.assignment_type}</p><p className="text-slate-500">{item.effective_from} → {item.effective_to ?? 'present'}</p></td>
                <td className="px-3 py-2">
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-bold ${item.status === 'APPROVED' && item.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
                    {item.is_active ? item.status : `${item.status} (disabled)`}
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right">
                  {item.status !== 'APPROVED' && item.is_active && (
                    <button type="button" disabled={workingId === item.id} onClick={() => void approve(item)} aria-label="Approve schedule assignment" className="rounded-md p-1.5 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50">
                      <Check className="h-3.5 w-3.5" />
                    </button>
                  )}
                  {item.is_active && (
                    <>
                      <button type="button" onClick={() => startEdit(item)} aria-label="Edit schedule assignment" className="rounded-md p-1.5 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700">
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button type="button" disabled={workingId === item.id} onClick={() => void deactivate(item)} aria-label="Deactivate schedule assignment" className="rounded-md p-1.5 text-rose-700 hover:bg-rose-50 disabled:opacity-50">
                        <Power className="h-3.5 w-3.5" />
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-xs font-bold text-slate-700">{editingId ? 'Edit schedule assignment' : 'Add schedule assignment'}</h4>
          {editingId && <button type="button" onClick={resetForm} className="inline-flex items-center gap-1 text-xs font-semibold text-slate-600"><X className="h-3.5 w-3.5" /> Cancel</button>}
        </div>
        <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className={labelClassName}>Schedule template
            <select className={inputClassName} required value={form.schedule_template_id} onChange={(event) => updateField('schedule_template_id', event.target.value)} disabled={isLoading}>
              <option value="">Select schedule template</option>
              {templates.map((template) => <option key={template.id} value={template.id}>{template.schedule_code} — {template.schedule_name}</option>)}
            </select>
          </label>
          <label className={labelClassName}>Rest-day pattern
            <select className={inputClassName} value={form.rest_day_pattern_id ?? ''} onChange={(event) => updateField('rest_day_pattern_id', event.target.value || null)} disabled={isLoading}>
              <option value="">No rest-day pattern</option>
              {patterns.map((pattern) => <option key={pattern.id} value={pattern.id}>{pattern.pattern_code} — {pattern.pattern_name}</option>)}
            </select>
          </label>
          <label className={labelClassName}>Assignment type
            <input className={inputClassName} required maxLength={30} value={form.assignment_type} onChange={(event) => updateField('assignment_type', event.target.value)} placeholder="e.g. REGULAR" />
          </label>
          <label className={labelClassName}>Effective from
            <input className={inputClassName} type="date" required value={form.effective_from} onChange={(event) => updateField('effective_from', event.target.value)} />
          </label>
          <label className={labelClassName}>Effective to
            <input className={inputClassName} type="date" min={form.effective_from} value={form.effective_to ?? ''} onChange={(event) => updateField('effective_to', event.target.value || null)} />
          </label>
          <label className={`${labelClassName} sm:col-span-2 lg:col-span-3`}>Reason
            <textarea className={inputClassName} rows={2} value={form.reason ?? ''} onChange={(event) => updateField('reason', event.target.value || null)} />
          </label>
          <div className="flex justify-end gap-2 sm:col-span-2 lg:col-span-3">
            <button type="button" onClick={resetForm} className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">Clear</button>
            <button type="button" onClick={() => void saveAssignment()} disabled={isSaving || isLoading || !templates.length} className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60">
              <Plus className="h-3.5 w-3.5" />{isSaving ? 'Saving…' : editingId ? 'Save changes' : 'Add assignment'}
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
