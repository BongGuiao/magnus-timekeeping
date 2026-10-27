import { useEffect, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { Pencil, Plus } from 'lucide-react'
import DataTable from '../components/common/DataTable'
import type { DataTableColumn } from '../components/common/DataTable'
import FormModal from '../components/common/FormModal'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import OrgUnitForm from '../features/orgUnits/OrgUnitForm'
import { emptyOrgUnit, orgUnitSchema, toOrgUnitFormValues } from '../features/orgUnits/orgUnitSchema'
import type { OrgUnitFormValues } from '../features/orgUnits/orgUnitSchema'
import { useLogout } from '../hooks/useLogout'
import { useCompanySetupSelection } from '../hooks/useCompanySetupSelection'
import { fetchCompanies } from '../lib/companyApi'
import { fetchEmployees } from '../lib/employeeApi'
import {
  createOrgUnit,
  fetchOrgUnit,
  fetchOrgUnits,
  fetchOrgUnitTypes,
  updateOrgUnit,
} from '../lib/orgUnitApi'
import type { OrgUnitType, OrgUnitWritePayload } from '../lib/orgUnitApi'
import type { Company } from '../types/company'
import type { Employee } from '../types/employee'
import type { OrgUnit } from '../types/orgUnit'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

function nullable(value: string) {
  return value || null
}

function formatDate(value: string | null) {
  if (!value) return 'Open-ended'
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`))
}

export default function OrgUnits({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const { companyId } = useCompanySetupSelection()
  const [companies, setCompanies] = useState<Company[]>([])
  const [employees, setEmployees] = useState<Employee[]>([])
  const [orgUnits, setOrgUnits] = useState<OrgUnit[]>([])
  const [orgUnitTypes, setOrgUnitTypes] = useState<OrgUnitType[]>([])
  const [editingOrgUnit, setEditingOrgUnit] = useState<OrgUnit | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [loadingEditId, setLoadingEditId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  useEffect(() => {
    let isCurrent = true
    setIsFormOpen(false)
    setEditingOrgUnit(null)

    Promise.allSettled([
      fetchCompanies(),
      companyId ? fetchOrgUnits(companyId) : Promise.resolve([]),
      fetchEmployees(),
      companyId ? fetchOrgUnitTypes(companyId) : Promise.resolve([]),
    ])
      .then(([companiesResult, orgUnitsResult, employeesResult, orgUnitTypesResult]) => {
        if (!isCurrent) return

        const errors: string[] = []
        if (companiesResult.status === 'fulfilled') {
          setCompanies(companiesResult.value)
        } else {
          errors.push(companiesResult.reason instanceof Error
            ? companiesResult.reason.message
            : 'Could not load companies.')
        }

        if (orgUnitsResult.status === 'fulfilled') {
          setOrgUnits(orgUnitsResult.value)
        } else {
          errors.push(orgUnitsResult.reason instanceof Error
            ? orgUnitsResult.reason.message
            : 'Could not load organization units.')
        }
        if (employeesResult.status === 'fulfilled') {
          setEmployees(employeesResult.value)
        } else {
          errors.push(employeesResult.reason instanceof Error
            ? employeesResult.reason.message
            : 'Could not load employees.')
        }
        if (orgUnitTypesResult.status === 'fulfilled') {
          setOrgUnitTypes(orgUnitTypesResult.value)
        } else {
          errors.push(orgUnitTypesResult.reason instanceof Error
            ? orgUnitTypesResult.reason.message
            : 'Could not load organization unit types.')
        }
        setErrorMessage(errors.join(' '))
      })
      .finally(() => {
        if (isCurrent) setIsLoading(false)
      })

    return () => {
      isCurrent = false
    }
  }, [companyId])

  useEffect(() => {
    if (!successMessage) return
    const timeout = window.setTimeout(() => setSuccessMessage(''), 5000)
    return () => window.clearTimeout(timeout)
  }, [successMessage])

  const uniqueOrgUnitSchema = orgUnitSchema.superRefine((values, context) => {
    const duplicate = orgUnits.some((unit) => (
      unit.company_id === values.company_id
      && unit.org_unit_code === values.org_unit_code
      && unit.id !== editingOrgUnit?.id
    ))
    if (duplicate) {
      context.addIssue({
        code: 'custom',
        path: ['org_unit_code'],
        message: 'Org unit code must be unique within the selected company.',
      })
    }
    if (values.parent_org_unit_id === editingOrgUnit?.id) {
      context.addIssue({ code: 'custom', path: ['parent_org_unit_id'], message: 'An org unit cannot be its own parent.' })
    }
  })

  const defaultValues: OrgUnitFormValues = editingOrgUnit
    ? toOrgUnitFormValues(editingOrgUnit)
    : {
        ...emptyOrgUnit,
        company_id: companyId,
        org_unit_type: orgUnitTypes.find((type) => type.is_default)?.org_unit_type ?? '',
      }

  function companyLabel(companyId: string) {
    const company = companies.find((item) => item.id === companyId)
    return company ? company.company_code : 'Unknown company'
  }

  function parentLabel(parentId: string | null) {
    if (!parentId) return 'Top level'
    const parent = orgUnits.find((unit) => unit.id === parentId)
    return parent ? parent.org_unit_name : 'Unknown parent'
  }

  function openCreate() {
    setErrorMessage('')
    setSuccessMessage('')
    setEditingOrgUnit(null)
    setIsFormOpen(true)
  }

  async function openEdit(orgUnit: OrgUnit) {
    setErrorMessage('')
    setSuccessMessage('')
    setLoadingEditId(orgUnit.id)
    try {
      const loadedOrgUnit = await fetchOrgUnit(orgUnit.id)
      if (!loadedOrgUnit) {
        setErrorMessage('This organization unit could not be found.')
        return
      }
      setEditingOrgUnit(loadedOrgUnit)
      setIsFormOpen(true)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not load this organization unit.')
    } finally {
      setLoadingEditId(null)
    }
  }

  function closeForm() {
    setIsFormOpen(false)
    setEditingOrgUnit(null)
    setErrorMessage('')
  }

  async function saveOrgUnit(values: OrgUnitFormValues) {
    setErrorMessage('')
    setSuccessMessage('')
    const payload: OrgUnitWritePayload = {
      company_id: values.company_id,
      parent_org_unit_id: nullable(values.parent_org_unit_id),
      org_unit_code: values.org_unit_code,
      org_unit_name: values.org_unit_name,
      org_unit_type: values.org_unit_type,
      manager_employee_id: nullable(values.manager_employee_id),
      cost_center_code: nullable(values.cost_center_code),
      effective_from: values.effective_from,
      effective_to: nullable(values.effective_to),
      status: values.status,
      is_active: values.is_active,
    }
    try {
      const isUpdating = Boolean(editingOrgUnit)
      const savedOrgUnit = editingOrgUnit
        ? await updateOrgUnit(editingOrgUnit.id, payload)
        : await createOrgUnit(payload)
      setOrgUnits((current) => editingOrgUnit
        ? current.map((item) => item.id === savedOrgUnit.id ? savedOrgUnit : item)
        : [savedOrgUnit, ...current])
      closeForm()
      setSuccessMessage(`Org unit ${savedOrgUnit.org_unit_code} ${isUpdating ? 'updated' : 'created'} successfully.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not save the organization unit.')
    }
  }

  const columns: DataTableColumn<OrgUnit>[] = [
    {
      key: 'unit',
      header: 'Org unit',
      value: (unit) => `${unit.org_unit_code} ${unit.org_unit_name}`,
      render: (unit) => (
        <div>
          <p className="font-bold text-slate-900">{unit.org_unit_code}</p>
          <p className="max-w-xs truncate text-xs text-slate-500">{unit.org_unit_name}</p>
        </div>
      ),
    },
    { key: 'company', header: 'Company', value: (unit) => companyLabel(unit.company_id) },
    { key: 'type', header: 'Type', value: (unit) => unit.org_unit_type },
    { key: 'parent', header: 'Parent', value: (unit) => parentLabel(unit.parent_org_unit_id) },
    { key: 'cost_center', header: 'Cost center', value: (unit) => unit.cost_center_code ?? '—' },
    {
      key: 'effective',
      header: 'Effective period',
      value: (unit) => `${unit.effective_from} ${unit.effective_to ?? ''}`,
      render: (unit) => <span>{formatDate(unit.effective_from)} – {formatDate(unit.effective_to)}</span>,
    },
    {
      key: 'status',
      header: 'Status',
      value: (unit) => unit.status,
      render: (unit) => (
        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${
          unit.status === 'ACTIVE'
            ? 'bg-emerald-50 text-emerald-700'
            : unit.status === 'DRAFT'
              ? 'bg-amber-50 text-amber-700'
              : 'bg-slate-100 text-slate-600'
        }`}>
          {unit.status}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      value: () => '',
      sortable: false,
      searchable: false,
      render: (unit) => (
        <button type="button" onClick={() => openEdit(unit)} disabled={loadingEditId === unit.id} aria-label={`Edit ${unit.org_unit_code}`} className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-50">
          <Pencil className="h-4 w-4" />
        </button>
      ),
    },
  ]

  return (
    <div className="min-h-svh bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="org-units" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] py-6">
        <div className="mb-3">
          <p className="text-xs text-slate-500">Maintain company hierarchy, ownership, cost centers, and effective dates.</p>
        </div>

        {errorMessage && !isFormOpen && <p role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
        {successMessage && <p role="status" className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{successMessage}</p>}

        <DataTable
          rows={orgUnits}
          columns={columns}
          getRowKey={(unit) => unit.id}
          searchPlaceholder="Search code, name, company, or type"
          emptyMessage={isLoading ? 'Loading organization units…' : 'No organization units match your search.'}
          toolbar={(
            <button type="button" onClick={openCreate} disabled={isLoading || !companyId} className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">
              <Plus className="h-4 w-4" />
              New org unit
            </button>
          )}
        />
      </main>

      <FormModal<OrgUnitFormValues>
        isOpen={isFormOpen}
        title={editingOrgUnit ? 'Edit org unit' : 'Create org unit'}
        description="Define hierarchy and effective dates within a company."
        defaultValues={defaultValues}
        resetKey={editingOrgUnit?.id ?? 'new'}
        resolver={zodResolver(uniqueOrgUnitSchema)}
        submitLabel={editingOrgUnit ? 'Save changes' : 'Create org unit'}
        onClose={closeForm}
        onSubmit={saveOrgUnit}
      >
        {(form) => (
          <>
            {errorMessage && <p role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
            <OrgUnitForm
              form={form}
              companies={companies}
              employees={employees}
              orgUnits={orgUnits}
              orgUnitTypes={orgUnitTypes}
              selectedCompanyId={companyId}
              editingId={editingOrgUnit?.id}
            />
          </>
        )}
      </FormModal>
    </div>
  )
}