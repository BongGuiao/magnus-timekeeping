import { useEffect, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { LoaderCircle, Pencil, Plus, Trash2 } from 'lucide-react'
import { z } from 'zod'
import DataTable from '../components/common/DataTable'
import type { DataTableColumn } from '../components/common/DataTable'
import FormModal from '../components/common/FormModal'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useCompanySetupSelection } from '../hooks/useCompanySetupSelection'
import { useLogout } from '../hooks/useLogout'
import {
  createOrgUnitType,
  deleteOrgUnitType,
  fetchOrgUnitTypes,
  updateOrgUnitType,
} from '../lib/orgUnitApi'
import type {
  OrgUnitType,
  OrgUnitTypeCreatePayload,
  OrgUnitTypeUpdatePayload,
} from '../lib/orgUnitApi'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const orgUnitTypeSchema = z.object({
  org_unit_type: z.string()
    .trim()
    .min(1, 'Type code is required.')
    .max(30, 'Type code must be 30 characters or fewer.')
    .regex(/^[A-Za-z0-9_-]+$/, 'Use letters, numbers, hyphens, or underscores.'),
  display_name: z.string().trim().min(1, 'Display name is required.').max(50),
  sort_order: z.number().int().min(0, 'Sort order must be zero or greater.'),
  is_default: z.boolean(),
  is_active: z.boolean(),
}).superRefine((values, context) => {
  if (values.is_default && !values.is_active) {
    context.addIssue({
      code: 'custom',
      path: ['is_default'],
      message: 'An inactive type cannot be the default.',
    })
  }
})

type OrgUnitTypeFormValues = z.infer<typeof orgUnitTypeSchema>

const emptyOrgUnitType: OrgUnitTypeFormValues = {
  org_unit_type: '',
  display_name: '',
  sort_order: 0,
  is_default: false,
  is_active: true,
}

const inputClassName = 'mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
const labelClassName = 'text-xs font-semibold text-slate-700'

function FieldError({ message }: { message?: string }) {
  return message ? <p className="mt-1 text-xs font-medium text-rose-600">{message}</p> : null
}

