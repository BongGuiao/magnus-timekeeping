import { useEffect, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { z } from 'zod'
import DataTable from '../components/common/DataTable'
import type { DataTableColumn } from '../components/common/DataTable'
import FormModal from '../components/common/FormModal'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useCompanySetupSelection } from '../hooks/useCompanySetupSelection'
import { useLogout } from '../hooks/useLogout'
import {
  createOperationalGroup, deleteOperationalGroup, fetchOperationalGroups,
  restoreOperationalGroup, updateOperationalGroup,
} from '../lib/operationalGroupApi'
import type { OperationalGroup } from '../lib/operationalGroupApi'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const groupSchema = z.object({
  operational_group: z.string().trim().min(1, 'Group code is required.').max(30)
    .regex(/^[A-Za-z0-9_-]+$/, 'Use letters, numbers, hyphens, or underscores.'),
  display_name: z.string().trim().min(1, 'Display name is required.').max(50),
  sort_order: z.number().int().min(0, 'Sort order must be zero or greater.'),
  is_active: z.boolean(),
})
type GroupFormValues = z.infer<typeof groupSchema>
const emptyGroup: GroupFormValues = { operational_group: '', display_name: '', sort_order: 0, is_active: true }
const inputClassName = 'mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-100'
const labelClassName = 'text-xs font-semibold text-slate-700'

function FieldError({ message }: { message?: string }) {
  return message ? <p className="mt-1 text-xs font-medium text-rose-600">{message}</p> : null
}

export default function OperationalGroups(props: Props) {
  const { companyId } = useCompanySetupSelection()
  return <CompanyOperationalGroups key={companyId} companyId={companyId} {...props} />
}

