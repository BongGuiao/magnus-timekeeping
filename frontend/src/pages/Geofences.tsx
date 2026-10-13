import { useEffect, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { Pencil, Plus } from 'lucide-react'
import { z } from 'zod'
import DataTable from '../components/common/DataTable'
import type { DataTableColumn } from '../components/common/DataTable'
import FormModal from '../components/common/FormModal'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { useCompanySetupSelection } from '../hooks/useCompanySetupSelection'
import { fetchCompanies } from '../lib/companyApi'
import { createGeofence, fetchGeofence, fetchGeofences, updateGeofence } from '../lib/geofenceApi'
import type { GeofenceWritePayload } from '../lib/geofenceApi'
import { fetchLocations } from '../lib/locationApi'
import type { Company } from '../types/company'
import type { Geofence } from '../types/geofence'
import type { Location } from '../types/location'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const inputClassName = 'mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
const labelClassName = 'text-xs font-semibold text-slate-700'
const maxGpsAccuracyMeters = import.meta.env.DEV ? 2000 : 100
const maxRadiusMeters = 1000

function SliderRuler({ max }: { max: number }) {
  const steps = 10
  return (
    <div aria-hidden="true" className="mt-1">
      <div className="flex justify-between px-[7px]">
        {Array.from({ length: steps + 1 }, (_, index) => (
          <span key={index} className={`w-px bg-slate-400 ${index % 5 === 0 ? 'h-3' : 'h-1.5'}`} />
        ))}
      </div>
      <div className="relative mt-0.5 h-4 text-[10px] font-normal text-slate-500">
        {Array.from({ length: steps / 5 + 1 }, (_, index) => {
          const value = Math.round((max / 2) * index)
          return (
            <span
              key={index}
              className={`absolute ${index === 0 ? 'left-0' : index === 2 ? 'right-0' : 'left-1/2 -translate-x-1/2'}`}
            >
              {value.toLocaleString()}
            </span>
          )
        })}
      </div>
    </div>
  )
}

const geofenceSchema = z.object({
  company_id: z.string().min(1, 'Company is required.'),
  location_id: z.string().min(1, 'Location is required.'),
  geofence_code: z.string().trim().min(1, 'Geofence code is required.').max(50),
  geofence_name: z.string().trim().min(1, 'Geofence name is required.').max(150),
  geofence_type: z.string().trim().min(1, 'Geofence type is required.').max(30),
  shape: z.enum(['CIRCLE', 'POLYGON']),
  center_point: z.string(),
  radius_meters: z.union([z.literal(''), z.number().positive()]),
  boundary_polygon: z.string(),
  maximum_gps_accuracy_meters: z.number().int().positive(),
  effective_from: z.string().min(1, 'Effective from is required.'),
  effective_to: z.string(),
  source_type: z.string().trim().min(1, 'Source type is required.').max(30),
  source_reference_id: z.string().trim().max(100),
  status: z.string().trim().min(1, 'Status is required.').max(20),
  is_active: z.boolean(),
}).superRefine((values, context) => {
  if (values.shape === 'CIRCLE') {
    if (!/^POINT\s*\(\s*-?\d+(\.\d+)?\s+-?\d+(\.\d+)?\s*\)$/i.test(values.center_point.trim())) {
      context.addIssue({
        code: 'custom',
        path: ['center_point'],
        message: 'Enter a POINT in longitude latitude order, e.g. POINT(121.0244 14.5547).',
      })
    }
    if (values.radius_meters === '') {
      context.addIssue({ code: 'custom', path: ['radius_meters'], message: 'Radius is required for a circle.' })
    }
  } else if (!/^POLYGON\s*\(\(.*\)\)$/is.test(values.boundary_polygon.trim())) {
    context.addIssue({
      code: 'custom',
      path: ['boundary_polygon'],
      message: 'Enter a valid POLYGON WKT boundary.',
    })
  }

  if (values.effective_to && new Date(values.effective_to) <= new Date(values.effective_from)) {
    context.addIssue({
      code: 'custom',
      path: ['effective_to'],
      message: 'Effective to must be later than effective from.',
    })
  }
})

type GeofenceFormValues = z.infer<typeof geofenceSchema>

function localDateTime(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const timezoneOffset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - timezoneOffset).toISOString().slice(0, 16)
}