export default function OrgUnitTypes({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const { companyId } = useCompanySetupSelection()
  const [types, setTypes] = useState<OrgUnitType[]>([])
  const [editingType, setEditingType] = useState<OrgUnitType | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [deletingType, setDeletingType] = useState<string | null>(null)
  const [showDeleted, setShowDeleted] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  useEffect(() => {
    let isCurrent = true
    setIsFormOpen(false)
    setEditingType(null)
    setErrorMessage('')
    setTypes([])

    if (!companyId) {
      setIsLoading(false)
      return () => {
        isCurrent = false
      }
    }

    setIsLoading(true)
    fetchOrgUnitTypes(companyId, true, showDeleted)
      .then((items) => {
        if (isCurrent) setTypes(items)
      })
      .catch((error: unknown) => {
        if (isCurrent) {
          setErrorMessage(error instanceof Error ? error.message : 'Could not load organization unit types.')
        }
      })
      .finally(() => {
        if (isCurrent) setIsLoading(false)
      })

    return () => {
      isCurrent = false
    }
  }, [companyId, showDeleted])

  useEffect(() => {
    if (!successMessage) return
    const timeout = window.setTimeout(() => setSuccessMessage(''), 5000)
    return () => window.clearTimeout(timeout)
  }, [successMessage])

  const defaultValues: OrgUnitTypeFormValues = editingType
    ? {
        org_unit_type: editingType.org_unit_type,
        display_name: editingType.display_name,
        sort_order: editingType.sort_order,
        is_default: editingType.is_default,
        is_active: editingType.is_active,
      }
    : emptyOrgUnitType

  function openCreate() {
    setErrorMessage('')
    setSuccessMessage('')
    setEditingType(null)
    setIsFormOpen(true)
  }

  function openEdit(type: OrgUnitType) {
    setErrorMessage('')
    setSuccessMessage('')
    setEditingType(type)
    setIsFormOpen(true)
  }

  function closeForm() {
    setIsFormOpen(false)
    setEditingType(null)
    setErrorMessage('')
  }

  async function removeOrgUnitType(type: OrgUnitType) {
    if (!companyId) return
    const confirmed = window.confirm(
      `Delete organization unit type ${type.display_name} (${type.org_unit_type})?\n\n`
      + 'Existing organization units keep their type for history. The type will no longer be available for new organization units.',
    )
    if (!confirmed) return
    setErrorMessage('')
    setSuccessMessage('')
    setDeletingType(type.org_unit_type)
    try {
      const deleted = await deleteOrgUnitType(companyId, type.org_unit_type)
      setTypes((current) => showDeleted
        ? current.map((item) => item.org_unit_type === deleted.org_unit_type ? deleted : item)
        : current.filter((item) => item.org_unit_type !== deleted.org_unit_type))
      setSuccessMessage(`Organization unit type ${deleted.org_unit_type} deleted. Existing history is kept.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not delete the organization unit type.')
    } finally {
      setDeletingType(null)
    }
  }

  async function saveOrgUnitType(values: OrgUnitTypeFormValues) {
    if (!companyId) {
      setErrorMessage('Select a company before managing organization unit types.')
      return
    }
    setErrorMessage('')
    setSuccessMessage('')

    const normalizedCode = values.org_unit_type.trim().toUpperCase()
    if (!editingType && types.some((type) => type.org_unit_type === normalizedCode)) {
      setErrorMessage(`The type code "${normalizedCode}" already exists for this company.`)
      return
    }

    try {
      const savedType = editingType
        ? await updateOrgUnitType(companyId, editingType.org_unit_type, {
            display_name: values.display_name,
            sort_order: values.sort_order,
            is_default: values.is_default,
            is_active: values.is_active,
          } satisfies OrgUnitTypeUpdatePayload)
        : await createOrgUnitType({
            company_id: companyId,
            org_unit_type: normalizedCode,
            display_name: values.display_name,
            sort_order: values.sort_order,
            is_default: values.is_default,
            is_active: values.is_active,
          } satisfies OrgUnitTypeCreatePayload)
      setTypes((current) => {
        const next = current.map((type) => (
          savedType.is_default && type.org_unit_type !== savedType.org_unit_type
            ? { ...type, is_default: false }
            : type
        ))
        const updatedTypes = editingType
          ? next.map((type) => type.org_unit_type === savedType.org_unit_type ? savedType : type)
          : [...next, savedType]
        return updatedTypes.sort((left, right) => (
          left.sort_order - right.sort_order
          || left.org_unit_type.localeCompare(right.org_unit_type)
        ))
      })
      closeForm()
      setSuccessMessage(`Org unit type ${savedType.org_unit_type} ${editingType ? 'updated' : 'created'} successfully.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not save the organization unit type.')
    }
  }

  const columns: DataTableColumn<OrgUnitType>[] = [
    { key: 'code', header: 'Type code', value: (type) => type.org_unit_type },
    { key: 'name', header: 'Display name', value: (type) => type.display_name },
    { key: 'order', header: 'Order', value: (type) => type.sort_order },
    {
      key: 'default',
      header: 'Default',
      value: (type) => type.is_default,
      render: (type) => type.is_default ? (
        <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-bold text-indigo-700">Default</span>
      ) : '—',
    },
    {
      key: 'status',
      header: 'Status',
      value: (type) => type.is_active ? 'Active' : 'Inactive',
      render: (type) => (
        <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${
          type.deleted_at
            ? 'bg-rose-50 text-rose-700'
            : type.is_active
              ? 'bg-emerald-50 text-emerald-700'
              : 'bg-slate-100 text-slate-600'
        }`}>
          {type.deleted_at ? 'Deleted' : type.is_active ? 'Active' : 'Inactive'}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      value: () => '',
      sortable: false,
      searchable: false,
      render: (type) => (
        <div className="flex items-center gap-1">
          {!type.deleted_at && (
            <>
              <button
                type="button"
                onClick={() => openEdit(type)}
                aria-label={`Edit ${type.display_name}`}
                className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700"
              >
                <Pencil className="h-4 w-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => void removeOrgUnitType(type)}
                disabled={deletingType === type.org_unit_type}
                aria-label={`Delete ${type.display_name}`}
                className="rounded-md p-2 text-rose-600 hover:bg-rose-50 disabled:opacity-50"
              >
                {deletingType === type.org_unit_type
                  ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                  : <Trash2 className="h-4 w-4" aria-hidden="true" />}
              </button>
            </>
          )}
          {type.deleted_at && (
            <span className="text-xs text-slate-500">
              Deleted {new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(type.deleted_at))}
            </span>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="min-h-svh bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="org-unit-types" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-3">
          <p className="text-xs text-slate-500">
            Manage the types available when creating organization units. Deactivate types you no longer use; type codes cannot be deleted or changed.
          </p>
        </div>

        {errorMessage && !isFormOpen && (
          <p role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {errorMessage}
          </p>
        )}
        {successMessage && (
          <p role="status" className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            {successMessage}
          </p>
        )}

        {!companyId ? (
          <section className="rounded-lg border border-amber-200 bg-amber-50 px-5 py-6 text-sm text-amber-800">
            Select a company in the top navigation to manage its organization unit types.
          </section>
        ) : (
          <DataTable
            rows={types}
            columns={columns}
            getRowKey={(type) => `${type.company_id}-${type.org_unit_type}`}
            searchPlaceholder="Search type code or display name"
            emptyMessage={isLoading ? 'Loading organization unit types…' : 'No organization unit types match your search.'}
            toolbar={(
              <div className="flex items-center gap-4">
                <button
                  type="button"
                  onClick={openCreate}
                  className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
                >
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  New type
                </button>
                <label className="flex items-center gap-2 whitespace-nowrap text-xs font-semibold text-slate-600">
                  <input
                    type="checkbox"
                    checked={showDeleted}
                    onChange={(event) => setShowDeleted(event.target.checked)}
                    className="h-4 w-4 accent-indigo-600"
                  />
                  Show deleted
                </label>
              </div>
            )}
          />
        )}
      </main>

      <FormModal<OrgUnitTypeFormValues>
        isOpen={isFormOpen}
        title={editingType ? 'Edit org unit type' : 'Create org unit type'}
        description="Type codes are unique within a company and cannot be changed after creation."
        defaultValues={defaultValues}
        resetKey={editingType?.org_unit_type ?? 'new'}
        resolver={zodResolver(orgUnitTypeSchema)}
        submitLabel={editingType ? 'Save changes' : 'Create type'}
        onClose={closeForm}
        onSubmit={saveOrgUnitType}
      >
        {({ register, formState: { errors } }) => (
          <>
            {errorMessage && (
              <p role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {errorMessage}
              </p>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <label className={labelClassName}>
                Type code
                <input
                  {...register('org_unit_type', { setValueAs: (value: string) => value.toUpperCase() })}
                  disabled={Boolean(editingType)}
                  maxLength={30}
                  className={`${inputClassName} disabled:bg-slate-100 disabled:text-slate-500`}
                />
                <FieldError message={errors.org_unit_type?.message} />
              </label>
              <label className={labelClassName}>
                Display name
                <input {...register('display_name')} maxLength={50} className={inputClassName} />
                <FieldError message={errors.display_name?.message} />
              </label>
              <label className={labelClassName}>
                Sort order
                <input {...register('sort_order', { valueAsNumber: true })} type="number" min={0} step={1} className={inputClassName} />
                <FieldError message={errors.sort_order?.message} />
              </label>
              <div className="flex flex-col gap-3 self-end pb-1">
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                  <input type="checkbox" {...register('is_default')} className="h-4 w-4 accent-indigo-600" />
                  Default type for new org units
                </label>
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                  <input type="checkbox" {...register('is_active')} className="h-4 w-4 accent-indigo-600" />
                  Active and available for selection
                </label>
                <FieldError message={errors.is_default?.message} />
              </div>
            </div>
          </>
        )}
      </FormModal>
    </div>
  )
}