function CompanyOperationalGroups({ companyId, employeeName, onNavigate, onLoggedOut }: Props & { companyId: string }) {
  const { logout } = useLogout({ onLoggedOut })
  const [groups, setGroups] = useState<OperationalGroup[]>([])
  const [editingGroup, setEditingGroup] = useState<OperationalGroup | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(Boolean(companyId))
  const [errorMessage, setErrorMessage] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [reloadKey, setReloadKey] = useState(0)
  const [showDeleted, setShowDeleted] = useState(false)
  const [changingCode, setChangingCode] = useState<string | null>(null)

  useEffect(() => {
    let isCurrent = true
    if (companyId) {
      fetchOperationalGroups(companyId, true, showDeleted)
        .then((items) => { if (isCurrent) setGroups(items) })
        .catch((error: unknown) => {
          if (isCurrent) setErrorMessage(error instanceof Error ? error.message : 'Could not load operational groups.')
        })
        .finally(() => { if (isCurrent) setIsLoading(false) })
    }
    return () => { isCurrent = false }
  }, [companyId, reloadKey, showDeleted])

  useEffect(() => {
    if (!successMessage) return
    const timeout = window.setTimeout(() => setSuccessMessage(''), 5000)
    return () => window.clearTimeout(timeout)
  }, [successMessage])

  function openForm(group: OperationalGroup | null) {
    setErrorMessage('')
    setSuccessMessage('')
    setEditingGroup(group)
    setIsFormOpen(true)
  }

  async function changeDeletedState(group: OperationalGroup) {
    const restoring = Boolean(group.deleted_at)
    if (!restoring && !window.confirm(
      `Delete operational group "${group.display_name}"? Existing assignments and history will be preserved.`,
    )) return
    setChangingCode(group.operational_group)
    setErrorMessage('')
    setSuccessMessage('')
    try {
      const saved = restoring
        ? await restoreOperationalGroup(companyId, group.operational_group)
        : await deleteOperationalGroup(companyId, group.operational_group)
      setGroups((current) => current.flatMap((item) => {
        if (item.operational_group !== saved.operational_group) return [item]
        return saved.deleted_at && !showDeleted ? [] : [saved]
      }))
      setSuccessMessage(restoring
        ? `Operational group ${saved.operational_group} restored as inactive. Edit it to reactivate.`
        : `Operational group ${saved.operational_group} deleted. Existing assignments and history were preserved.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not change the operational group.')
    } finally {
      setChangingCode(null)
    }
  }

  async function saveGroup(values: GroupFormValues) {
    if (!companyId) {
      setErrorMessage('Select a company before managing operational groups.')
      return
    }
    setErrorMessage('')
    setSuccessMessage('')
    const code = values.operational_group.toUpperCase()
    if (!editingGroup && groups.some((group) => group.operational_group === code)) {
      setErrorMessage(`The group code "${code}" already exists for this company.`)
      return
    }
    try {
      const payload = { display_name: values.display_name, sort_order: values.sort_order, is_active: values.is_active }
      const saved = editingGroup
        ? await updateOperationalGroup(companyId, editingGroup.operational_group, payload)
        : await createOperationalGroup({ ...payload, company_id: companyId, operational_group: code })
      setGroups((current) => (
        editingGroup
          ? current.map((group) => group.operational_group === saved.operational_group ? saved : group)
          : [...current, saved]
      ).sort((left, right) => left.sort_order - right.sort_order || left.operational_group.localeCompare(right.operational_group)))
      setIsFormOpen(false)
      setEditingGroup(null)
      setSuccessMessage(`Operational group ${saved.operational_group} ${editingGroup ? 'updated' : 'created'} successfully.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not save the operational group.')
    }
  }

  const columns: DataTableColumn<OperationalGroup>[] = [
    { key: 'code', header: 'Group code', value: (group) => group.operational_group },
    { key: 'name', header: 'Display name', value: (group) => group.display_name },
    { key: 'order', header: 'Order', value: (group) => group.sort_order },
    { key: 'status', header: 'Status', value: (group) => group.deleted_at ? 'Deleted' : group.is_active ? 'Active' : 'Inactive' },
    { key: 'deleted', header: 'Deleted at', value: (group) => group.deleted_at ?? '' },
    {
      key: 'actions', header: '', value: () => '', sortable: false, searchable: false,
      render: (group) => (
        <div className="flex items-center gap-1">
          {!group.deleted_at && (
            <button type="button" onClick={() => openForm(group)} aria-label={`Edit ${group.display_name}`}
              disabled={changingCode !== null}
              className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-50">
              <Pencil className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
          <button type="button" onClick={() => void changeDeletedState(group)}
            disabled={changingCode !== null || isFormOpen}
            aria-label={`${group.deleted_at ? 'Restore' : 'Delete'} ${group.display_name}`}
            className="rounded-md p-2 text-slate-500 hover:bg-rose-50 hover:text-rose-700 disabled:opacity-50">
            {group.deleted_at ? <RotateCcw className="h-4 w-4" aria-hidden="true" /> : <Trash2 className="h-4 w-4" aria-hidden="true" />}
          </button>
        </div>
      ),
    },
  ]

  return (
    <div className="min-h-svh bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="operational-groups" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full px-4 py-6 sm:px-6 lg:px-8">
        <p className="mb-3 text-xs text-slate-500">
          Manage operational groups for the selected company. Codes cannot be changed or reused.
          Delete hides a group from new assignments while preserving existing assignments and history. Deleted groups can be restored.
        </p>
        {errorMessage && !isFormOpen && (
          <div role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {errorMessage}
            <button type="button" className="ml-3 underline" onClick={() => {
              setErrorMessage('')
              setIsLoading(true)
              setGroups([])
              setReloadKey((key) => key + 1)
            }}>Retry</button>
          </div>
        )}
        {successMessage && <p role="status" className="mb-4 rounded-md bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{successMessage}</p>}
        {!companyId ? <p className="text-sm text-slate-600">Select a company to manage operational groups.</p> : (
          <DataTable columns={columns} rows={groups} getRowKey={(group) => group.operational_group}
            emptyMessage={isLoading ? 'Loading operational groups...' : 'No operational groups for this company.'}
            toolbar={(
              <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                <input type="checkbox" checked={showDeleted} disabled={changingCode !== null || isFormOpen}
                  onChange={(event) => {
                    setShowDeleted(event.target.checked)
                    setGroups([])
                    setIsLoading(true)
                    setErrorMessage('')
                  }} /> Show deleted
              </label>
              <button type="button" onClick={() => openForm(null)} disabled={isLoading || changingCode !== null}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
                <Plus className="h-4 w-4" /> Add operational group
              </button>
              </div>
            )} />
        )}
      </main>
      <FormModal<GroupFormValues> isOpen={isFormOpen} title={editingGroup ? 'Edit operational group' : 'Add operational group'}
        defaultValues={editingGroup ?? emptyGroup} resetKey={`${companyId}:${editingGroup?.operational_group ?? 'new'}`}
        resolver={zodResolver(groupSchema)} submitLabel={editingGroup ? 'Save changes' : 'Create group'}
        onClose={() => { setIsFormOpen(false); setErrorMessage('') }} onSubmit={saveGroup}>
        {({ register, formState: { errors } }) => (
          <div className="grid gap-4 sm:grid-cols-2">
            {errorMessage && <p role="alert" className="col-span-full text-sm text-rose-700">{errorMessage}</p>}
            <label className={labelClassName}>Group code
              <input {...register('operational_group')} readOnly={Boolean(editingGroup)} className={inputClassName} />
              <FieldError message={errors.operational_group?.message} />
            </label>
            <label className={labelClassName}>Display name
              <input {...register('display_name')} className={inputClassName} />
              <FieldError message={errors.display_name?.message} />
            </label>
            <label className={labelClassName}>Sort order
              <input type="number" min="0" step="1" {...register('sort_order', { valueAsNumber: true })} className={inputClassName} />
              <FieldError message={errors.sort_order?.message} />
            </label>
            <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
              <input type="checkbox" {...register('is_active')} /> Active
            </label>
          </div>
        )}
      </FormModal>
    </div>
  )
}
