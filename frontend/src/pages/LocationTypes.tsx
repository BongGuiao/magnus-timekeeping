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
  createLocationType,
  deleteLocationType,
  fetchLocationTypes,
  updateLocationType,
} from '../lib/locationApi'
import type {
  LocationTypeCreatePayload,
  LocationTypeOption,
  LocationTypeUpdatePayload,
} from '../lib/locationApi'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const locationTypeSchema = z.object({
  location_type: z.string()
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

type LocationTypeFormValues = z.infer<typeof locationTypeSchema>

const emptyLocationType: LocationTypeFormValues = {
  location_type: '',
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

export default function LocationTypes({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const { companyId } = useCompanySetupSelection()
  const [types, setTypes] = useState<LocationTypeOption[]>([])
  const [editingType, setEditingType] = useState<LocationTypeOption | null>(null)
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
    fetchLocationTypes(companyId, true, showDeleted)
      .then((items) => {
        if (isCurrent) setTypes(items)
      })
      .catch((error: unknown) => {
        if (isCurrent) {
          setErrorMessage(error instanceof Error ? error.message : 'Could not load location types.')
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

  const defaultValues: LocationTypeFormValues = editingType
    ? {
        location_type: editingType.location_type,
        display_name: editingType.display_name,
        sort_order: editingType.sort_order,
        is_default: editingType.is_default,
        is_active: editingType.is_active,
      }
    : emptyLocationType

  function openCreate() {
    setErrorMessage('')
    setSuccessMessage('')
    setEditingType(null)
    setIsFormOpen(true)
  }

  function openEdit(type: LocationTypeOption) {
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

  async function removeLocationType(type: LocationTypeOption) {
    if (!companyId) return
    const confirmed = window.confirm(
      `Delete location type ${type.display_name} (${type.location_type})?\n\n`
      + 'Existing locations keep their type for history. The type will no longer be available for new locations.',
    )
    if (!confirmed) return
    setErrorMessage('')
    setSuccessMessage('')
    setDeletingType(type.location_type)
    try {
      const deleted = await deleteLocationType(companyId, type.location_type)
      setTypes((current) => showDeleted
        ? current.map((item) => item.location_type === deleted.location_type ? deleted : item)
        : current.filter((item) => item.location_type !== deleted.location_type))
      setSuccessMessage(`Location type ${deleted.location_type} deleted. Existing location history is kept.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not delete the location type.')
    } finally {
      setDeletingType(null)
    }
  }

  async function saveLocationType(values: LocationTypeFormValues) {
    if (!companyId) {
      setErrorMessage('Select a company before managing location types.')
      return
    }
    setErrorMessage('')
    setSuccessMessage('')

    const normalizedCode = values.location_type.trim().toUpperCase()
    if (!editingType && types.some((type) => type.location_type === normalizedCode)) {
      setErrorMessage(`The type code "${normalizedCode}" already exists for this company.`)
      return
    }

    try {
      const savedType = editingType
        ? await updateLocationType(companyId, editingType.location_type, {
            display_name: values.display_name,
            sort_order: values.sort_order,
            is_default: values.is_default,
            is_active: values.is_active,
          } satisfies LocationTypeUpdatePayload)
        : await createLocationType({
            company_id: companyId,
            location_type: normalizedCode,
            display_name: values.display_name,
            sort_order: values.sort_order,
            is_default: values.is_default,
            is_active: values.is_active,
          } satisfies LocationTypeCreatePayload)
      setTypes((current) => {
        const next = current.map((type) => (
          savedType.is_default && type.location_type !== savedType.location_type
            ? { ...type, is_default: false }
            : type
        ))
        const updatedTypes = editingType
          ? next.map((type) => type.location_type === savedType.location_type ? savedType : type)
          : [...next, savedType]
        return updatedTypes.sort((left, right) => (
          left.sort_order - right.sort_order
          || left.location_type.localeCompare(right.location_type)
        ))
      })
      closeForm()
      setSuccessMessage(`Location type ${savedType.location_type} ${editingType ? 'updated' : 'created'} successfully.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not save the location type.')
    }
  }

  const columns: DataTableColumn<LocationTypeOption>[] = [
    { key: 'code', header: 'Type code', value: (type) => type.location_type },
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
                onClick={() => void removeLocationType(type)}
                disabled={deletingType === type.location_type}
                aria-label={`Delete ${type.display_name}`}
                className="rounded-md p-2 text-rose-600 hover:bg-rose-50 disabled:opacity-50"
              >
                {deletingType === type.location_type
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
      <TopNav employeeName={employeeName} activeView="location-types" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-3">
          <p className="text-xs text-slate-500">
            Manage the types used to classify company locations. Existing locations keep their type if it is deactivated; inactive types cannot be assigned to new locations.
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
            Select a company in the top navigation to manage its location types.
          </section>
        ) : (
          <DataTable
            rows={types}
            columns={columns}
            getRowKey={(type) => `${type.company_id}-${type.location_type}`}
            searchPlaceholder="Search type code or display name"
            emptyMessage={isLoading ? 'Loading location types…' : 'No location types match your search.'}
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

      <FormModal<LocationTypeFormValues>
        isOpen={isFormOpen}
        title={editingType ? 'Edit location type' : 'Create location type'}
        description="Type codes are unique within a company and cannot be changed after creation."
        defaultValues={defaultValues}
        resetKey={editingType?.location_type ?? 'new'}
        resolver={zodResolver(locationTypeSchema)}
        submitLabel={editingType ? 'Save changes' : 'Create type'}
        onClose={closeForm}
        onSubmit={saveLocationType}
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
                  {...register('location_type', { setValueAs: (value: string) => value.toUpperCase() })}
                  disabled={Boolean(editingType)}
                  maxLength={30}
                  className={`${inputClassName} disabled:bg-slate-100 disabled:text-slate-500`}
                />
                <FieldError message={errors.location_type?.message} />
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
                  Default type for new locations
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
