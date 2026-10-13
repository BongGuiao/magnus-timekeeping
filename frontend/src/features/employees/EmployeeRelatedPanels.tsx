import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { LoaderCircle, Pencil, Plus } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import {
  createEmployeeSkill,
  createEmploymentAssignment,
  fetchEmployeeSkills,
  fetchEmploymentAssignments,
  updateEmployeeSkill,
  updateEmploymentAssignment,
} from '../../lib/employeeRelatedApi'
import { fetchLocations } from '../../lib/locationApi'
import { fetchPayrollGroups } from '../../lib/payrollGroupApi'
import type { PayrollGroup } from '../../lib/payrollGroupApi'
import type { Company } from '../../types/company'
import type { Employee } from '../../types/employee'
import type { Location } from '../../types/location'
import { OPERATIONAL_GROUPS } from '../../types/employeeRelated'
import type {
  EmployeeSkill,
  EmployeeSkillWritePayload,
  EmploymentAssignment,
  EmploymentAssignmentWritePayload,
} from '../../types/employeeRelated'
import type { OrgUnit } from '../../types/orgUnit'

const inputClassName = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-100'
const labelClassName = 'text-xs font-semibold text-slate-700'
const optionalDate = z.union([z.literal(''), z.iso.date('Enter a valid date.')])
const optionalUuid = z.union([z.literal(''), z.uuid('Must be a valid UUID.')])

function nullable(value: string) {
  return value.trim() || null
}

function employeeLabel(employee: Employee) {
  return `${employee.employee_no} — ${employee.first_name} ${employee.last_name}`
}

