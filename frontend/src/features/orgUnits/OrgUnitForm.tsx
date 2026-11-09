import { Controller, type UseFormReturn } from 'react-hook-form'
import SearchableSelect from '../../components/common/SearchableSelect'
import type { Company } from '../../types/company'
import type { Employee } from '../../types/employee'
import type { OrgUnit } from '../../types/orgUnit'
import type { OrgUnitFormValues } from './orgUnitSchema'
import type { OrgUnitType } from '../../lib/orgUnitApi'
import { descendantOrgUnitOptions } from './orgUnitHierarchy'

interface Props {
  form: UseFormReturn<OrgUnitFormValues>
  companies: Company[]
  employees: Employee[]
  orgUnits: OrgUnit[]
  orgUnitTypes: OrgUnitType[]
  selectedCompanyId?: string
  editingId?: string
}

const inputClassName = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
const labelClassName = 'text-xs font-semibold text-slate-700'

function FieldError({ message }: { message?: string }) {
  return message ? <p className="mt-1 text-xs font-medium text-rose-600">{message}</p> : null
}

function employeeName(employee: Employee) {
  const name = employee.preferred_name || [employee.first_name, employee.middle_name, employee.last_name]
    .filter(Boolean)
    .join(' ')
  return `${employee.employee_no} — ${name}${employee.is_active ? '' : ' (Inactive)'}`
}

