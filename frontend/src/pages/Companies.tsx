import { useEffect, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { Pencil, Plus } from 'lucide-react'
import { z } from 'zod'
import PsgcAddressFields from '../components/common/PsgcAddressFields'
import DataTable from '../components/common/DataTable'
import type { DataTableColumn } from '../components/common/DataTable'
import FormModal from '../components/common/FormModal'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { useCompanySetupSelection } from '../hooks/useCompanySetupSelection'
import { createCompany, fetchCompanies, fetchCompany, updateCompany } from '../lib/companyApi'
import type { Company } from '../types/company'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const companySchema = z.object({
  company_code: z.string().trim().min(1, 'Company code is required.').max(30).regex(/^[A-Z0-9_-]+$/, 'Use uppercase letters, numbers, hyphens, or underscores.'),
  legal_name: z.string().trim().min(1, 'Legal name is required.').max(200),
  trade_name: z.string().trim().max(200),
  tax_id: z.string().trim().max(30),
  registration_no: z.string().trim().max(50),
  timezone: z.string().trim().min(1, 'Timezone is required.').max(50),
  address_line1: z.string().trim().max(200),
  address_line2: z.string().trim().max(200),
  region: z.string().trim().max(100),
  psgc_region_code: z.string().regex(/^$|^\d{9}$/),
  psgc_province_code: z.string().regex(/^$|^\d{9}$/),
  psgc_city_code: z.string().regex(/^$|^\d{9}$/),
  psgc_barangay_code: z.string().regex(/^$|^\d{9}$/),
  barangay: z.string().trim().max(100),
  city: z.string().trim().max(100),
  province: z.string().trim().max(100),
  postal_code: z.string().trim().max(20),
  default_currency: z.string().trim().length(3, 'Currency must contain three letters.').regex(/^[A-Z]{3}$/, 'Use an ISO currency code such as PHP.'),
  status: z.enum(['DRAFT', 'ACTIVE', 'INACTIVE']),
  is_active: z.boolean(),
})

type CompanyFormValues = z.infer<typeof companySchema>

const emptyCompany: CompanyFormValues = {
  company_code: '',
  legal_name: '',
  trade_name: '',
  tax_id: '',
  registration_no: '',
  timezone: 'Asia/Manila',
  address_line1: '',
  address_line2: '',
  region: '',
  psgc_region_code: '',
  psgc_province_code: '',
  psgc_city_code: '',
  psgc_barangay_code: '',
  barangay: '',
  city: '',
  province: '',
  postal_code: '',
  default_currency: 'PHP',
  status: 'ACTIVE',
  is_active: true,
}

function nullable(value: string) {
  return value || null
}

function formatUpdatedAt(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value))
}

function FieldError({ message }: { message?: string }) {
  return message ? <p className="mt-1 text-xs font-medium text-rose-600">{message}</p> : null
}