function errorText(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

// The panels live inside the employee <form>; stop Enter from submitting it.
function blockEnterSubmit(event: KeyboardEvent<HTMLDivElement>) {
  if (event.key === 'Enter' && event.target instanceof HTMLInputElement) event.preventDefault()
}

function FieldError({ message }: { message?: string }) {
  return message ? <p className="mt-1 text-xs font-medium text-rose-600">{message}</p> : null
}

function useRelatedRecords<T extends { id: string }>(employeeId: string | null, fetcher: (id: string) => Promise<T[]>, fallback: string) {
  const [records, setRecords] = useState<T[]>([])
  const [isLoading, setIsLoading] = useState(Boolean(employeeId))
  const [errorMessage, setErrorMessage] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  useEffect(() => {
    if (!employeeId) return
    let isCurrent = true
    fetcher(employeeId)
      .then((result) => {
        if (!isCurrent) return
        if (Array.isArray(result)) setRecords(result)
        else setErrorMessage(fallback)
      })
      .catch((error: unknown) => { if (isCurrent) setErrorMessage(errorText(error, fallback)) })
      .finally(() => { if (isCurrent) setIsLoading(false) })
    return () => { isCurrent = false }
  }, [employeeId, fetcher, fallback])

  useEffect(() => {
    if (!successMessage) return
    const timeout = window.setTimeout(() => setSuccessMessage(''), 5000)
    return () => window.clearTimeout(timeout)
  }, [successMessage])

  function upsert(record: T) {
    setRecords((current) => current.some((item) => item.id === record.id)
      ? current.map((item) => item.id === record.id ? record : item)
      : [record, ...current])
  }

  return { records, isLoading, errorMessage, setErrorMessage, successMessage, setSuccessMessage, upsert }
}

function PanelShell({ title, errorMessage, successMessage, children }: { title: string; errorMessage: string; successMessage: string; children: ReactNode }) {
  return (
    <div className="space-y-4" onKeyDown={blockEnterSubmit}>
      <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">{title}</h3>
      {errorMessage && <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
      {successMessage && <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{successMessage}</p>}
      {children}
    </div>
  )
}

function SaveEmployeeFirst({ label }: { label: string }) {
  return (
    <p className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      Create the employee record first, then reopen it to add {label}.
    </p>
  )
}

function EditorActions({ isEditing, isSubmitting, onSave, onCancel }: { isEditing: boolean; isSubmitting: boolean; onSave: () => void; onCancel: () => void }) {
  return (
    <div className="flex justify-end gap-2 sm:col-span-2 lg:col-span-3">
      {isEditing && (
        <button type="button" onClick={onCancel} className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
          New instead
        </button>
      )}
      <button type="button" onClick={onSave} disabled={isSubmitting} className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60">
        {isSubmitting ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Plus className="h-3.5 w-3.5" aria-hidden="true" />}
        {isSubmitting ? 'Saving...' : isEditing ? 'Save changes' : 'Add'}
      </button>
    </div>
  )
}

function StatusBadge({ status, isActive }: { status: string; isActive: boolean }) {
  const isGood = isActive && (status === 'ACTIVE' || status === 'VALID')
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-bold ${isGood ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
      {isActive ? status : `${status} (disabled)`}
    </span>
  )
}

const assignmentSchema = z.object({
  company_id: z.string().min(1, 'Company is required.'),
  org_unit_id: z.string(),
  position_id: optionalUuid,
  supervisor_employee_id: z.string(),
  employment_type: z.string().trim().min(1, 'Employment type is required.').max(30),
  employee_category: z.string().trim().min(1, 'Employee category is required.').max(30),
  operational_group: z.union([z.literal(''), z.enum(OPERATIONAL_GROUPS)]),
  payroll_group_id: optionalUuid,
  primary_location_id: optionalUuid,
  hire_date: z.iso.date('Hire date is required.'),
  effective_from: z.iso.date('Effective from is required.'),
  effective_to: optionalDate,
  separation_date: optionalDate,
  status: z.string().trim().min(1, 'Status is required.').max(30),
  is_active: z.boolean(),
}).superRefine((values, context) => {
  if (values.effective_to && values.effective_to < values.effective_from) {
    context.addIssue({ code: 'custom', path: ['effective_to'], message: 'Must be on or after effective from.' })
  }
  if (values.separation_date && values.separation_date < values.hire_date) {
    context.addIssue({ code: 'custom', path: ['separation_date'], message: 'Must be on or after hire date.' })
  }
})

type AssignmentFormValues = z.infer<typeof assignmentSchema>

const emptyAssignment: AssignmentFormValues = {
  company_id: '', org_unit_id: '', position_id: '', supervisor_employee_id: '',
  employment_type: '', employee_category: '', operational_group: '',
  payroll_group_id: '', primary_location_id: '', hire_date: '', effective_from: '',
  effective_to: '', separation_date: '', status: 'ACTIVE', is_active: true,
}

function assignmentToForm(assignment: EmploymentAssignment): AssignmentFormValues {
  return {
    company_id: assignment.company_id,
    org_unit_id: assignment.org_unit_id ?? '',
    position_id: assignment.position_id ?? '',
    supervisor_employee_id: assignment.supervisor_employee_id ?? '',
    employment_type: assignment.employment_type,
    employee_category: assignment.employee_category,
    operational_group: assignment.operational_group ?? '',
    payroll_group_id: assignment.payroll_group_id ?? '',
    primary_location_id: assignment.primary_location_id ?? '',
    hire_date: assignment.hire_date,
    effective_from: assignment.effective_from,
    effective_to: assignment.effective_to ?? '',
    separation_date: assignment.separation_date ?? '',
    status: assignment.status,
    is_active: assignment.is_active,
  }
}

interface AssignmentsPanelProps {
  employee: Employee | null
  employees: Employee[]
  companies: Company[]
  orgUnits: OrgUnit[]
}

export function EmploymentAssignmentsPanel({ employee, employees, companies, orgUnits }: AssignmentsPanelProps) {
  const related = useRelatedRecords(employee?.id ?? null, fetchEmploymentAssignments, 'Could not load employment assignments.')
  const [editingId, setEditingId] = useState<string | null>(null)
  const { register, handleSubmit, reset, watch, setValue, formState: { errors, isSubmitting } } = useForm<AssignmentFormValues>({
    defaultValues: emptyAssignment,
    resolver: zodResolver(assignmentSchema),
  })
  const selectedCompanyId = watch('company_id')
  const autoLoaded = useRef(false)
  const [locations, setLocations] = useState<Location[]>([])
  const [isLoadingLocations, setIsLoadingLocations] = useState(true)
  const [locationsError, setLocationsError] = useState('')
  const [payrollGroups, setPayrollGroups] = useState<PayrollGroup[]>([])
  const [payrollGroupsLoad, setPayrollGroupsLoad] = useState<{
    loaded: boolean
    error: string
  }>({ loaded: false, error: '' })

  useEffect(() => {
    let isCurrent = true
    fetchLocations()
      .then((items) => {
        if (isCurrent) setLocations(items)
      })
      .catch((error: unknown) => {
        if (isCurrent) setLocationsError(errorText(error, 'Could not load locations.'))
      })
      .finally(() => {
        if (isCurrent) setIsLoadingLocations(false)
      })
    return () => { isCurrent = false }
  }, [])

  useEffect(() => {
    let isCurrent = true
    fetchPayrollGroups()
      .then((groups) => {
        if (!isCurrent) return
        setPayrollGroups(groups)
        setPayrollGroupsLoad({ loaded: true, error: '' })
      })
      .catch((error: unknown) => {
        if (!isCurrent) return
        setPayrollGroupsLoad({
          loaded: true,
          error: errorText(error, 'Could not load payroll groups.'),
        })
      })
    return () => { isCurrent = false }
  }, [])

  useEffect(() => {
    if (autoLoaded.current || related.isLoading || related.records.length === 0) return
    autoLoaded.current = true
    setEditingId(related.records[0].id)
    reset(assignmentToForm(related.records[0]))
  }, [related.isLoading, related.records, reset])
  const companyOrgUnits = orgUnits.filter((orgUnit) => orgUnit.company_id === selectedCompanyId)
  const companyLocations = locations.filter((location) => location.company_id === selectedCompanyId)
  const companyPayrollGroups = payrollGroups.filter((group) => group.company_id === selectedCompanyId)
  const selectedPayrollGroupId = watch('payroll_group_id')
  const selectedPayrollGroup = companyPayrollGroups.find((group) => group.id === selectedPayrollGroupId)
  const isLoadingPayrollGroups = !payrollGroupsLoad.loaded
  const selectedLocationId = watch('primary_location_id')
  const selectedLocation = companyLocations.find((location) => location.id === selectedLocationId)

  if (!employee) {
    return <PanelShell title="Employment assignments" errorMessage="" successMessage=""><SaveEmployeeFirst label="employment assignments" /></PanelShell>
  }
  const employeeId = employee.id

  function startEdit(assignment: EmploymentAssignment) {
    related.setErrorMessage('')
    setEditingId(assignment.id)
    reset(assignmentToForm(assignment))
  }

  function cancelEdit() {
    setEditingId(null)
    reset(emptyAssignment)
  }

  async function save(values: AssignmentFormValues) {
    related.setErrorMessage('')
    related.setSuccessMessage('')
    const payload: EmploymentAssignmentWritePayload = {
      employee_id: employeeId,
      company_id: values.company_id,
      org_unit_id: nullable(values.org_unit_id),
      position_id: nullable(values.position_id),
      supervisor_employee_id: nullable(values.supervisor_employee_id),
      employment_type: values.employment_type,
      employee_category: values.employee_category,
      operational_group: values.operational_group || null,
      payroll_group_id: nullable(values.payroll_group_id),
      primary_location_id: nullable(values.primary_location_id),
      hire_date: values.hire_date,
      effective_from: values.effective_from,
      effective_to: nullable(values.effective_to),
      separation_date: nullable(values.separation_date),
      status: values.status,
      is_active: values.is_active,
    }
    try {
      const saved = editingId
        ? await updateEmploymentAssignment(editingId, payload)
        : await createEmploymentAssignment(payload)
      related.upsert(saved)
      related.setSuccessMessage(`Employment assignment ${editingId ? 'updated' : 'added'} successfully.`)
      cancelEdit()
    } catch (error) {
      related.setErrorMessage(errorText(error, 'Could not save the employment assignment.'))
    }
  }

  const companyName = (id: string) => companies.find((company) => company.id === id)?.legal_name ?? '—'
  const orgUnitName = (id: string | null) => orgUnits.find((orgUnit) => orgUnit.id === id)?.org_unit_name ?? '—'
  const locationName = (id: string | null) => {
    if (!id) return 'No primary location'
    return locations.find((location) => location.id === id)?.location_name ?? 'Location unavailable'
  }

  return (
    <PanelShell title="Employment assignments" errorMessage={related.errorMessage} successMessage={related.successMessage}>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Company / Org unit / Location</th>
              <th className="px-3 py-2">Payroll group</th>
              <th className="px-3 py-2">Type / Category</th>
              <th className="px-3 py-2">Effective</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {related.isLoading && <tr><td colSpan={6} className="px-3 py-3 text-slate-500">Loading assignments…</td></tr>}
            {!related.isLoading && related.records.length === 0 && <tr><td colSpan={6} className="px-3 py-3 text-slate-500">No employment assignments yet.</td></tr>}
            {related.records.map((assignment) => (
              <tr key={assignment.id} className={editingId === assignment.id ? 'bg-indigo-50' : ''}>
                <td className="px-3 py-2"><p className="font-semibold text-slate-900">{companyName(assignment.company_id)}</p><p className="text-slate-500">{orgUnitName(assignment.org_unit_id)} · {locationName(assignment.primary_location_id)}</p></td>
                <td className="px-3 py-2">{payrollGroups.find((group) => group.id === assignment.payroll_group_id)?.payroll_group_name ?? (assignment.payroll_group_id ? 'Group unavailable' : '—')}</td>
                <td className="px-3 py-2"><p>{assignment.employment_type}</p><p className="text-slate-500">{assignment.employee_category}{assignment.operational_group ? ` · ${assignment.operational_group}` : ''}</p></td>
                <td className="px-3 py-2">{assignment.effective_from} → {assignment.effective_to ?? 'present'}</td>
                <td className="px-3 py-2"><StatusBadge status={assignment.status} isActive={assignment.is_active} /></td>
                <td className="px-3 py-2 text-right">
                  <button type="button" onClick={() => startEdit(assignment)} aria-label="Edit assignment" className="rounded-md p-1.5 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700"><Pencil className="h-3.5 w-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
        <h4 className="text-xs font-bold text-slate-700">{editingId ? 'Edit assignment' : 'Add assignment'}</h4>
        <div key={editingId ?? 'new'} className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className={labelClassName}>Company
            <select {...register('company_id', {
              onChange: () => {
                setValue('org_unit_id', '')
                setValue('primary_location_id', '')
                setValue('payroll_group_id', '')
              },
            })} className={inputClassName}>
              <option value="">Select company</option>
              {companies.map((company) => <option key={company.id} value={company.id}>{company.company_code} — {company.legal_name}</option>)}
            </select>
            <FieldError message={errors.company_id?.message} />
          </label>
          <label className={labelClassName}>Org unit
            <select {...register('org_unit_id')} disabled={!selectedCompanyId} className={inputClassName}>
              <option value="">None</option>
              {companyOrgUnits.map((orgUnit) => <option key={orgUnit.id} value={orgUnit.id}>{orgUnit.org_unit_code} — {orgUnit.org_unit_name}</option>)}
            </select>
          </label>
          <label className={labelClassName}>Primary location
            <select
              {...register('primary_location_id')}
              disabled={!selectedCompanyId || isLoadingLocations}
              className={inputClassName}
            >
              <option value="">{isLoadingLocations ? 'Loading locations…' : 'Not assigned (clock-in disabled)'}</option>
              {selectedLocationId && !selectedLocation && (
                <option value={selectedLocationId}>Previously assigned location</option>
              )}
              {companyLocations
                .filter((location) => location.is_active && location.status === 'ACTIVE')
                .map((location) => (
                  <option key={location.id} value={location.id}>
                    {location.location_code} — {location.location_name}
                  </option>
                ))}
              {selectedLocation && (!selectedLocation.is_active || selectedLocation.status !== 'ACTIVE') && (
                <option value={selectedLocation.id}>
                  {selectedLocation.location_code} — {selectedLocation.location_name} (inactive)
                </option>
              )}
            </select>
            <FieldError message={errors.primary_location_id?.message} />
            {locationsError && <span className="mt-1 block text-xs font-medium text-rose-600">{locationsError}</span>}
            <span className="mt-1 block text-[11px] font-normal text-slate-500">Clock-in also requires an active geofence for this location.</span>
          </label>
          <label className={labelClassName}>Supervisor
            <select {...register('supervisor_employee_id')} className={inputClassName}>
              <option value="">None</option>
              {employees.filter((item) => item.id !== employeeId).map((item) => <option key={item.id} value={item.id}>{employeeLabel(item)}</option>)}
            </select>
          </label>
          <label className={labelClassName}>Employment type<input {...register('employment_type')} placeholder="e.g. REGULAR" className={inputClassName} /><FieldError message={errors.employment_type?.message} /></label>
          <label className={labelClassName}>Employee category<input {...register('employee_category')} placeholder="e.g. RANK_AND_FILE" className={inputClassName} /><FieldError message={errors.employee_category?.message} /></label>
          <label className={labelClassName}>Operational group
            <select {...register('operational_group')} className={inputClassName}>
              <option value="">None</option>
              {OPERATIONAL_GROUPS.map((group) => <option key={group} value={group}>{group}</option>)}
            </select>
          </label>
          <label className={labelClassName}>Hire date<input type="date" {...register('hire_date')} className={inputClassName} /><FieldError message={errors.hire_date?.message} /></label>
          <label className={labelClassName}>Effective from<input type="date" {...register('effective_from')} className={inputClassName} /><FieldError message={errors.effective_from?.message} /></label>
          <label className={labelClassName}>Effective to<input type="date" {...register('effective_to')} className={inputClassName} /><FieldError message={errors.effective_to?.message} /></label>
          <label className={labelClassName}>Separation date<input type="date" {...register('separation_date')} className={inputClassName} /><FieldError message={errors.separation_date?.message} /></label>
          <label className={labelClassName}>Position ID<input {...register('position_id')} placeholder="UUID (optional)" className={inputClassName} /><FieldError message={errors.position_id?.message} /></label>
          <label className={labelClassName}>Payroll group
            <select {...register('payroll_group_id')} disabled={!selectedCompanyId || isLoadingPayrollGroups} className={inputClassName}>
              <option value="">{isLoadingPayrollGroups ? 'Loading payroll groups…' : 'None'}</option>
              {selectedPayrollGroupId && !selectedPayrollGroup && (
                <option value={selectedPayrollGroupId}>Previously assigned payroll group</option>
              )}
              {companyPayrollGroups
                .filter((group) => (group.is_active && group.status === 'ACTIVE') || group.id === selectedPayrollGroupId)
                .map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.payroll_group_code} — {group.payroll_group_name}
                    {group.is_active && group.status === 'ACTIVE' ? '' : ' (inactive)'}
                  </option>
                ))}
            </select>
            <FieldError message={errors.payroll_group_id?.message} />
            {payrollGroupsLoad.error && <span className="mt-1 block text-xs font-medium text-rose-600">{payrollGroupsLoad.error}</span>}
          </label>
          <label className={labelClassName}>Status<input {...register('status')} className={inputClassName} /><FieldError message={errors.status?.message} /></label>
          <label className="flex items-center gap-3 self-end rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700"><input type="checkbox" {...register('is_active')} className="h-4 w-4 accent-indigo-600" />Enabled for use</label>
          <EditorActions isEditing={Boolean(editingId)} isSubmitting={isSubmitting} onSave={handleSubmit(save)} onCancel={cancelEdit} />
        </div>
      </section>
    </PanelShell>
  )
}

const skillSchema = z.object({
  skill_code: z.string().trim().min(1, 'Skill code is required.').max(50),
  proficiency_level: z.string().trim().max(30),
  certification_no: z.string().trim().max(100),
  issued_date: optionalDate,
  expiry_date: optionalDate,
  verified_by: z.string(),
  status: z.string().trim().min(1, 'Status is required.').max(20),
  is_active: z.boolean(),
}).superRefine((values, context) => {
  if (values.issued_date && values.expiry_date && values.expiry_date < values.issued_date) {
    context.addIssue({ code: 'custom', path: ['expiry_date'], message: 'Must be on or after issued date.' })
  }
})

type SkillFormValues = z.infer<typeof skillSchema>

const emptySkill: SkillFormValues = {
  skill_code: '', proficiency_level: '', certification_no: '', issued_date: '',
  expiry_date: '', verified_by: '', status: 'VALID', is_active: true,
}

function skillToForm(skill: EmployeeSkill): SkillFormValues {
  return {
    skill_code: skill.skill_code,
    proficiency_level: skill.proficiency_level ?? '',
    certification_no: skill.certification_no ?? '',
    issued_date: skill.issued_date ?? '',
    expiry_date: skill.expiry_date ?? '',
    verified_by: skill.verified_by ?? '',
    status: skill.status,
    is_active: skill.is_active,
  }
}

interface SkillsPanelProps {
  employee: Employee | null
  employees: Employee[]
}

export function EmployeeSkillsPanel({ employee, employees }: SkillsPanelProps) {
  const related = useRelatedRecords(employee?.id ?? null, fetchEmployeeSkills, 'Could not load employee skills.')
  const [editingId, setEditingId] = useState<string | null>(null)
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<SkillFormValues>({
    defaultValues: emptySkill,
    resolver: zodResolver(skillSchema),
  })
  const autoLoaded = useRef(false)

  useEffect(() => {
    if (autoLoaded.current || related.isLoading || related.records.length === 0) return
    autoLoaded.current = true
    setEditingId(related.records[0].id)
    reset(skillToForm(related.records[0]))
  }, [related.isLoading, related.records, reset])

  if (!employee) {
    return <PanelShell title="Skills" errorMessage="" successMessage=""><SaveEmployeeFirst label="skills" /></PanelShell>
  }
  const employeeId = employee.id

  function startEdit(skill: EmployeeSkill) {
    related.setErrorMessage('')
    setEditingId(skill.id)
    reset(skillToForm(skill))
  }

  function cancelEdit() {
    setEditingId(null)
    reset(emptySkill)
  }

  async function save(values: SkillFormValues) {
    related.setErrorMessage('')
    related.setSuccessMessage('')
    const payload: EmployeeSkillWritePayload = {
      employee_id: employeeId,
      skill_code: values.skill_code,
      proficiency_level: nullable(values.proficiency_level),
      certification_no: nullable(values.certification_no),
      issued_date: nullable(values.issued_date),
      expiry_date: nullable(values.expiry_date),
      verified_by: nullable(values.verified_by),
      status: values.status,
      is_active: values.is_active,
    }
    try {
      const saved = editingId ? await updateEmployeeSkill(editingId, payload) : await createEmployeeSkill(payload)
      related.upsert(saved)
      related.setSuccessMessage(`Skill ${saved.skill_code} ${editingId ? 'updated' : 'added'} successfully.`)
      cancelEdit()
    } catch (error) {
      related.setErrorMessage(errorText(error, 'Could not save the employee skill.'))
    }
  }

  const verifierName = (id: string | null) => {
    const verifier = employees.find((item) => item.id === id)
    return verifier ? employeeLabel(verifier) : '—'
  }

  return (
    <PanelShell title="Skills" errorMessage={related.errorMessage} successMessage={related.successMessage}>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Skill</th>
              <th className="px-3 py-2">Certification</th>
              <th className="px-3 py-2">Validity</th>
              <th className="px-3 py-2">Verified by</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {related.isLoading && <tr><td colSpan={6} className="px-3 py-3 text-slate-500">Loading skills…</td></tr>}
            {!related.isLoading && related.records.length === 0 && <tr><td colSpan={6} className="px-3 py-3 text-slate-500">No skills yet.</td></tr>}
            {related.records.map((skill) => (
              <tr key={skill.id} className={editingId === skill.id ? 'bg-indigo-50' : ''}>
                <td className="px-3 py-2"><p className="font-semibold text-slate-900">{skill.skill_code}</p><p className="text-slate-500">{skill.proficiency_level ?? '—'}</p></td>
                <td className="px-3 py-2">{skill.certification_no ?? '—'}</td>
                <td className="px-3 py-2">{skill.issued_date ?? '—'} → {skill.expiry_date ?? 'no expiry'}</td>
                <td className="px-3 py-2">{verifierName(skill.verified_by)}</td>
                <td className="px-3 py-2"><StatusBadge status={skill.status} isActive={skill.is_active} /></td>
                <td className="px-3 py-2 text-right">
                  <button type="button" onClick={() => startEdit(skill)} aria-label={`Edit skill ${skill.skill_code}`} className="rounded-md p-1.5 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700"><Pencil className="h-3.5 w-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
        <h4 className="text-xs font-bold text-slate-700">{editingId ? 'Edit skill' : 'Add skill'}</h4>
        <div key={editingId ?? 'new'} className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className={labelClassName}>Skill code<input {...register('skill_code')} placeholder="e.g. FORKLIFT" className={inputClassName} /><FieldError message={errors.skill_code?.message} /></label>
          <label className={labelClassName}>Proficiency level<input {...register('proficiency_level')} placeholder="e.g. INTERMEDIATE" className={inputClassName} /><FieldError message={errors.proficiency_level?.message} /></label>
          <label className={labelClassName}>Certification number<input {...register('certification_no')} className={inputClassName} /><FieldError message={errors.certification_no?.message} /></label>
          <label className={labelClassName}>Issued date<input type="date" {...register('issued_date')} className={inputClassName} /><FieldError message={errors.issued_date?.message} /></label>
          <label className={labelClassName}>Expiry date<input type="date" {...register('expiry_date')} className={inputClassName} /><FieldError message={errors.expiry_date?.message} /></label>
          <label className={labelClassName}>Verified by
            <select {...register('verified_by')} className={inputClassName}>
              <option value="">None</option>
              {employees.map((item) => <option key={item.id} value={item.id}>{employeeLabel(item)}</option>)}
            </select>
          </label>
          <label className={labelClassName}>Status<input {...register('status')} className={inputClassName} /><FieldError message={errors.status?.message} /></label>
          <label className="flex items-center gap-3 self-end rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700"><input type="checkbox" {...register('is_active')} className="h-4 w-4 accent-indigo-600" />Enabled for use</label>
          <EditorActions isEditing={Boolean(editingId)} isSubmitting={isSubmitting} onSave={handleSubmit(save)} onCancel={cancelEdit} />
        </div>
      </section>
    </PanelShell>
  )
}
