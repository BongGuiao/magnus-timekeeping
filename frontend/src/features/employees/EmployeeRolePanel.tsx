import { useEffect, useState } from 'react'
import { AxiosError } from 'axios'
import { AlertCircle, CalendarDays, CheckCircle2, LoaderCircle, Plus, ShieldCheck, UserRoundCog } from 'lucide-react'
import {
  createUserRoleAssignment,
  fetchAvailableRoles,
  fetchUserRoleAssignments,
  updateUserRoleAssignment,
} from '../../lib/userRoleApi'
import type { AvailableRole, CreateUserRolePayload, UserRoleAssignment } from '../../lib/userRoleApi'
import {
  EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT,
  fetchEmploymentAssignments,
  getManilaDate,
  isCurrentEmploymentAssignment,
} from '../../lib/employeeRelatedApi'
import type { ApiErrorEnvelope } from '../../types/auth'
import type { Company } from '../../types/company'
import type { Employee } from '../../types/employee'
import type { OrgUnit } from '../../types/orgUnit'

const inputClassName = 'mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500'
const labelClassName = 'text-xs font-semibold text-slate-700'

function errorText(error: unknown): string {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    return body?.detail ?? 'Could not save or load employee roles.'
  }
  return error instanceof Error ? error.message : 'Could not save or load employee roles.'
}

function assignmentIsCurrent(assignment: UserRoleAssignment, today: string): boolean {
  return assignment.effective_from <= today
    && (!assignment.effective_to || assignment.effective_to >= today)
}

function scopeLabel(
  assignment: UserRoleAssignment,
  companiesById: Map<string, Company>,
  orgUnitsById: Map<string, OrgUnit>,
): string {
  const companyName = assignment.company_id
    ? companiesById.get(assignment.company_id)?.trade_name
      ?? companiesById.get(assignment.company_id)?.legal_name
      ?? 'Company'
    : ''
  const orgUnitName = assignment.org_unit_id
    ? orgUnitsById.get(assignment.org_unit_id)?.org_unit_name ?? 'Org unit'
    : ''
  if (companyName && orgUnitName) return `${companyName} · ${orgUnitName}`
  if (companyName) return companyName
  if (orgUnitName) return orgUnitName
  return 'Global'
}

interface Props {
  employee: Employee | null
  companies: Company[]
  orgUnits: OrgUnit[]
}