export default function Companies({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const { companyId, selectCompany } = useCompanySetupSelection()
  const [companies, setCompanies] = useState<Company[]>([])
  const [editingCompany, setEditingCompany] = useState<Company | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  useEffect(() => {
    fetchCompanies()
      .then(setCompanies)
      .catch((error: unknown) => setErrorMessage(error instanceof Error ? error.message : 'Could not load companies.'))
      .finally(() => setIsLoading(false))
  }, [])

  useEffect(() => {
    setIsFormOpen(false)
    setEditingCompany(null)
  }, [companyId])

  useEffect(() => {
    if (!successMessage) return
    const timeout = window.setTimeout(() => setSuccessMessage(''), 5000)
    return () => window.clearTimeout(timeout)
  }, [successMessage])

  const uniqueCompanySchema = companySchema.superRefine((values, context) => {
    const duplicate = companies.some((company) => company.company_code === values.company_code && company.id !== editingCompany?.id)
    if (duplicate) context.addIssue({ code: 'custom', path: ['company_code'], message: 'Company code must be unique.' })
  })

  const defaultValues: CompanyFormValues = editingCompany
    ? {
        company_code: editingCompany.company_code,
        legal_name: editingCompany.legal_name,
        trade_name: editingCompany.trade_name ?? '',
        tax_id: editingCompany.tax_id ?? '',
        registration_no: editingCompany.registration_no ?? '',
        timezone: editingCompany.timezone,
        address_line1: editingCompany.address_line1 ?? '',
        address_line2: editingCompany.address_line2 ?? '',
        region: editingCompany.region ?? '',
        psgc_region_code: editingCompany.psgc_region_code ?? '',
        psgc_province_code: editingCompany.psgc_province_code ?? '',
        psgc_city_code: editingCompany.psgc_city_code ?? '',
        psgc_barangay_code: editingCompany.psgc_barangay_code ?? '',
        barangay: editingCompany.barangay ?? '',
        city: editingCompany.city ?? '',
        province: editingCompany.province ?? '',
        postal_code: editingCompany.postal_code ?? '',
        default_currency: editingCompany.default_currency,
        status: editingCompany.status,
        is_active: editingCompany.is_active,
      }
    : emptyCompany
  const companyRows = companyId
    ? companies.filter((company) => company.id === companyId)
    : companies

  function openCreate() {
    setErrorMessage('')
    setSuccessMessage('')
    setEditingCompany(null)
    setIsFormOpen(true)
  }

  async function openEdit(company: Company) {
    setErrorMessage('')
    setSuccessMessage('')
    try {
      const fullCompany = await fetchCompany(company.id)
      setEditingCompany(fullCompany)
      setIsFormOpen(true)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not load this company.')
    }
  }

  function closeForm() {
    setIsFormOpen(false)
    setEditingCompany(null)
  }

  async function saveCompany(values: CompanyFormValues) {
    setErrorMessage('')
    setSuccessMessage('')
    const payload = {
      company_code: values.company_code,
      legal_name: values.legal_name,
      trade_name: nullable(values.trade_name),
      tax_id: nullable(values.tax_id),
      registration_no: nullable(values.registration_no),
      timezone: values.timezone,
      address_line1: nullable(values.address_line1),
      address_line2: nullable(values.address_line2),
      region: nullable(values.region),
      psgc_region_code: nullable(values.psgc_region_code),
      psgc_province_code: nullable(values.psgc_province_code),
      psgc_city_code: nullable(values.psgc_city_code),
      psgc_barangay_code: nullable(values.psgc_barangay_code),
      barangay: nullable(values.barangay),
      city: nullable(values.city),
      province: nullable(values.province),
      postal_code: nullable(values.postal_code),
      default_currency: values.default_currency,
      status: values.status,
      is_active: values.is_active,
    }
    try {
      const isUpdating = Boolean(editingCompany)
      const company = editingCompany
        ? await updateCompany(editingCompany.id, payload)
        : await createCompany(payload)
      setCompanies((current) => editingCompany
        ? current.map((item) => item.id === company.id ? company : item)
        : [company, ...current])
      if (!editingCompany) selectCompany(company.id)
      closeForm()
      setSuccessMessage(`Company ${company.company_code} ${isUpdating ? 'updated' : 'created'} successfully.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not save the company.')
    }
  }

  const columns: DataTableColumn<Company>[] = [
    {
      key: 'company',
      header: 'Company',
      value: (company) => `${company.company_code} ${company.legal_name} ${company.trade_name ?? ''}`,
      render: (company) => (
        <div>
          <p className="font-bold text-slate-900">{company.company_code}</p>
          <p className="max-w-xs truncate text-xs text-slate-500">{company.legal_name}</p>
        </div>
      ),
    },
    { key: 'location', header: 'Location', value: (company) => `${company.city ?? ''} ${company.province ?? ''}`, render: (company) => company.city || '—' },
    { key: 'timezone', header: 'Timezone', value: (company) => company.timezone },
    { key: 'currency', header: 'Currency', value: (company) => company.default_currency },
    {
      key: 'status',
      header: 'Status',
      value: (company) => company.status,
      render: (company) => (
        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${
          company.status === 'ACTIVE'
            ? 'bg-emerald-50 text-emerald-700'
            : company.status === 'DRAFT'
              ? 'bg-amber-50 text-amber-700'
              : 'bg-slate-100 text-slate-600'
        }`}>
          {company.status}
        </span>
      ),
    },
    { key: 'updated', header: 'Updated', value: (company) => company.updated_at, render: (company) => formatUpdatedAt(company.updated_at) },
    {
      key: 'actions',
      header: '',
      value: () => '',
      sortable: false,
      searchable: false,
      render: (company) => (
        <button type="button" onClick={() => openEdit(company)} aria-label={`Edit ${company.company_code}`} className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700">
          <Pencil className="h-4 w-4" />
        </button>
      ),
    },
  ]

  const inputClassName = 'mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
  const labelClassName = 'text-xs font-semibold text-slate-700'

  return (
    <div className="min-h-svh bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="companies" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-3">
          <p className="text-xs text-slate-500">Manage legal entities, operating details, and company status.</p>
        </div>

        {errorMessage && <p role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
        {successMessage && <p role="status" className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{successMessage}</p>}

        <DataTable
          rows={companyRows}
          columns={columns}
          getRowKey={(company) => company.id}
          searchPlaceholder="Search code, name, or location"
          emptyMessage={isLoading ? 'Loading companies…' : 'No companies match your search.'}
          toolbar={(
            <button type="button" onClick={openCreate} className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">
              <Plus className="h-4 w-4" />
              New company
            </button>
          )}
        />
      </main>

      <FormModal<CompanyFormValues>
        isOpen={isFormOpen}
        title={editingCompany ? 'Edit company' : 'Create company'}
        description="Required fields mirror the company validation contract."
        defaultValues={defaultValues}
        resetKey={editingCompany?.id ?? 'new'}
        resolver={zodResolver(uniqueCompanySchema)}
        submitLabel={editingCompany ? 'Save changes' : 'Create company'}
        onClose={closeForm}
        onSubmit={saveCompany}
      >
        {({ register, watch, setValue, formState: { errors } }) => (
          <div className="space-y-4">
            {errorMessage && <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
            <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Identity</h3>
              <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                <label className={labelClassName}>Company code<input {...register('company_code', { setValueAs: (value: string) => value.toUpperCase() })} className={inputClassName} /><FieldError message={errors.company_code?.message} /></label>
                <label className={labelClassName}>Legal name<input {...register('legal_name')} className={inputClassName} /><FieldError message={errors.legal_name?.message} /></label>
                <label className={labelClassName}>Trade name<input {...register('trade_name')} className={inputClassName} /><FieldError message={errors.trade_name?.message} /></label>
                <label className={labelClassName}>Tax ID<input {...register('tax_id')} className={inputClassName} /><FieldError message={errors.tax_id?.message} /></label>
                <label className={labelClassName}>Registration no.<input {...register('registration_no')} className={inputClassName} /><FieldError message={errors.registration_no?.message} /></label>
              </div>
            </section>

            <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Operations</h3>
              <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                <label className={labelClassName}>Timezone<input {...register('timezone')} className={inputClassName} /><FieldError message={errors.timezone?.message} /></label>
                <label className={labelClassName}>Currency<input {...register('default_currency', { setValueAs: (value: string) => value.toUpperCase() })} maxLength={3} className={inputClassName} /><FieldError message={errors.default_currency?.message} /></label>
                <label className={labelClassName}>Status<select {...register('status')} className={inputClassName}><option value="DRAFT">Draft</option><option value="ACTIVE">Active</option><option value="INACTIVE">Inactive</option></select><FieldError message={errors.status?.message} /></label>
                <label className="flex items-center gap-3 self-end rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700"><input type="checkbox" {...register('is_active')} className="h-4 w-4 accent-indigo-600" />Enabled for use</label>
              </div>
            </section>

            <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Address</h3>
              <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                <label className={`${labelClassName} sm:col-span-2 lg:col-span-1`}>Address line 1<input {...register('address_line1')} className={inputClassName} /><FieldError message={errors.address_line1?.message} /></label>
                <label className={`${labelClassName} sm:col-span-2 lg:col-span-1`}>Address line 2<input {...register('address_line2')} className={inputClassName} /><FieldError message={errors.address_line2?.message} /></label>
                <PsgcAddressFields
                  region={watch('region')}
                  province={watch('province')}
                  city={watch('city')}
                  barangay={watch('barangay')}
                  psgcRegionCode={watch('psgc_region_code') || null}
                  psgcProvinceCode={watch('psgc_province_code') || null}
                  psgcCityCode={watch('psgc_city_code') || null}
                  psgcBarangayCode={watch('psgc_barangay_code') || null}
                  errors={{
                    province: errors.province?.message,
                    city: errors.city?.message,
                    barangay: errors.barangay?.message,
                  }}
                  onChange={(field, value) => setValue(field, value, { shouldDirty: true, shouldValidate: true })}
                />
                <label className={labelClassName}>Postal code<input {...register('postal_code')} className={inputClassName} /><FieldError message={errors.postal_code?.message} /></label>
              </div>
            </section>
          </div>
        )}
      </FormModal>
    </div>
  )
}