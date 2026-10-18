import { useEffect, useId, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { Pencil, Plus, Users } from 'lucide-react'
import { z } from 'zod'
import DataTable from '../components/common/DataTable'
import type { DataTableColumn } from '../components/common/DataTable'
import FormModal from '../components/common/FormModal'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { apiClient } from '../lib/apiClient'
import { createEmployee, EMPLOYEE_CREATED_EVENT, fetchEmployee, fetchEmployees, updateEmployee } from '../lib/employeeApi'
import type { EmployeeWritePayload } from '../lib/employeeApi'
import { fetchCompanies } from '../lib/companyApi'
import { fetchOrgUnits } from '../lib/orgUnitApi'
import { EmployeeSkillsPanel, EmploymentAssignmentsPanel } from '../features/employees/EmployeeRelatedPanels'
import EmployeeEntitlementsPanel from '../features/employees/EmployeeEntitlementsPanel'
import EmployeeScheduleAssignmentsPanel from '../features/employees/EmployeeScheduleAssignmentsPanel'
import EmployeeFaceEnrollmentPanel from '../features/employees/EmployeeFaceEnrollmentPanel'
import EmployeeWfhPanel from '../features/employees/EmployeeWfhPanel'
import EmployeeRolePanel from '../features/employees/EmployeeRolePanel'
import type { Company } from '../types/company'
import type { Employee } from '../types/employee'
import type { OrgUnit } from '../types/orgUnit'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

type EmployeeTab = 'details' | 'assignments' | 'entitlements' | 'skills' | 'schedule' | 'face' | 'wfh' | 'role'

const employeeTabs: { id: EmployeeTab; label: string }[] = [
  { id: 'details', label: 'Employee Details' },
  { id: 'assignments', label: 'Employment Assignments' },
  { id: 'entitlements', label: 'Employee Entitlements' },
  { id: 'schedule', label: 'Schedule Assignments' },
  { id: 'face', label: 'Face Enrollment' },
  { id: 'wfh', label: 'WFH Location' },
  { id: 'role', label: 'Role' },
  { id: 'skills', label: 'Skills' },
]

const employeeSchema = z.object({
  employee_no: z.string().trim().min(1, 'Employee number is required.').max(30),
  first_name: z.string().trim().min(1, 'First name is required.').max(100),
  middle_name: z.string().trim().max(100),
  last_name: z.string().trim().min(1, 'Last name is required.').max(100),
  suffix: z.string().trim().max(20),
  preferred_name: z.string().trim().max(100),
  birth_date: z.union([z.literal(''), z.iso.date()]),
  gender_code: z.enum(['MALE', 'FEMALE', 'OTHER']),
  personal_email: z.union([z.literal(''), z.email().max(200)]),
  mobile_no: z.string().trim().max(30),
  photo_reference: z.string().trim(),
  record_status: z.enum(['ACTIVE', 'ARCHIVED']),
  is_active: z.boolean(),
})

type EmployeeFormValues = z.infer<typeof employeeSchema>

const emptyEmployee: EmployeeFormValues = {
  employee_no: '',
  first_name: '',
  middle_name: '',
  last_name: '',
  suffix: '',
  preferred_name: '',
  birth_date: '',
  gender_code: 'OTHER',
  personal_email: '',
  mobile_no: '',
  photo_reference: '',
  record_status: 'ACTIVE',
  is_active: true,
}

function nullable(value: string) {
  return value || null
}

function FieldError({ message }: { message?: string }) {
  return message ? <p className="mt-1 text-xs font-medium text-rose-600">{message}</p> : null
}

function EmployeePhoto({ photoReference, employeeName, size = 'h-10 w-10', shape = 'circle' }: {
  photoReference: string | null
  employeeName: string
  size?: string
  shape?: 'circle' | 'square'
}) {
  const [photoUrl, setPhotoUrl] = useState<string | null>(null)
  const shapeClassName = shape === 'square' ? 'rounded-lg' : 'rounded-full'

  useEffect(() => {
    if (!photoReference) {
      setPhotoUrl(null)
      return
    }

    let isCurrent = true
    let objectUrl: string | null = null
    setPhotoUrl(null)
    apiClient.get<Blob>(photoReference, { responseType: 'blob' })
      .then(({ data }) => {
        if (!isCurrent) return
        objectUrl = URL.createObjectURL(data)
        setPhotoUrl(objectUrl)
      })
      .catch(() => {
        if (isCurrent) setPhotoUrl(null)
      })

    return () => {
      isCurrent = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [photoReference])

  return photoUrl
    ? <img src={photoUrl} alt={`${employeeName} employee photo`} className={`${size} shrink-0 ${shapeClassName} object-cover`} />
    : <span aria-hidden="true" className={`${size} flex shrink-0 items-center justify-center ${shapeClassName} bg-indigo-100 text-xs font-bold text-indigo-700`}>{employeeName.trim().charAt(0).toUpperCase() || '?'}</span>
}

export default function Employees({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const tabId = useId()
  const [employees, setEmployees] = useState<Employee[]>([])
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<EmployeeTab>('details')
  const [isLoading, setIsLoading] = useState(true)
  const [loadingEditId, setLoadingEditId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [companies, setCompanies] = useState<Company[]>([])
  const [orgUnits, setOrgUnits] = useState<OrgUnit[]>([])
  const visibleEmployeeTabs = employeeTabs.filter((tab) =>
    (tab.id !== 'entitlements' || localStorage.getItem('role') === 'admin')
    && (tab.id !== 'wfh' || localStorage.getItem('role') === 'admin')
    && (tab.id !== 'role' || (localStorage.getItem('role') === 'admin' && Boolean(editingEmployee)))
    && (tab.id !== 'schedule' || (localStorage.getItem('role') === 'admin' && Boolean(editingEmployee))),
  )

  useEffect(() => {
    let isCurrent = true
    Promise.allSettled([fetchEmployees(), fetchCompanies(), fetchOrgUnits()])
      .then(([employeeResult, companyResult, orgUnitResult]) => {
        if (!isCurrent) return
        if (employeeResult.status === 'fulfilled') setEmployees(employeeResult.value)
        else setErrorMessage(employeeResult.reason instanceof Error ? employeeResult.reason.message : 'Could not load employees.')
        if (companyResult.status === 'fulfilled') setCompanies(companyResult.value)
        if (orgUnitResult.status === 'fulfilled') setOrgUnits(orgUnitResult.value)
      })
      .finally(() => { if (isCurrent) setIsLoading(false) })
    return () => { isCurrent = false }
  }, [])

  useEffect(() => {
    if (!successMessage) return
    const timeout = window.setTimeout(() => setSuccessMessage(''), 5000)
    return () => window.clearTimeout(timeout)
  }, [successMessage])

  const uniqueEmployeeSchema = employeeSchema.superRefine((values, context) => {
    if (employees.some((employee) => employee.employee_no === values.employee_no && employee.id !== editingEmployee?.id)) {
      context.addIssue({ code: 'custom', path: ['employee_no'], message: 'Employee number must be unique.' })
    }
    if (!editingEmployee && !values.personal_email.trim()) {
      context.addIssue({
        code: 'custom',
        path: ['personal_email'],
        message: 'Personal email is required to create the employee account.',
      })
    }
  })

  const defaultValues: EmployeeFormValues = editingEmployee
    ? {
        employee_no: editingEmployee.employee_no,
        first_name: editingEmployee.first_name,
        middle_name: editingEmployee.middle_name ?? '',
        last_name: editingEmployee.last_name,
        suffix: editingEmployee.suffix ?? '',
        preferred_name: editingEmployee.preferred_name ?? '',
        birth_date: editingEmployee.birth_date ?? '',
        gender_code: editingEmployee.gender_code ?? 'OTHER',
        personal_email: editingEmployee.personal_email ?? '',
        mobile_no: editingEmployee.mobile_no ?? '',
        photo_reference: editingEmployee.photo_reference ?? '',
        record_status: editingEmployee.record_status,
        is_active: editingEmployee.is_active,
      }
    : emptyEmployee

  function openCreate() {
    setErrorMessage('')
    setSuccessMessage('')
    setEditingEmployee(null)
    setActiveTab('details')
    setIsFormOpen(true)
  }

  async function openEdit(employee: Employee) {
    setErrorMessage('')
    setSuccessMessage('')
    setLoadingEditId(employee.id)
    try {
      const fullEmployee = await fetchEmployee(employee.id)
      if (!fullEmployee) {
        setErrorMessage('This employee could not be found.')
        return
      }
      setEditingEmployee(fullEmployee)
      setActiveTab('details')
      setIsFormOpen(true)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not load this employee.')
    } finally {
      setLoadingEditId(null)
    }
  }

  function closeForm() {
    setIsFormOpen(false)
    setEditingEmployee(null)
    setActiveTab('details')
    setErrorMessage('')
  }

  async function saveEmployee(values: EmployeeFormValues) {
    setErrorMessage('')
    setSuccessMessage('')
    const payload: EmployeeWritePayload = {
      employee_no: values.employee_no,
      first_name: values.first_name,
      middle_name: nullable(values.middle_name),
      last_name: values.last_name,
      suffix: nullable(values.suffix),
      preferred_name: nullable(values.preferred_name),
      birth_date: nullable(values.birth_date),
      gender_code: values.gender_code,
      personal_email: nullable(values.personal_email),
      mobile_no: nullable(values.mobile_no),
      photo_reference: nullable(values.photo_reference),
      record_status: values.record_status,
      is_active: values.is_active,
    }
    try {
      const isUpdating = Boolean(editingEmployee)
      const savedEmployee = editingEmployee
        ? await updateEmployee(editingEmployee.id, payload)
        : await createEmployee(payload)
      if (!isUpdating) window.dispatchEvent(new Event(EMPLOYEE_CREATED_EVENT))
      setEmployees((current) => isUpdating
        ? current.map((employee) => employee.id === savedEmployee.id ? savedEmployee : employee)
        : [savedEmployee, ...current])
      closeForm()
      setSuccessMessage(`Employee ${savedEmployee.employee_no} ${isUpdating ? 'updated' : 'created'} successfully.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not save the employee.')
    }
  }

  const columns: DataTableColumn<Employee>[] = [
    {
      key: 'employee',
      header: 'Employee',
      value: (employee) => `${employee.employee_no} ${employee.first_name} ${employee.middle_name ?? ''} ${employee.last_name} ${employee.preferred_name ?? ''}`,
      render: (employee) => (
        <div className="flex items-center gap-3">
          <EmployeePhoto
            photoReference={employee.photo_reference}
            employeeName={`${employee.first_name} ${employee.last_name}`}
            shape="square"
          />
          <div>
            <p className="font-bold text-slate-900">{employee.employee_no}</p>
            <p className="text-xs text-slate-500">{employee.first_name} {employee.last_name}</p>
          </div>
        </div>
      ),
    },
    { key: 'email', header: 'Email', value: (employee) => employee.personal_email ?? '', render: (employee) => employee.personal_email || '—' },
    { key: 'mobile', header: 'Mobile', value: (employee) => employee.mobile_no ?? '', render: (employee) => employee.mobile_no || '—' },
    {
      key: 'status',
      header: 'Status',
      value: (employee) => employee.record_status,
      render: (employee) => (
        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${
          employee.record_status === 'ACTIVE' && employee.is_active
            ? 'bg-emerald-50 text-emerald-700'
            : 'bg-slate-100 text-slate-600'
        }`}>
          {employee.record_status === 'ARCHIVED' ? 'Archived' : employee.is_active ? 'Active' : 'Disabled'}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      value: () => '',
      sortable: false,
      searchable: false,
      render: (employee) => (
        <button type="button" onClick={() => openEdit(employee)} disabled={loadingEditId === employee.id} aria-label={`Edit ${employee.employee_no}`} className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-50">
          <Pencil className="h-4 w-4" />
        </button>
      ),
    },
  ]

  const inputClassName = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
  const labelClassName = 'text-xs font-semibold text-slate-700'

  return (
    <div className="min-h-svh bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="employees" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] py-6">
        <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-bold uppercase text-indigo-600">Maintenance</p>
            <h1 className="mt-1 text-2xl font-extrabold text-slate-900">Employees</h1>
            <p className="mt-1 text-sm text-slate-500">Maintain employee identity, contact details, and record status.</p>
          </div>
          <button type="button" onClick={openCreate} disabled={isLoading} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">
            <Plus className="h-4 w-4" />
            New employee
          </button>
        </div>

        {errorMessage && !isFormOpen && <p role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
        {successMessage && <p role="status" className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{successMessage}</p>}

        <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="border-l-4 border-indigo-500 bg-white p-4"><p className="text-xs font-bold uppercase text-slate-400">Total</p><p className="mt-1 text-2xl font-bold text-slate-900">{employees.length}</p></div>
          <div className="border-l-4 border-emerald-500 bg-white p-4"><p className="text-xs font-bold uppercase text-slate-400">Active</p><p className="mt-1 text-2xl font-bold text-slate-900">{employees.filter((employee) => employee.record_status === 'ACTIVE' && employee.is_active).length}</p></div>
          <div className="border-l-4 border-slate-500 bg-white p-4"><p className="text-xs font-bold uppercase text-slate-400">Archived</p><p className="mt-1 text-2xl font-bold text-slate-900">{employees.filter((employee) => employee.record_status === 'ARCHIVED').length}</p></div>
          <div className="hidden border-l-4 border-slate-400 bg-white p-4 lg:block"><Users className="h-6 w-6 text-slate-400" /><p className="mt-2 text-xs text-slate-500">Employee registry</p></div>
        </div>

        <DataTable
          rows={employees}
          columns={columns}
          getRowKey={(employee) => employee.id}
          searchPlaceholder="Search number, name, email, or mobile"
          emptyMessage={isLoading ? 'Loading employees…' : 'No employees match your search.'}
        />
      </main>

      <FormModal<EmployeeFormValues>
        isOpen={isFormOpen}
        title={editingEmployee ? (
          <span className="flex items-center gap-3">
            <EmployeePhoto
              photoReference={editingEmployee.photo_reference}
              employeeName={`${editingEmployee.first_name} ${editingEmployee.last_name}`}
              size="h-12 w-12"
              shape="square"
            />
            <span className="min-w-0">
              <span className="block truncate text-base font-bold text-slate-900">{editingEmployee.first_name} {editingEmployee.last_name}</span>
              <span className="mt-0.5 block text-xs font-medium text-slate-500">{editingEmployee.employee_no}</span>
            </span>
          </span>
        ) : 'Create employee'}
        description="Maintain the employee record."
        defaultValues={defaultValues}
        resetKey={editingEmployee?.id ?? 'new'}
        resolver={zodResolver(uniqueEmployeeSchema)}
        submitLabel={editingEmployee ? 'Save changes' : 'Create employee'}
        showSubmit={activeTab === 'details'}
        onClose={closeForm}
        onSubmit={saveEmployee}
      >
        {({ register, setValue, formState: { errors } }) => (
          <div className="space-y-4">
            {errorMessage && <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
            <div role="tablist" aria-label="Employee information" className="flex flex-wrap border-b-2 border-indigo-200 pb-1">
                          {visibleEmployeeTabs.map((tab, tabIndex) => (
                <button
                  key={tab.id}
                              style={{
                                clipPath:
                                  tabIndex === 0
                                    ? 'polygon(0 0, calc(100% - 14px) 0, 100% 50%, calc(100% - 14px) 100%, 0 100%)'
                                    : 'polygon(0 0, calc(100% - 14px) 0, 100% 50%, calc(100% - 14px) 100%, 0 100%, 14px 50%)',
                                marginLeft: 0,
                              }}
                  type="button"
                  role="tab"
                  id={`${tabId}-${tab.id}-tab`}
                  aria-controls={`${tabId}-${tab.id}-panel`}
                  aria-selected={activeTab === tab.id}
                  tabIndex={activeTab === tab.id ? 0 : -1}
                  onClick={() => setActiveTab(tab.id)}
                  onKeyDown={(event) => {
                    const index = visibleEmployeeTabs.findIndex((item) => item.id === tab.id)
                    const nextIndex = event.key === 'ArrowRight'
                      ? (index + 1) % visibleEmployeeTabs.length
                      : event.key === 'ArrowLeft'
                        ? (index - 1 + visibleEmployeeTabs.length) % visibleEmployeeTabs.length
                        : event.key === 'Home' ? 0 : event.key === 'End' ? visibleEmployeeTabs.length - 1 : -1
                    if (nextIndex === -1) return
                    event.preventDefault()
                    const nextTab = visibleEmployeeTabs[nextIndex].id
                    setActiveTab(nextTab)
                    document.getElementById(`${tabId}-${nextTab}-tab`)?.focus()
                  }}
                  className={`min-w-[7rem] flex-1 whitespace-nowrap py-2 pl-7 pr-8 text-xs font-semibold transition first:pl-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                    activeTab === tab.id
                                        ? 'bg-indigo-600 text-white'
                                        : 'bg-slate-100 text-slate-600 hover:bg-indigo-100 hover:text-indigo-700'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="grid">
            <div role="tabpanel" id={`${tabId}-details-panel`} aria-labelledby={`${tabId}-details-tab`} tabIndex={activeTab === 'details' ? 0 : -1} className={`space-y-4 [grid-area:1/1] ${activeTab === 'details' ? '' : 'invisible'}`}>
              <input type="hidden" {...register('photo_reference')} />
              <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Identity</h3>
              <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                <label className={labelClassName}>Employee number<input {...register('employee_no')} className={inputClassName} /><FieldError message={errors.employee_no?.message} /></label>
                <label className={labelClassName}>First name<input {...register('first_name')} className={inputClassName} /><FieldError message={errors.first_name?.message} /></label>
                <label className={labelClassName}>Middle name<input {...register('middle_name')} className={inputClassName} /><FieldError message={errors.middle_name?.message} /></label>
                <label className={labelClassName}>Last name<input {...register('last_name')} className={inputClassName} /><FieldError message={errors.last_name?.message} /></label>
                <label className={labelClassName}>Suffix<input {...register('suffix')} className={inputClassName} /><FieldError message={errors.suffix?.message} /></label>
                <label className={labelClassName}>Preferred name<input {...register('preferred_name')} className={inputClassName} /><FieldError message={errors.preferred_name?.message} /></label>
                <label className={labelClassName}>Birth date<input type="date" {...register('birth_date')} className={inputClassName} /><FieldError message={errors.birth_date?.message} /></label>
                <label className={labelClassName}>Gender code<select {...register('gender_code')} className={inputClassName}><option value="MALE">Male</option><option value="FEMALE">Female</option><option value="OTHER">Other</option></select><FieldError message={errors.gender_code?.message} /></label>
              </div>
              </section>
              <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Contact &amp; record</h3>
              <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                <label className={labelClassName}>Personal email<input type="email" {...register('personal_email')} className={inputClassName} /><FieldError message={errors.personal_email?.message} /></label>
                <label className={labelClassName}>Mobile number<input type="tel" {...register('mobile_no')} className={inputClassName} /><FieldError message={errors.mobile_no?.message} /></label>
                <label className={labelClassName}>Record status<select {...register('record_status')} className={inputClassName}><option value="ACTIVE">Active</option><option value="ARCHIVED">Archived</option></select><FieldError message={errors.record_status?.message} /></label>
                <label className="flex items-center gap-3 self-end rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700"><input type="checkbox" {...register('is_active')} className="h-4 w-4 accent-indigo-600" />Enabled for use</label>
              </div>
              </section>
            </div>
            {visibleEmployeeTabs.slice(1).map((tab) => (
              <div key={tab.id} role="tabpanel" id={`${tabId}-${tab.id}-panel`} aria-labelledby={`${tabId}-${tab.id}-tab`} tabIndex={activeTab === tab.id ? 0 : -1} className={`[grid-area:1/1] ${activeTab === tab.id ? '' : 'invisible'}`}>
                {tab.id === 'assignments'
                  ? <EmploymentAssignmentsPanel employee={editingEmployee} employees={employees} companies={companies} orgUnits={orgUnits} />
                  : tab.id === 'skills'
                    ? <EmployeeSkillsPanel employee={editingEmployee} employees={employees} />
                    : tab.id === 'entitlements'
                      ? <EmployeeEntitlementsPanel employee={editingEmployee} />
                      : tab.id === 'schedule'
                        ? <EmployeeScheduleAssignmentsPanel employee={editingEmployee} />
                        : tab.id === 'wfh'
                          ? <EmployeeWfhPanel key={editingEmployee?.id} employee={editingEmployee} />
                          : tab.id === 'role'
                            ? <EmployeeRolePanel key={editingEmployee?.id} employee={editingEmployee} companies={companies} orgUnits={orgUnits} />
                            : <EmployeeFaceEnrollmentPanel
                      employee={editingEmployee}
                      isActive={activeTab === 'face'}
                      onPhotoReferenceSaved={(photoReference) => {
                        if (!editingEmployee) return
                        setValue('photo_reference', photoReference)
                        setEditingEmployee((current) => current
                          ? { ...current, photo_reference: photoReference }
                          : current)
                        setEmployees((current) => current.map((employee) => employee.id === editingEmployee.id
                          ? { ...employee, photo_reference: photoReference }
                          : employee))
                      }}
                    />}
              </div>
            ))}
            </div>
          </div>
        )}
      </FormModal>
    </div>
  )
}