export default function EmployeeRolePanel({ employee, companies, orgUnits }: Props) {
  const employeeId = employee?.id ?? ''
  const [roles, setRoles] = useState<AvailableRole[]>([])
  const [assignments, setAssignments] = useState<UserRoleAssignment[]>([])
  const [roleId, setRoleId] = useState('')
  const [companyId, setCompanyId] = useState('')
  const [orgUnitId, setOrgUnitId] = useState('')
  const [effectiveFrom, setEffectiveFrom] = useState(getManilaDate())
  const [isLoading, setIsLoading] = useState(Boolean(employeeId))
  const [isSaving, setIsSaving] = useState(false)
  const [endingAssignmentId, setEndingAssignmentId] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const today = getManilaDate()

  useEffect(() => {
    if (!employeeId) {
      return
    }
    let current = true
    const loadRoleData = async () => {
      setIsLoading(true)
      try {
        const [availableRoles, userRoles, employmentAssignments] = await Promise.all([
          fetchAvailableRoles(),
          fetchUserRoleAssignments(employeeId),
          fetchEmploymentAssignments(employeeId),
        ])
        if (!current) return
        setRoles(availableRoles)
        setAssignments(userRoles)
        const currentAssignment = employmentAssignments.find((assignment) =>
          isCurrentEmploymentAssignment(assignment),
        )
        setCompanyId(currentAssignment?.company_id ?? '')
        setOrgUnitId('')
        setError('')
      } catch (cause: unknown) {
        if (current) {
          setCompanyId('')
          setOrgUnitId('')
          setError(errorText(cause))
        }
      } finally {
        if (current) setIsLoading(false)
      }
    }
    void loadRoleData()
    window.addEventListener(EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT, loadRoleData)
    return () => {
      current = false
      window.removeEventListener(EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT, loadRoleData)
    }
  }, [employeeId])

  async function refreshAssignments() {
    if (!employeeId) return
    setAssignments(await fetchUserRoleAssignments(employeeId))
  }

  async function assignRole() {
    if (!employeeId || !roleId || !companyId || !effectiveFrom || isSaving) return
    const hasOverlappingRole = assignments.some((assignment) =>
      assignment.role_id === roleId
      && assignment.company_id === (companyId || null)
      && assignment.org_unit_id === (orgUnitId || null)
      && (!assignment.effective_to || assignment.effective_to >= effectiveFrom),
    )
    if (hasOverlappingRole) {
      setError('This employee already has an overlapping assignment for the selected role.')
      return
    }
    const payload: CreateUserRolePayload = {
      user_id: employeeId,
      role_id: roleId,
      company_id: companyId,
      org_unit_id: orgUnitId || null,
      effective_from: effectiveFrom,
      effective_to: null,
    }
    setIsSaving(true)
    setError('')
    setNotice('')
    try {
      await createUserRoleAssignment(payload)
      await refreshAssignments()
      setEffectiveFrom(today)
      setNotice('Employee role assigned.')
    } catch (cause) {
      setError(errorText(cause))
    } finally {
      setIsSaving(false)
    }
  }

  async function endAssignment(assignment: UserRoleAssignment) {
    if (assignment.effective_from > today || !assignmentIsCurrent(assignment, today)) return
    setEndingAssignmentId(assignment.id)
    setError('')
    setNotice('')
    try {
      await updateUserRoleAssignment(assignment.id, { effective_to: today })
      await refreshAssignments()
      setNotice('Employee role ended.')
    } catch (cause) {
      setError(errorText(cause))
    } finally {
      setEndingAssignmentId('')
    }
  }

  if (!employee) {
    return (
      <div className="flex flex-col items-center rounded-xl border border-dashed border-slate-300 bg-slate-50 px-6 py-10 text-center">
        <span className="mb-3 rounded-xl border border-slate-200 bg-white p-3 text-indigo-600"><UserRoundCog className="h-6 w-6" aria-hidden="true" /></span>
        <h3 className="text-sm font-bold text-slate-900">Create the employee first</h3>
        <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">Save the employee record, then reopen it to manage assigned roles.</p>
      </div>
    )
  }

  const rolesById = new Map(roles.map((role) => [role.id, role]))
  const companiesById = new Map(companies.map((company) => [company.id, company]))
  const orgUnitsById = new Map(orgUnits.map((orgUnit) => [orgUnit.id, orgUnit]))
  const activeAssignmentCount = assignments.filter((assignment) => assignmentIsCurrent(assignment, today)).length
  const scopedOrgUnits = orgUnits.filter((orgUnit) =>
    orgUnit.company_id === companyId
    && orgUnit.is_active
    && orgUnit.status === 'ACTIVE',
  )

  return (
    <div className="mx-auto max-w-5xl space-y-5" aria-busy={isLoading || isSaving || Boolean(endingAssignmentId)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="rounded-xl bg-indigo-50 p-2.5 text-indigo-600"><ShieldCheck className="h-5 w-5" aria-hidden="true" /></span>
          <div>
            <h3 className="text-base font-bold text-slate-900">Employee roles</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">Manage access roles assigned to {employee.first_name} {employee.last_name}.</p>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1.5 text-[11px] font-semibold text-indigo-700">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />Access management
        </span>
      </div>

      {isLoading && <p role="status" className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600"><LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />Loading employee roles...</p>}
      {error && <p role="alert" className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-xs leading-5 text-rose-700"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />{error}</p>}
      {notice && <p role="status" className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs text-emerald-800"><CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />{notice}</p>}

      <fieldset disabled={isLoading || isSaving || Boolean(endingAssignmentId)} className="min-w-0 space-y-5">
        <legend className="sr-only">Employee role assignments</legend>
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50/70 px-5 py-3">
            <Plus className="h-4 w-4 text-indigo-600" aria-hidden="true" />
            <h4 className="text-xs font-bold text-slate-800">Assign a role</h4>
          </div>
          <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)_180px_auto] lg:items-end">
            <label className={labelClassName}>Role <span className="font-normal text-slate-400">(required)</span>
              <select value={roleId} onChange={(event) => setRoleId(event.target.value)} className={inputClassName}>
                <option value="">Select a role</option>
                {roles.map((role) => <option key={role.id} value={role.id}>{role.role_name} ({role.role_code})</option>)}
              </select>
            </label>
            <label className={labelClassName}>Employment assignment company
              <select value={companyId} disabled className={inputClassName}>
                <option value="">{isLoading ? 'Loading assignment company…' : 'No employment assignment company'}</option>
                {companyId && (
                  <option value={companyId}>
                    {companies.find((company) => company.id === companyId)?.trade_name
                      ?? companies.find((company) => company.id === companyId)?.legal_name
                      ?? 'Assigned company'}
                  </option>
                )}
              </select>
            </label>
            <label className={labelClassName}>Org unit scope
              <select value={orgUnitId} onChange={(event) => setOrgUnitId(event.target.value)} disabled={!companyId} className={inputClassName}>
                <option value="">All org units</option>
                {scopedOrgUnits.map((orgUnit) => <option key={orgUnit.id} value={orgUnit.id}>{orgUnit.org_unit_code} — {orgUnit.org_unit_name}</option>)}
              </select>
            </label>
            <label className={labelClassName}>Effective from <span className="font-normal text-slate-400">(required)</span>
              <input type="date" value={effectiveFrom} onChange={(event) => setEffectiveFrom(event.target.value)} className={inputClassName} />
            </label>
            <button type="button" onClick={() => void assignRole()} disabled={!roleId || !companyId || !effectiveFrom || isLoading || isSaving} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 text-xs font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">
              {isSaving ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Plus className="h-4 w-4" aria-hidden="true" />}
              {isSaving ? 'Assigning...' : 'Assign role'}
            </button>
          </div>
          <p className="px-5 pb-5 text-[11px] leading-5 text-slate-500">
            Role assignments are scoped to the company on the employee&apos;s most recent employment assignment. An org unit can be selected within that company.
          </p>
          {!isLoading && !companyId && (
            <p className="px-5 pb-5 text-xs text-amber-800">Add an employment assignment before assigning a company-scoped role.</p>
          )}
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/70 px-5 py-3">
            <div className="flex items-center gap-2">
              <UserRoundCog className="h-4 w-4 text-indigo-600" aria-hidden="true" />
              <h4 className="text-xs font-bold text-slate-800">Assigned roles</h4>
            </div>
            <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-[11px] font-bold text-indigo-700">{activeAssignmentCount} active</span>
          </div>
          {assignments.length === 0
            ? <p className="px-5 py-8 text-center text-xs text-slate-500">{isLoading ? 'Loading assignments...' : 'No role assignments have been added.'}</p>
            : <ul className="divide-y divide-slate-100">
              {assignments.map((assignment) => {
                const role = rolesById.get(assignment.role_id)
                const isCurrent = assignmentIsCurrent(assignment, today)
                const isFuture = assignment.effective_from > today
                return (
                  <li key={assignment.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-semibold text-slate-900">{role?.role_name ?? 'Unknown role'}</p>
                        {role && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-600">{role.role_code}</span>}
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${isCurrent ? 'bg-emerald-50 text-emerald-700' : isFuture ? 'bg-indigo-50 text-indigo-700' : 'bg-slate-100 text-slate-600'}`}>
                          {isCurrent ? 'Active' : isFuture ? 'Scheduled' : 'Expired'}
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
                        <span className="inline-flex items-center gap-1"><CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />{assignment.effective_from} – {assignment.effective_to ?? 'No end date'}</span>
                        <span>{scopeLabel(assignment, companiesById, orgUnitsById)}</span>
                      </div>
                      {role?.description && <p className="mt-1 text-[11px] leading-5 text-slate-500">{role.description}</p>}
                    </div>
                    {isCurrent && !isFuture && assignment.effective_to !== today && (
                      <button type="button" onClick={() => void endAssignment(assignment)} className="inline-flex shrink-0 items-center justify-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-50">
                        {endingAssignmentId === assignment.id ? 'Ending...' : 'End role today'}
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>}
        </section>

        <div className="flex items-start gap-2 rounded-lg border border-indigo-100 bg-indigo-50/60 p-4">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" aria-hidden="true" />
          <p className="text-[11px] leading-5 text-indigo-900">Role changes take effect according to their effective dates. Ending an assignment preserves its history instead of deleting it.</p>
        </div>
      </fieldset>
    </div>
  )
}