export default function OrgUnitForm({
  form,
  companies,
  employees,
  orgUnits,
  orgUnitTypes,
  selectedCompanyId,
  editingId,
}: Props) {
  const { control, register, setValue, watch, formState: { errors } } = form
  const companyId = watch('company_id')
  const selectedOrgUnitType = watch('org_unit_type')
  const exclusionOptions = descendantOrgUnitOptions(orgUnits, companyId, editingId)
  const descendantIds = new Set(exclusionOptions.map((option) => option.value))
  const parentOptions = orgUnits.filter((unit) => (
    unit.company_id === companyId && unit.id !== editingId && !descendantIds.has(unit.id)
  ))
  const managerIsApprover = watch('manager_is_approver')
  const excludedOrgUnitIds = watch('excluded_approval_org_unit_ids')
  const selectedTypeIsAvailable = orgUnitTypes.some((type) => type.org_unit_type === selectedOrgUnitType)

  return (
    <div className="space-y-4">
      <section>
        <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Organization</h3>
        <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className={labelClassName}>
            Company
            <select {...register('company_id')} className={inputClassName} disabled={Boolean(selectedCompanyId)}>
              <option value="">Select a company</option>
              {companies.filter((company) => !selectedCompanyId || company.id === selectedCompanyId).map((company) => <option key={company.id} value={company.id}>{company.company_code} — {company.legal_name}</option>)}
            </select>
            <FieldError message={errors.company_id?.message} />
          </label>
          <label className={labelClassName}>
            Parent org unit
            <Controller name="parent_org_unit_id" control={control} render={({ field }) => (
              <SearchableSelect
                {...field}
                inputRef={field.ref}
                label="Parent org unit"
                placeholder="Search parent org units"
                className={inputClassName}
                disabled={!companyId}
                options={[
                  { value: '', label: 'No parent' },
                  ...parentOptions.map((unit) => ({
                    value: unit.id,
                    label: `${unit.org_unit_code} — ${unit.org_unit_name}`,
                  })),
                ]}
              />
            )} />
            <FieldError message={errors.parent_org_unit_id?.message} />
          </label>
          <label className={labelClassName}>
            Org unit code
            <input {...register('org_unit_code', { setValueAs: (value: string) => value.toUpperCase() })} className={inputClassName} />
            <FieldError message={errors.org_unit_code?.message} />
          </label>
          <label className={labelClassName}>
            Org unit name
            <input {...register('org_unit_name')} className={inputClassName} />
            <FieldError message={errors.org_unit_name?.message} />
          </label>
          <label className={labelClassName}>
            Org unit type
            <select {...register('org_unit_type')} className={inputClassName}>
              <option value="">Select an org unit type</option>
              {!selectedTypeIsAvailable && selectedOrgUnitType && (
                <option value={selectedOrgUnitType}>{selectedOrgUnitType} (inactive or unavailable)</option>
              )}
              {orgUnitTypes.map((type) => (
                <option key={type.org_unit_type} value={type.org_unit_type}>
                  {type.display_name}
                </option>
              ))}
            </select>
            <FieldError message={errors.org_unit_type?.message} />
          </label>
          <label className={labelClassName}>
            Cost center code
            <input {...register('cost_center_code', { setValueAs: (value: string) => value.toUpperCase() })} className={inputClassName} />
            <FieldError message={errors.cost_center_code?.message} />
          </label>
          <label className={`${labelClassName} sm:col-span-2 lg:col-span-3`}>
            Manager employee
            <Controller name="manager_employee_id" control={control} render={({ field }) => (
              <SearchableSelect
                {...field}
                inputRef={field.ref}
                label="Manager employee"
                placeholder="Search employees by number or name"
                className={inputClassName}
                options={[
                  { value: '', label: 'No manager' },
                  ...employees.map((employee) => ({
                    value: employee.id,
                    label: employeeName(employee),
                  })),
                ]}
              />
            )} />
            <FieldError message={errors.manager_employee_id?.message} />
          </label>
        </div>
      </section>

      <section>
        <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Approval settings</h3>
        <label className={`${labelClassName} mt-2 flex items-center gap-3`}>
          <input type="checkbox" {...register('manager_is_approver')} className="h-4 w-4 accent-indigo-600" />
          Manager is an approver
        </label>
        <p className="mt-1 text-[11px] text-slate-500">
          Enabled by default. When disabled, new requests use the next eligible ancestor manager.
          Existing pending approvals keep their assigned reviewer.
        </p>
        <label className={`${labelClassName} mt-3 block`}>
          Excluded org units
          <SearchableSelect
            label="Excluded org units"
            value=""
            onChange={(id) => {
              if (id && !excludedOrgUnitIds.includes(id)) {
                setValue('excluded_approval_org_unit_ids', [...excludedOrgUnitIds, id], {
                  shouldDirty: true, shouldValidate: true,
                })
              }
            }}
            disabled={!editingId || !managerIsApprover || !exclusionOptions.length}
            placeholder="Search descendant org units to exclude"
            className={inputClassName}
            options={exclusionOptions.filter((option) => !excludedOrgUnitIds.includes(option.value))}
          />
        </label>
        {excludedOrgUnitIds.length > 0 && (
          <ul className="mt-2 space-y-1">
            {excludedOrgUnitIds.map((id) => {
              const option = exclusionOptions.find((item) => item.value === id)
              return (
                <li key={id} className={`flex items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${option ? 'border-slate-200 text-slate-700' : 'border-amber-200 text-amber-800'}`}>
                  <span>{option?.label ?? `Unavailable or no longer a descendant (${id})`}</span>
                  <button type="button" aria-label={`Remove exclusion ${option?.label ?? id}`}
                    onClick={() => setValue('excluded_approval_org_unit_ids', excludedOrgUnitIds.filter((value) => value !== id), {
                      shouldDirty: true, shouldValidate: true,
                    })}
                    className="shrink-0 rounded px-2 py-1 font-semibold hover:bg-slate-100">
                    Remove
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        <FieldError message={errors.excluded_approval_org_unit_ids?.message} />
        <p className="mt-1 text-[11px] text-slate-500">
          {!editingId ? 'Create this org unit first to configure descendant exclusions.' : (
            'Only descendant units in this company can be selected. Each exclusion covers its entire subtree '
            + "for this manager only; those units' own eligible managers are unaffected."
          )}
        </p>
      </section>

      <section>
        <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Effective period</h3>
        <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className={labelClassName}>Effective from<input type="date" {...register('effective_from')} className={inputClassName} /><FieldError message={errors.effective_from?.message} /></label>
          <label className={labelClassName}>Effective to<input type="date" {...register('effective_to')} className={inputClassName} /><FieldError message={errors.effective_to?.message} /></label>
          <label className={labelClassName}>
            Status
            <select {...register('status')} className={inputClassName}>
              <option value="DRAFT">Draft</option>
              <option value="ACTIVE">Active</option>
              <option value="INACTIVE">Inactive</option>
            </select>
            <FieldError message={errors.status?.message} />
          </label>
          <label className="flex items-center gap-3 self-end rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700">
            <input type="checkbox" {...register('is_active')} className="h-4 w-4 accent-indigo-600" />
            Enabled for use
          </label>
        </div>
      </section>
    </div>
  )
}