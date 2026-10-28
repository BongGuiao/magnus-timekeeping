import { useEffect, useId, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { BadgeCheck, BriefcaseBusiness, CalendarDays, ContactRound, Download, FileUp, MapPin, Pencil, Plus, ScanFace, Shield, Sparkles, Users } from 'lucide-react'
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
import { EMPLOYEE_CSV_HEADERS, parseEmployeeCsv } from '../lib/employeeCsv'
import {
  EMPLOYMENT_ASSIGNMENT_CSV_HEADERS,
  parseEmploymentAssignmentCsv,
} from '../lib/employmentAssignmentCsv'
import {
  createEmploymentAssignmentsBatch,
  EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT,
} from '../lib/employeeRelatedApi'
import type { EmploymentAssignmentWritePayload } from '../types/employeeRelated'
import { OPERATIONAL_GROUPS } from '../types/employeeRelated'
import { fetchLocations } from '../lib/locationApi'
import type { Location } from '../types/location'
import { fetchPayrollGroups } from '../lib/payrollGroupApi'
import type { PayrollGroup } from '../lib/payrollGroupApi'
import { EmployeeSkillsPanel, EmploymentAssignmentsPanel } from '../features/employees/EmployeeRelatedPanels'
import EmployeeEntitlementsPanel from '../features/employees/EmployeeEntitlementsPanel'
import EmployeeScheduleAssignmentsPanel from '../features/employees/EmployeeScheduleAssignmentsPanel'
import EmployeeFaceEnrollmentPanel from '../features/employees/EmployeeFaceEnrollmentPanel'
import EmployeeWfhPanel from '../features/employees/EmployeeWfhPanel'
import EmployeeRolePanel from '../features/employees/EmployeeRolePanel'
import { hasPermission } from '../types/role'
import type { Company } from '../types/company'
import type { Employee } from '../types/employee'
import type { OrgUnit } from '../types/orgUnit'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

type EmployeeTab = 'details' | 'assignments' | 'entitlements' | 'skills' | 'schedule' | 'face' | 'wfh' | 'role'

const employeeTabs = [
  { id: 'details', label: 'Details', icon: ContactRound },
  { id: 'assignments', label: 'Assignments', icon: BriefcaseBusiness },
  { id: 'entitlements', label: 'Entitlements', icon: BadgeCheck },
  { id: 'schedule', label: 'Schedule', icon: CalendarDays },
  { id: 'face', label: 'Face Enrollment', icon: ScanFace },
  { id: 'wfh', label: 'WFH Location', icon: MapPin },
  { id: 'role', label: 'Role', icon: Shield },
  { id: 'skills', label: 'Skills', icon: Sparkles },
] satisfies { id: EmployeeTab; label: string; icon: typeof ContactRound }[]

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

interface EmployeeCsvPreviewRow {
  rowNumber: number
  payload: EmployeeWritePayload
  errors: string[]
}

interface EmployeeCsvResult {
  rowNumber: number
  employeeNo: string
  status: 'created' | 'skipped' | 'failed'
  message: string
}

interface EmploymentAssignmentCsvPreviewRow {
  rowNumber: number
  employeeNo: string
  companyCode: string
  payload: EmploymentAssignmentWritePayload | null
  errors: string[]
}

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
  const [isCsvImportOpen, setIsCsvImportOpen] = useState(false)
  const [csvFileName, setCsvFileName] = useState('')
  const [csvPreviewRows, setCsvPreviewRows] = useState<EmployeeCsvPreviewRow[]>([])
  const [csvResults, setCsvResults] = useState<EmployeeCsvResult[]>([])
  const [csvError, setCsvError] = useState('')
  const [isImportingCsv, setIsImportingCsv] = useState(false)
  const [isAssignmentCsvImportOpen, setIsAssignmentCsvImportOpen] = useState(false)
  const [assignmentCsvFileName, setAssignmentCsvFileName] = useState('')
  const [assignmentCsvPreviewRows, setAssignmentCsvPreviewRows] = useState<EmploymentAssignmentCsvPreviewRow[]>([])
  const [assignmentCsvError, setAssignmentCsvError] = useState('')
  const [assignmentCsvMessage, setAssignmentCsvMessage] = useState('')
  const [isImportingAssignmentCsv, setIsImportingAssignmentCsv] = useState(false)
  const [assignmentLookups, setAssignmentLookups] = useState<{
    locations: Location[]
    payrollGroups: PayrollGroup[]
    loaded: boolean
    error: string
  }>({ locations: [], payrollGroups: [], loaded: false, error: '' })
  const [companies, setCompanies] = useState<Company[]>([])
  const [orgUnits, setOrgUnits] = useState<OrgUnit[]>([])
  const canManageEmployees = hasPermission('employees.manage')
  const canManageRoles = hasPermission('system.manage')
  const canManagePayroll = hasPermission('payroll.manage')
  const visibleEmployeeTabs = employeeTabs.filter((tab) =>
    (tab.id !== 'entitlements' || localStorage.getItem('role') === 'admin')
    && (tab.id !== 'wfh' || localStorage.getItem('role') === 'admin')
    && (tab.id !== 'role' || (canManageRoles && Boolean(editingEmployee)))
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
    if (!canManageEmployees) return
    let isCurrent = true
    Promise.all([
      fetchLocations(),
      canManagePayroll ? fetchPayrollGroups() : Promise.resolve<PayrollGroup[]>([]),
    ])
      .then(([locations, payrollGroups]) => {
        if (isCurrent) setAssignmentLookups({ locations, payrollGroups, loaded: true, error: '' })
      })
      .catch((error: unknown) => {
        if (isCurrent) setAssignmentLookups({
          locations: [],
          payrollGroups: [],
          loaded: true,
          error: error instanceof Error ? error.message : 'Could not load assignment lookup data.',
        })
      })
    return () => { isCurrent = false }
  }, [canManageEmployees, canManagePayroll])

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

  function downloadEmployeeCsvTemplate() {
    const example = [
      'EMP-0002',
      'Alex',
      '',
      'Santos',
      '',
      '',
      '1990-01-31',
      'OTHER',
      'alex.santos@example.com',
      '09171234567',
      'ACTIVE',
      'true',
    ]
    const contents = [EMPLOYEE_CSV_HEADERS.join(','), example.join(',')].join('\r\n')
    const url = URL.createObjectURL(new Blob([contents], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'employee-import-template.csv'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  async function selectEmployeeCsv(file: File | undefined) {
    setCsvError('')
    setCsvResults([])
    setCsvPreviewRows([])
    setCsvFileName(file?.name ?? '')
    if (!file) return
    if (file.size > 5 * 1024 * 1024) {
      setCsvError('The CSV file must be 5 MB or smaller.')
      return
    }

    try {
      const parsedRows = parseEmployeeCsv(await file.text())
      if (parsedRows.length > 500) {
        setCsvError('The CSV can contain no more than 500 employee rows per import.')
        return
      }

      const knownEmployeeNumbers = new Set(employees.map((employee) => employee.employee_no.trim().toLowerCase()))
      const knownEmails = new Set(employees.map((employee) => employee.personal_email?.trim().toLowerCase()).filter(Boolean))
      const seenEmployeeNumbers = new Set<string>()
      const seenEmails = new Set<string>()
      const previewRows = parsedRows.map(({ rowNumber, payload }) => {
        const errors: string[] = []
        const formValues: EmployeeFormValues = {
          employee_no: payload.employee_no,
          first_name: payload.first_name,
          middle_name: payload.middle_name ?? '',
          last_name: payload.last_name,
          suffix: payload.suffix ?? '',
          preferred_name: payload.preferred_name ?? '',
          birth_date: payload.birth_date ?? '',
          gender_code: payload.gender_code ?? 'OTHER',
          personal_email: payload.personal_email ?? '',
          mobile_no: payload.mobile_no ?? '',
          photo_reference: payload.photo_reference ?? '',
          record_status: payload.record_status,
          is_active: payload.is_active,
        }
        const validation = employeeSchema.safeParse(formValues)
        if (!validation.success) {
          errors.push(...validation.error.issues.map((issue) => issue.message))
        }
        if (!formValues.personal_email.trim()) {
          errors.push('Personal email is required to create the employee account.')
        }

        const employeeNumber = payload.employee_no.trim().toLowerCase()
        if (knownEmployeeNumbers.has(employeeNumber)) {
          errors.push('Employee number already exists; existing employees are not updated by CSV import.')
        } else if (seenEmployeeNumbers.has(employeeNumber)) {
          errors.push('Employee number is duplicated in this CSV file.')
        }
        seenEmployeeNumbers.add(employeeNumber)

        const email = (payload.personal_email ?? '').trim().toLowerCase()
        if (email && knownEmails.has(email)) {
          errors.push('Personal email is already assigned to an employee.')
        } else if (email && seenEmails.has(email)) {
          errors.push('Personal email is duplicated in this CSV file.')
        }
        if (email) seenEmails.add(email)

        return { rowNumber, payload, errors: [...new Set(errors)] }
      })

      setCsvPreviewRows(previewRows)
    } catch (error) {
      setCsvError(error instanceof Error ? error.message : 'Could not read the CSV file.')
    }
  }

  async function importEmployeeCsv() {
    if (isImportingCsv) return
    const readyRows = csvPreviewRows.filter((row) => row.errors.length === 0)
    if (readyRows.length === 0) return

    setIsImportingCsv(true)
    setCsvError('')
    setSuccessMessage('')
    const results: EmployeeCsvResult[] = csvPreviewRows
      .filter((row) => row.errors.length > 0)
      .map((row) => ({
        rowNumber: row.rowNumber,
        employeeNo: row.payload.employee_no || '(blank)',
        status: 'skipped',
        message: row.errors.join(' '),
      }))
    setCsvResults(results)

    for (const row of readyRows) {
      try {
        const employee = await createEmployee(row.payload)
        results.push({
          rowNumber: row.rowNumber,
          employeeNo: employee.employee_no,
          status: 'created',
          message: 'Employee profile and initial employee account created.',
        })
        setEmployees((current) => [employee, ...current])
        window.dispatchEvent(new Event(EMPLOYEE_CREATED_EVENT))
      } catch (error) {
        results.push({
          rowNumber: row.rowNumber,
          employeeNo: row.payload.employee_no || '(blank)',
          status: 'failed',
          message: error instanceof Error ? error.message : 'Could not create this employee.',
        })
      }
      setCsvResults([...results].sort((left, right) => left.rowNumber - right.rowNumber))
    }

    const createdCount = results.filter((result) => result.status === 'created').length
    setSuccessMessage(`${createdCount} employee${createdCount === 1 ? '' : 's'} imported. Review the row results for skipped or failed records.`)
    setIsImportingCsv(false)
  }

  function downloadEmploymentAssignmentCsvTemplate() {
    const example = [
      'EMP-0002',
      'COMPANY-CODE',
      '',
      '',
      'REGULAR',
      'RANK_AND_FILE',
      '',
      '',
      '',
      '',
      '2026-01-01',
      '2026-01-01',
      '',
      '',
      'ACTIVE',
      'true',
    ]
    const contents = [EMPLOYMENT_ASSIGNMENT_CSV_HEADERS.join(','), example.join(',')].join('\r\n')
    const url = URL.createObjectURL(new Blob([contents], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'employment-assignment-import-template.csv'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  async function selectEmploymentAssignmentCsv(file: File | undefined) {
    setAssignmentCsvError('')
    setAssignmentCsvMessage('')
    setAssignmentCsvPreviewRows([])
    setAssignmentCsvFileName(file?.name ?? '')
    if (!file) return
    if (file.size > 5 * 1024 * 1024) {
      setAssignmentCsvError('The CSV file must be 5 MB or smaller.')
      return
    }
    if (!assignmentLookups.loaded) {
      setAssignmentCsvError('Assignment lookup data is still loading. Please try again shortly.')
      return
    }
    if (assignmentLookups.error) {
      setAssignmentCsvError(`Cannot validate the assignment file: ${assignmentLookups.error}`)
      return
    }

    try {
      const parsedRows = parseEmploymentAssignmentCsv(await file.text())
      const seenPairs = new Set<string>()
      const previewRows = parsedRows.map(({ rowNumber, values }) => {
        const errors: string[] = []
        const employeeNo = values.employee_no.trim()
        const companyCode = values.company_code.trim()
        const employee = employees.find((item) => item.employee_no.trim().toLocaleLowerCase() === employeeNo.toLocaleLowerCase())
        const company = companies.find((item) => item.company_code.trim().toLocaleLowerCase() === companyCode.toLocaleLowerCase())
        if (!employee) errors.push(`Employee number "${employeeNo || '(blank)'}" was not found.`)
        if (!company) errors.push(`Company code "${companyCode || '(blank)'}" was not found.`)

        let orgUnitId: string | null = null
        const orgUnitCode = values.org_unit_code.trim()
        if (orgUnitCode) {
          const orgUnit = orgUnits.find((item) =>
            item.company_id === company?.id
            && item.org_unit_code.trim().toLocaleLowerCase() === orgUnitCode.toLocaleLowerCase(),
          )
          if (!orgUnit) errors.push(`Org unit code "${orgUnitCode}" was not found for this company.`)
          else orgUnitId = orgUnit.id
        }

        let supervisorEmployeeId: string | null = null
        const supervisorNo = values.supervisor_employee_no.trim()
        if (supervisorNo) {
          const supervisor = employees.find((item) => item.employee_no.trim().toLocaleLowerCase() === supervisorNo.toLocaleLowerCase())
          if (!supervisor) errors.push(`Supervisor employee number "${supervisorNo}" was not found.`)
          else if (supervisor.id === employee?.id) errors.push('An employee cannot be their own supervisor.')
          else supervisorEmployeeId = supervisor.id
        }

        let payrollGroupId: string | null = null
        const payrollGroupCode = values.payroll_group_code.trim()
        if (payrollGroupCode && !canManagePayroll) {
          errors.push('Payroll group can only be set by HR payroll personnel. Leave payroll_group_code blank.')
        } else if (payrollGroupCode) {
          const payrollGroup = assignmentLookups.payrollGroups.find((item) =>
            item.company_id === company?.id
            && item.payroll_group_code.trim().toLocaleLowerCase() === payrollGroupCode.toLocaleLowerCase(),
          )
          if (!payrollGroup) errors.push(`Payroll group code "${payrollGroupCode}" was not found for this company.`)
          else payrollGroupId = payrollGroup.id
        }

        const locationIds: string[] = []
        const locationCodes = (values.location_codes ?? '').split(';').map((code) => code.trim()).filter(Boolean)
        for (const locationCode of locationCodes) {
          const location = assignmentLookups.locations.find((item) =>
            item.company_id === company?.id
            && item.location_code.trim().toLocaleLowerCase() === locationCode.toLocaleLowerCase(),
          )
          if (!location) errors.push(`Location code "${locationCode}" was not found for this company.`)
          else if (!locationIds.includes(location.id)) locationIds.push(location.id)
        }
        let primaryLocationId = locationIds[0] ?? null
        const primaryLocationCode = values.primary_location_code?.trim() ?? ''
        if (primaryLocationCode) {
          const primaryLocation = assignmentLookups.locations.find((item) =>
            item.company_id === company?.id
            && item.location_code.trim().toLocaleLowerCase() === primaryLocationCode.toLocaleLowerCase(),
          )
          if (!primaryLocation) {
            errors.push(`Primary location code "${primaryLocationCode}" was not found for this company.`)
          } else if (!locationIds.includes(primaryLocation.id)) {
            errors.push('The primary location code must also be included in location_codes.')
          } else {
            primaryLocationId = primaryLocation.id
          }
        }

        const employmentType = values.employment_type.trim()
        const employeeCategory = values.employee_category.trim()
        if (!employmentType) errors.push('Employment type is required.')
        if (employmentType.length > 30) errors.push('Employment type must be 30 characters or fewer.')
        if (!employeeCategory) errors.push('Employee category is required.')
        if (employeeCategory.length > 30) errors.push('Employee category must be 30 characters or fewer.')

        const operationalGroupInput = values.operational_group.trim().toUpperCase()
        const operationalGroup = OPERATIONAL_GROUPS.find((group) => group === operationalGroupInput) ?? null
        if (operationalGroupInput && !operationalGroup) {
          errors.push(`Operational group must be one of: ${OPERATIONAL_GROUPS.join(', ')}.`)
        }
        const status = (values.status.trim() || 'ACTIVE').toUpperCase()
        if (status !== 'ACTIVE' && status !== 'INACTIVE') errors.push('Status must be ACTIVE or INACTIVE.')
        const activeInput = values.is_active.trim().toLocaleLowerCase()
        let isActive: boolean | null = true
        if (activeInput && ['true', 'yes', '1', 'active', 'enabled'].includes(activeInput)) isActive = true
        else if (activeInput && ['false', 'no', '0', 'inactive', 'disabled'].includes(activeInput)) isActive = false
        else if (activeInput) isActive = null
        if (isActive === null) errors.push('is_active must be true/false, yes/no, or 1/0.')

        const hireDate = values.hire_date.trim()
        const effectiveFrom = values.effective_from.trim()
        const effectiveTo = values.effective_to.trim() || null
        const separationDate = values.separation_date.trim() || null
        for (const [label, dateValue, required] of [
          ['hire_date', hireDate, true],
          ['effective_from', effectiveFrom, true],
          ['effective_to', effectiveTo ?? '', false],
          ['separation_date', separationDate ?? '', false],
        ] as const) {
          if (required && !dateValue) errors.push(`${label} is required.`)
          else if (dateValue && !z.iso.date().safeParse(dateValue).success) errors.push(`${label} must be a valid date in YYYY-MM-DD format.`)
        }
        if (effectiveTo && effectiveFrom && effectiveTo < effectiveFrom) errors.push('effective_to must be on or after effective_from.')
        if (separationDate && hireDate && separationDate < hireDate) errors.push('separation_date must be on or after hire_date.')

        if (employee && company) {
          const pair = `${employee.id}:${company.id}`
          if (seenPairs.has(pair)) errors.push('The employee and company combination is duplicated in this file.')
          seenPairs.add(pair)
        }

        const payload = employee && company && isActive !== null
          ? {
              employee_id: employee.id,
              company_id: company.id,
              org_unit_id: orgUnitId,
              position_id: null,
              supervisor_employee_id: supervisorEmployeeId,
              employment_type: employmentType,
              employee_category: employeeCategory,
              operational_group: operationalGroup,
              payroll_group_id: payrollGroupId,
              primary_location_id: primaryLocationId,
              location_ids: locationIds,
              authorized_geofence_ids: [],
              hire_date: hireDate,
              effective_from: effectiveFrom,
              effective_to: effectiveTo,
              separation_date: separationDate,
              status,
              is_active: isActive,
            } satisfies EmploymentAssignmentWritePayload
          : null
        return { rowNumber, employeeNo, companyCode, payload, errors: [...new Set(errors)] }
      })
      setAssignmentCsvPreviewRows(previewRows)
    } catch (error) {
      setAssignmentCsvError(error instanceof Error ? error.message : 'Could not read the assignment CSV file.')
    }
  }

  async function importEmploymentAssignmentCsv() {
    if (isImportingAssignmentCsv || assignmentCsvPreviewRows.length === 0) return
    const invalidRows = assignmentCsvPreviewRows.filter((row) => row.errors.length > 0 || row.payload === null)
    if (invalidRows.length > 0) {
      setAssignmentCsvError('The entire file was rejected. Fix every highlighted row before importing.')
      return
    }

    setIsImportingAssignmentCsv(true)
    setAssignmentCsvError('')
    setAssignmentCsvMessage('')
    try {
      const batchRows = assignmentCsvPreviewRows.map((row) => {
        if (!row.payload) throw new Error(`CSV row ${row.rowNumber} has no valid assignment payload.`)
        return { row_number: row.rowNumber, assignment: row.payload }
      })
      const created = await createEmploymentAssignmentsBatch(batchRows)
      window.dispatchEvent(new Event(EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT))
      setAssignmentCsvMessage(`${created.length} employment assignment${created.length === 1 ? '' : 's'} imported successfully.`)
    } catch (error) {
      setAssignmentCsvError(error instanceof Error
        ? `The entire file was rejected. ${error.message}`
        : 'The entire file was rejected. Could not import employment assignments.')
    } finally {
      setIsImportingAssignmentCsv(false)
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
      render: (employee) => canManageEmployees ? (
        <button type="button" onClick={() => openEdit(employee)} disabled={loadingEditId === employee.id} aria-label={`Edit ${employee.employee_no}`} className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-50">
          <Pencil className="h-4 w-4" />
        </button>
      ) : null,
    },
  ]

  const inputClassName = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
  const labelClassName = 'text-xs font-semibold text-slate-700'

  return (
    <div className="min-h-svh bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="employees" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-bold uppercase text-indigo-600">Maintenance</p>
            <h1 className="mt-1 text-2xl font-extrabold text-slate-900">Employees</h1>
            <p className="mt-1 text-sm text-slate-500">
              {canManageEmployees || hasPermission('employees.read')
                ? 'Maintain employee identity, contact details, and record status.'
                : 'Employees currently assigned to you as their supervisor.'}
            </p>
          </div>
          {canManageEmployees && <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                setIsAssignmentCsvImportOpen((current) => !current)
                setAssignmentCsvError('')
              }}
              disabled={isLoading || isImportingCsv || isImportingAssignmentCsv}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-emerald-200 bg-white px-4 py-2.5 text-sm font-semibold text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
              aria-expanded={isAssignmentCsvImportOpen}
            >
              <FileUp className="h-4 w-4" />
              Import Assignments
            </button>
            <button
              type="button"
              onClick={() => {
                setIsCsvImportOpen((current) => !current)
                setCsvError('')
              }}
              disabled={isLoading || isImportingCsv || isImportingAssignmentCsv}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-indigo-200 bg-white px-4 py-2.5 text-sm font-semibold text-indigo-700 hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50"
              aria-expanded={isCsvImportOpen}
            >
              <FileUp className="h-4 w-4" />
              Import CSV
            </button>
            <button type="button" onClick={openCreate} disabled={isLoading || isImportingCsv || isImportingAssignmentCsv} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">
              <Plus className="h-4 w-4" />
              New employee
            </button>
          </div>}
        </div>

        {errorMessage && !isFormOpen && <p role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
        {successMessage && <p role="status" className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{successMessage}</p>}

        {isCsvImportOpen && (
          <section aria-label="Import employees from CSV" className="mb-5 space-y-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
              <div>
                <h2 className="text-sm font-bold text-slate-900">Import employee profiles</h2>
                <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-600">
                  Import creates new profiles only. Existing or duplicate employee numbers are skipped; each successful row uses the normal employee creation flow and receives an initial Employee role. Employment assignments are managed separately.
                </p>
              </div>
              <button type="button" onClick={downloadEmployeeCsvTemplate} className="inline-flex shrink-0 items-center justify-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                <Download className="h-4 w-4" />
                Download template
              </button>
            </div>
            <label className="block text-xs font-semibold text-slate-700">
              Employee CSV file
              <input
                type="file"
                accept=".csv,text/csv"
                disabled={isImportingCsv}
                onChange={(event) => void selectEmployeeCsv(event.target.files?.[0])}
                className="mt-1.5 block w-full rounded-md border border-slate-300 px-3 py-2 text-xs text-slate-700 file:mr-3 file:rounded file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-indigo-700 disabled:opacity-50"
              />
            </label>
            <p className="text-[11px] leading-5 text-slate-500">
              Required columns: employee_no, first_name, last_name, personal_email. Optional columns: middle_name, suffix, preferred_name, birth_date (YYYY-MM-DD), gender_code (MALE/FEMALE/OTHER), mobile_no, record_status (ACTIVE/ARCHIVED), is_active (true/false). Maximum file size 5 MB and 500 employee rows.
            </p>
            {csvFileName && <p className="text-xs font-medium text-slate-600">Selected: {csvFileName}</p>}
            {csvError && <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{csvError}</p>}
            {csvPreviewRows.length > 0 && (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs text-slate-600">
                    {csvPreviewRows.filter((row) => row.errors.length === 0).length} ready · {csvPreviewRows.filter((row) => row.errors.length > 0).length} skipped for validation or duplicates
                  </p>
                  <button
                    type="button"
                    onClick={() => void importEmployeeCsv()}
                    disabled={isImportingCsv || !csvPreviewRows.some((row) => row.errors.length === 0)}
                    className="inline-flex items-center justify-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <FileUp className="h-4 w-4" />
                    {isImportingCsv ? 'Importing…' : 'Import valid rows'}
                  </button>
                </div>
                <div className="max-h-72 overflow-auto rounded-md border border-slate-200">
                  <table className="min-w-full text-left text-xs">
                    <thead className="sticky top-0 bg-slate-50 text-[11px] uppercase text-slate-500">
                      <tr>
                        <th className="px-3 py-2">CSV row</th>
                        <th className="px-3 py-2">Employee number</th>
                        <th className="px-3 py-2">Result / validation</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {csvPreviewRows.map((row) => {
                        const result = csvResults.find((item) => item.rowNumber === row.rowNumber)
                        const status = result?.status
                        const message = result?.message ?? row.errors.join(' ')
                        return (
                          <tr key={row.rowNumber}>
                            <td className="whitespace-nowrap px-3 py-2 text-slate-600">{row.rowNumber}</td>
                            <td className="whitespace-nowrap px-3 py-2 font-medium text-slate-800">{row.payload.employee_no || '(blank)'}</td>
                            <td className={`px-3 py-2 ${
                              status === 'created' ? 'text-emerald-700'
                                : status === 'failed' || row.errors.length > 0 ? 'text-rose-700'
                                  : 'text-slate-600'
                            }`}>
                              {status ? `${status === 'created' ? 'Created' : status === 'failed' ? 'Failed' : 'Skipped'}: ${message}` : row.errors.length > 0 ? `Will skip: ${message}` : 'Ready to import'}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="text-[11px] text-slate-500">
                  Rows are created one at a time. If a row fails, other valid rows continue; check each row result before closing this panel.
                </p>
              </>
            )}
          </section>
        )}

        {isAssignmentCsvImportOpen && (
          <section aria-label="Import employment assignments from CSV" className="mb-5 space-y-4 rounded-lg border border-emerald-200 bg-white p-4 shadow-sm">
            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
              <div>
                <h2 className="text-sm font-bold text-slate-900">Import employment assignments</h2>
                <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-600">
                  Imports assignments for existing employees. The whole file is rejected if a row is invalid, duplicates another row, or matches an existing employee/company assignment. No rows are imported unless every row passes validation.
                </p>
              </div>
              <button type="button" onClick={downloadEmploymentAssignmentCsvTemplate} className="inline-flex shrink-0 items-center justify-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                <Download className="h-4 w-4" />
                Download template
              </button>
            </div>
            <label className="block text-xs font-semibold text-slate-700">
              Assignment CSV file
              <input
                type="file"
                accept=".csv,text/csv"
                disabled={isImportingAssignmentCsv || !assignmentLookups.loaded || Boolean(assignmentLookups.error)}
                onChange={(event) => void selectEmploymentAssignmentCsv(event.target.files?.[0])}
                className="mt-1.5 block w-full rounded-md border border-slate-300 px-3 py-2 text-xs text-slate-700 file:mr-3 file:rounded file:border-0 file:bg-emerald-50 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-emerald-700 disabled:opacity-50"
              />
            </label>
            <p className="text-[11px] leading-5 text-slate-500">
              Required: employee_no, company_code, employment_type, employee_category, hire_date, effective_from. Optional: org_unit_code, supervisor_employee_no, operational_group, payroll_group_code, location_codes (separate multiple codes with semicolons), primary_location_code (must be included in location_codes; defaults to the first location when blank), effective_to, separation_date, status (defaults to ACTIVE), is_active (defaults to true). Dates must use YYYY-MM-DD. Maximum file size 5 MB and 500 rows.
            </p>
            {assignmentLookups.error && <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">Could not load data needed to validate assignments: {assignmentLookups.error}</p>}
            {assignmentCsvFileName && <p className="text-xs font-medium text-slate-600">Selected: {assignmentCsvFileName}</p>}
            {assignmentCsvError && <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{assignmentCsvError}</p>}
            {assignmentCsvMessage && <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">{assignmentCsvMessage}</p>}
            {assignmentCsvPreviewRows.length > 0 && (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs text-slate-600">
                    {assignmentCsvPreviewRows.filter((row) => row.errors.length === 0).length} ready · {assignmentCsvPreviewRows.filter((row) => row.errors.length > 0).length} row(s) with errors
                  </p>
                  <button
                    type="button"
                    onClick={() => void importEmploymentAssignmentCsv()}
                    disabled={isImportingAssignmentCsv || assignmentCsvPreviewRows.some((row) => row.errors.length > 0 || row.payload === null)}
                    className="inline-flex items-center justify-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <FileUp className="h-4 w-4" />
                    {isImportingAssignmentCsv ? 'Importing all assignments…' : 'Import all assignments'}
                  </button>
                </div>
                <div className="max-h-72 overflow-auto rounded-md border border-slate-200">
                  <table className="min-w-full text-left text-xs">
                    <thead className="sticky top-0 bg-slate-50 text-[11px] uppercase text-slate-500">
                      <tr>
                        <th className="px-3 py-2">CSV row</th>
                        <th className="px-3 py-2">Employee number</th>
                        <th className="px-3 py-2">Company code</th>
                        <th className="px-3 py-2">Validation</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {assignmentCsvPreviewRows.map((row) => (
                        <tr key={row.rowNumber}>
                          <td className="whitespace-nowrap px-3 py-2 text-slate-600">{row.rowNumber}</td>
                          <td className="whitespace-nowrap px-3 py-2 font-medium text-slate-800">{row.employeeNo || '(blank)'}</td>
                          <td className="whitespace-nowrap px-3 py-2 text-slate-700">{row.companyCode || '(blank)'}</td>
                          <td className={`px-3 py-2 ${row.errors.length ? 'text-rose-700' : 'text-emerald-700'}`}>
                            {row.errors.length ? row.errors.join(' ') : 'Ready'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>
        )}

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
                  <span className="inline-flex items-center justify-center gap-1.5">
                    <tab.icon aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
                    {tab.label}
                  </span>
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