function nullable(value: string) {
  return value || null
}

function FieldError({ message }: { message?: string }) {
  return message ? <p className="mt-1 text-xs font-medium text-rose-600">{message}</p> : null
}

function formatDate(value: string | null) {
  if (!value) return 'No end date'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value))
}

export default function Geofences({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const { companyId } = useCompanySetupSelection()
  const [companies, setCompanies] = useState<Company[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [geofences, setGeofences] = useState<Geofence[]>([])
  const [editingGeofence, setEditingGeofence] = useState<Geofence | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [loadingEditId, setLoadingEditId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  useEffect(() => {
    let isCurrent = true
    setIsFormOpen(false)
    setEditingGeofence(null)
    Promise.allSettled([
      fetchCompanies(),
      companyId ? fetchLocations(companyId) : Promise.resolve([]),
      companyId ? fetchGeofences(companyId) : Promise.resolve([]),
    ])
      .then(([companyResult, locationResult, geofenceResult]) => {
        if (!isCurrent) return
        const errors: string[] = []
        if (companyResult.status === 'fulfilled') setCompanies(companyResult.value)
        else errors.push(companyResult.reason instanceof Error ? companyResult.reason.message : 'Could not load companies.')
        if (locationResult.status === 'fulfilled') setLocations(locationResult.value)
        else errors.push(locationResult.reason instanceof Error ? locationResult.reason.message : 'Could not load locations.')
        if (geofenceResult.status === 'fulfilled') setGeofences(geofenceResult.value)
        else errors.push(geofenceResult.reason instanceof Error ? geofenceResult.reason.message : 'Could not load geofences.')
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

  const uniqueGeofenceSchema = geofenceSchema.superRefine((values, context) => {
    const duplicate = geofences.some((geofence) => (
      geofence.company_id === values.company_id
      && geofence.geofence_code === values.geofence_code
      && geofence.id !== editingGeofence?.id
    ))
    if (duplicate) {
      context.addIssue({
        code: 'custom',
        path: ['geofence_code'],
        message: 'Geofence code must be unique within the selected company.',
      })
    }
  })

  const defaultValues: GeofenceFormValues = editingGeofence
    ? {
        company_id: editingGeofence.company_id,
        location_id: editingGeofence.location_id ?? '',
        geofence_code: editingGeofence.geofence_code,
        geofence_name: editingGeofence.geofence_name,
        geofence_type: editingGeofence.geofence_type,
        shape: editingGeofence.boundary_polygon ? 'POLYGON' : 'CIRCLE',
        center_point: editingGeofence.center_point ?? '',
        radius_meters: editingGeofence.radius_meters === null ? 100 : Number(editingGeofence.radius_meters),
        boundary_polygon: editingGeofence.boundary_polygon ?? '',
        maximum_gps_accuracy_meters: editingGeofence.maximum_gps_accuracy_meters,
        effective_from: localDateTime(editingGeofence.effective_from),
        effective_to: localDateTime(editingGeofence.effective_to),
        source_type: editingGeofence.source_type,
        source_reference_id: editingGeofence.source_reference_id ?? '',
        status: editingGeofence.status,
        is_active: editingGeofence.is_active,
      }
    : {
        company_id: companyId,
        location_id: '',
        geofence_code: '',
        geofence_name: '',
        geofence_type: 'ATTENDANCE',
        shape: 'CIRCLE',
        center_point: '',
        radius_meters: 100,
        boundary_polygon: '',
        maximum_gps_accuracy_meters: 100,
        effective_from: localDateTime(new Date().toISOString()),
        effective_to: '',
        source_type: 'MANUAL',
        source_reference_id: '',
        status: 'ACTIVE',
        is_active: true,
      }

  function companyLabel(companyId: string) {
    return companies.find((company) => company.id === companyId)?.company_code ?? 'Unknown company'
  }

  function openCreate() {
    setErrorMessage('')
    setSuccessMessage('')
    setEditingGeofence(null)
    setIsFormOpen(true)
  }

  async function openEdit(geofence: Geofence) {
    setErrorMessage('')
    setSuccessMessage('')
    setLoadingEditId(geofence.id)
    try {
      const loadedGeofence = await fetchGeofence(geofence.id)
      if (!loadedGeofence) {
        setErrorMessage('This geofence could not be found.')
        return
      }
      setEditingGeofence(loadedGeofence)
      setIsFormOpen(true)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not load this geofence.')
    } finally {
      setLoadingEditId(null)
    }
  }

  function closeForm() {
    setIsFormOpen(false)
    setEditingGeofence(null)
    setErrorMessage('')
  }

  async function saveGeofence(values: GeofenceFormValues) {
    setErrorMessage('')
    setSuccessMessage('')
    const payload: GeofenceWritePayload = {
      company_id: values.company_id,
      location_id: nullable(values.location_id),
      geofence_code: values.geofence_code,
      geofence_name: values.geofence_name,
      geofence_type: values.geofence_type,
      center_point: values.shape === 'CIRCLE' ? values.center_point.trim() : null,
      radius_meters: values.shape === 'CIRCLE' && values.radius_meters !== '' ? values.radius_meters : null,
      boundary_polygon: values.shape === 'POLYGON' ? values.boundary_polygon.trim() : null,
      maximum_gps_accuracy_meters: values.maximum_gps_accuracy_meters,
      effective_from: new Date(values.effective_from).toISOString(),
      effective_to: values.effective_to ? new Date(values.effective_to).toISOString() : null,
      source_type: values.source_type,
      source_reference_id: nullable(values.source_reference_id),
      status: values.status,
      is_active: values.is_active,
    }
    try {
      const wasEditing = Boolean(editingGeofence)
      const savedGeofence = editingGeofence
        ? await updateGeofence(editingGeofence.id, payload)
        : await createGeofence(payload)
      setGeofences((current) => editingGeofence
        ? current.map((item) => item.id === savedGeofence.id ? savedGeofence : item)
        : [savedGeofence, ...current])
      closeForm()
      setSuccessMessage(`Geofence ${savedGeofence.geofence_code} ${wasEditing ? 'updated' : 'created'} successfully.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not save the geofence.')
    }
  }

  const columns: DataTableColumn<Geofence>[] = [
    {
      key: 'geofence',
      header: 'Geofence',
      value: (geofence) => `${geofence.geofence_code} ${geofence.geofence_name}`,
      render: (geofence) => (
        <div>
          <p className="font-bold text-slate-900">{geofence.geofence_code}</p>
          <p className="max-w-xs truncate text-xs text-slate-500">{geofence.geofence_name}</p>
        </div>
      ),
    },
    { key: 'company', header: 'Company', value: (geofence) => companyLabel(geofence.company_id) },
    { key: 'type', header: 'Type', value: (geofence) => geofence.geofence_type },
    {
      key: 'shape',
      header: 'Shape',
      value: (geofence) => geofence.boundary_polygon ? 'Polygon' : `Circle ${geofence.radius_meters ?? ''}`,
      render: (geofence) => geofence.boundary_polygon ? 'Polygon' : `Circle · ${geofence.radius_meters ?? '—'} m`,
    },
    {
      key: 'effective',
      header: 'Effective period',
      value: (geofence) => `${geofence.effective_from} ${geofence.effective_to ?? ''}`,
      render: (geofence) => `${formatDate(geofence.effective_from)} – ${formatDate(geofence.effective_to)}`,
    },
    {
      key: 'status',
      header: 'Status',
      value: (geofence) => geofence.status,
      render: (geofence) => (
        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${
          geofence.status === 'ACTIVE' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'
        }`}>
          {geofence.status}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      value: () => '',
      sortable: false,
      searchable: false,
      render: (geofence) => (
        <button
          type="button"
          onClick={() => openEdit(geofence)}
          disabled={loadingEditId === geofence.id}
          aria-label={`Edit ${geofence.geofence_code}`}
          className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-50"
        >
          <Pencil className="h-4 w-4" />
        </button>
      ),
    },
  ]

  const companyLocations = (companyId: string) => locations.filter((location) => location.company_id === companyId)

  return (
    <div className="min-h-svh bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="geofences" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] py-6">
        <div className="mb-3">
          <p className="text-xs text-slate-500">Configure circle and polygon boundaries for attendance and operational rules.</p>
        </div>

        {errorMessage && !isFormOpen && <p role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
        {successMessage && <p role="status" className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{successMessage}</p>}

        <DataTable
          rows={geofences}
          columns={columns}
          getRowKey={(geofence) => geofence.id}
          searchPlaceholder="Search code, name, company, or type"
          emptyMessage={isLoading ? 'Loading geofences…' : 'No geofences match your search.'}
          toolbar={(
            <button
              type="button"
              onClick={openCreate}
              disabled={isLoading || !companyId}
              className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus className="h-4 w-4" />
              New geofence
            </button>
          )}
        />
      </main>

      <FormModal<GeofenceFormValues>
        isOpen={isFormOpen}
        title={editingGeofence ? 'Edit geofence' : 'Create geofence'}
        description="Set a company boundary, effective period, and GPS accuracy rule."
        defaultValues={defaultValues}
        resetKey={editingGeofence?.id ?? 'new'}
        resolver={zodResolver(uniqueGeofenceSchema)}
        submitLabel={editingGeofence ? 'Save changes' : 'Create geofence'}
        onClose={closeForm}
        onSubmit={saveGeofence}
      >
        {({ register, watch, setValue, formState: { errors } }) => {
          const selectedCompanyId = watch('company_id')
          const shape = watch('shape')
          const radiusMeters = watch('radius_meters')
          const maximumGpsAccuracyMeters = watch('maximum_gps_accuracy_meters')
          const availableLocations = companyLocations(selectedCompanyId)
          const locationField = register('location_id')
          return (
            <div className="space-y-4">
              {errorMessage && <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
              <section>
                <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Identity</h3>
                <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                  <label className={labelClassName}>Company<select {...register('company_id')} className={inputClassName} disabled={Boolean(companyId)}><option value="">Select a company</option>{companies.filter((company) => !companyId || company.id === companyId).map((company) => <option key={company.id} value={company.id}>{company.company_code} — {company.legal_name}</option>)}</select><FieldError message={errors.company_id?.message} /></label>
                  <label className={labelClassName}>Location<select
                    {...locationField}
                    required
                    onChange={(event) => {
                      locationField.onChange(event)
                      if (editingGeofence) return

                      const location = locations.find((item) => item.id === event.target.value)
                      const latitude = location?.latitude
                      const longitude = location?.longitude
                      const hasCoordinates = latitude !== null
                        && latitude !== undefined
                        && String(latitude).trim() !== ''
                        && longitude !== null
                        && longitude !== undefined
                        && String(longitude).trim() !== ''
                        && Number.isFinite(Number(latitude))
                        && Number.isFinite(Number(longitude))
                      setValue(
                        'center_point',
                        hasCoordinates ? `POINT(${Number(longitude)} ${Number(latitude)})` : '',
                        { shouldDirty: true, shouldValidate: shape === 'CIRCLE' },
                      )
                    }}
                    className={inputClassName}
                  ><option value="">Select a location</option>{availableLocations.map((location) => <option key={location.id} value={location.id}>{location.location_code} — {location.location_name}</option>)}</select><FieldError message={errors.location_id?.message} /></label>
                  <label className={labelClassName}>Geofence code<input {...register('geofence_code', { setValueAs: (value: string) => value.toUpperCase() })} className={inputClassName} /><FieldError message={errors.geofence_code?.message} /></label>
                  <label className={labelClassName}>Name<input {...register('geofence_name')} className={inputClassName} /><FieldError message={errors.geofence_name?.message} /></label>
                  <label className={labelClassName}>Type<input {...register('geofence_type')} placeholder="ATTENDANCE, SAFETY…" className={inputClassName} /><FieldError message={errors.geofence_type?.message} /></label>
                  <label className={labelClassName}>Shape<select {...register('shape')} className={inputClassName}><option value="CIRCLE">Circle</option><option value="POLYGON">Polygon</option></select><FieldError message={errors.shape?.message} /></label>
                </div>
              </section>

              <section>
                <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Boundary</h3>
                <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2">
                  {shape === 'CIRCLE' ? (
                    <>
                      <label className={`${labelClassName} sm:col-span-2`}>Center point (WKT)<input {...register('center_point')} placeholder="POINT(121.0244 14.5547)" className={inputClassName} /><FieldError message={errors.center_point?.message} /><span className="mt-1 block text-xs font-normal text-slate-500">Coordinates use longitude, latitude order; SRID 4326 is applied by the API.</span></label>
                      <label className={labelClassName}>
                        <span className="flex items-center justify-between">
                          <span>Radius (meters)</span>
                          <output className="font-bold text-indigo-700">{radiusMeters === '' ? 'Select radius' : `${radiusMeters} m`}</output>
                        </span>
                        <input
                          type="range"
                          min="1"
                          max={maxRadiusMeters}
                          step="1"
                          aria-label="Radius in meters"
                          {...register('radius_meters', { valueAsNumber: true })}
                          className="mt-3 w-full accent-indigo-600"
                        />
                        <SliderRuler max={maxRadiusMeters} />
                        <FieldError message={errors.radius_meters?.message} />
                      </label>
                    </>
                  ) : (
                    <label className={`${labelClassName} sm:col-span-2`}>Boundary polygon (WKT)<textarea {...register('boundary_polygon')} rows={4} placeholder="POLYGON((121.02 14.55, 121.03 14.55, 121.03 14.56, 121.02 14.55))" className={inputClassName} /><FieldError message={errors.boundary_polygon?.message} /><span className="mt-1 block text-xs font-normal text-slate-500">Enter a closed polygon ring using longitude, latitude pairs.</span></label>
                  )}
                </div>
              </section>

              <section>
                <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Validity and source</h3>
                <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                  <label className={labelClassName}>Effective from<input type="datetime-local" {...register('effective_from')} className={inputClassName} /><FieldError message={errors.effective_from?.message} /></label>
                  <label className={labelClassName}>Effective to (optional)<input type="datetime-local" {...register('effective_to')} className={inputClassName} /><FieldError message={errors.effective_to?.message} /></label>
                  <label className={labelClassName}>Source type<input {...register('source_type')} placeholder="MANUAL" className={inputClassName} /><FieldError message={errors.source_type?.message} /></label>
                  <label className={labelClassName}>Source reference ID<input {...register('source_reference_id')} className={inputClassName} /><FieldError message={errors.source_reference_id?.message} /></label>
                  <label className={labelClassName}>
                    <span className="flex items-center justify-between">
                      <span>Max GPS accuracy (meters)</span>
                      <output className="font-bold text-indigo-700">{maximumGpsAccuracyMeters} m</output>
                    </span>
                    <input
                      type="range"
                      min="1"
                      max={maxGpsAccuracyMeters}
                      step="1"
                      aria-label="Maximum GPS accuracy in meters"
                      {...register('maximum_gps_accuracy_meters', { valueAsNumber: true })}
                      className="mt-3 w-full accent-indigo-600"
                    />
                    <SliderRuler max={maxGpsAccuracyMeters} />
                    <FieldError message={errors.maximum_gps_accuracy_meters?.message} />
                  </label>
                  <label className={labelClassName}>Status<input {...register('status')} className={inputClassName} /><FieldError message={errors.status?.message} /></label>
                  <label className="flex items-center gap-3 self-end rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700"><input type="checkbox" {...register('is_active')} className="h-4 w-4 accent-indigo-600" />Enabled for use</label>
                </div>
              </section>
            </div>
          )
        }}
      </FormModal>
    </div>
  )
}
