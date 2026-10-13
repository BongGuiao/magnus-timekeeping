import { useEffect, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { MapPin, Pencil, Plus } from 'lucide-react'
import { z } from 'zod'
import DataTable from '../components/common/DataTable'
import type { DataTableColumn } from '../components/common/DataTable'
import FormModal from '../components/common/FormModal'
import PsgcAddressFields from '../components/common/PsgcAddressFields'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { useCompanySetupSelection } from '../hooks/useCompanySetupSelection'
import { fetchCompanies } from '../lib/companyApi'
import { createLocation, fetchLocation, fetchLocations, updateLocation } from '../lib/locationApi'
import type { LocationWritePayload } from '../lib/locationApi'
import type { Company } from '../types/company'
import type { Location, LocationType } from '../types/location'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const locationTypes = [
  'OFFICE',
  'WAREHOUSE',
  'DISPATCH',
  'CUSTOMER',
  'FIELD',
  'FLEET_YARD',
  'OTHER',
] as const satisfies readonly LocationType[]

const locationSchema = z.object({
  company_id: z.string().min(1, 'Company is required.'),
  location_code: z.string().trim().min(1, 'Location code is required.').max(30)
    .regex(/^[A-Z0-9_-]+$/, 'Use uppercase letters, numbers, hyphens, or underscores.'),
  location_name: z.string().trim().min(1, 'Location name is required.').max(150),
  location_type: z.enum(locationTypes),
  address_line1: z.string().trim().max(200),
  region: z.string().trim().max(100),
  psgc_region_code: z.string().regex(/^$|^\d{9}$/),
  psgc_province_code: z.string().regex(/^$|^\d{9}$/),
  psgc_city_code: z.string().regex(/^$|^\d{9}$/),
  psgc_barangay_code: z.string().regex(/^$|^\d{9}$/),
  barangay: z.string().trim().max(100),
  city: z.string().trim().max(100),
  province: z.string().trim().max(100),
  postal_code: z.string().trim().max(20),
  latitude: z.union([z.literal(''), z.number().min(-90).max(90)]),
  longitude: z.union([z.literal(''), z.number().min(-180).max(180)]),
  timezone: z.string().trim().min(1, 'Timezone is required.').max(50),
  status: z.enum(['ACTIVE', 'INACTIVE']),
  is_active: z.boolean(),
})

type LocationFormValues = z.infer<typeof locationSchema>

const emptyLocation: LocationFormValues = {
  company_id: '',
  location_code: '',
  location_name: '',
  location_type: 'OFFICE',
  address_line1: '',
  region: '',
  psgc_region_code: '',
  psgc_province_code: '',
  psgc_city_code: '',
  psgc_barangay_code: '',
  barangay: '',
  city: '',
  province: '',
  postal_code: '',
  latitude: '',
  longitude: '',
  timezone: 'Asia/Manila',
  status: 'ACTIVE',
  is_active: true,
}

const inputClassName = 'mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
const labelClassName = 'text-xs font-semibold text-slate-700'

function nullable(value: string) {
  return value || null
}

function FieldError({ message }: { message?: string }) {
  return message ? <p className="mt-1 text-xs font-medium text-rose-600">{message}</p> : null
}

function formatUpdatedAt(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value))
}

function getCoordinates(location: Location) {
  const latitude = Number(location.latitude)
  const longitude = Number(location.longitude)
  if (
    location.latitude === null
    || location.longitude === null
    || !Number.isFinite(latitude)
    || !Number.isFinite(longitude)
    || latitude < -90
    || latitude > 90
    || longitude < -180
    || longitude > 180
  ) {
    return null
  }
  return { latitude, longitude }
}

export default function Locations({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const { companyId } = useCompanySetupSelection()
  const [companies, setCompanies] = useState<Company[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [selectedMapLocationId, setSelectedMapLocationId] = useState('')
  const [isMapVisible, setIsMapVisible] = useState(false)
  const [editingLocation, setEditingLocation] = useState<Location | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [loadingEditId, setLoadingEditId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  useEffect(() => {
    let isCurrent = true
    setIsFormOpen(false)
    setEditingLocation(null)
    Promise.allSettled([
      fetchCompanies(),
      companyId ? fetchLocations(companyId) : Promise.resolve([]),
    ])
      .then(([companiesResult, locationsResult]) => {
        if (!isCurrent) return
        const errors: string[] = []
        if (companiesResult.status === 'fulfilled') setCompanies(companiesResult.value)
        else errors.push(companiesResult.reason instanceof Error ? companiesResult.reason.message : 'Could not load companies.')
        if (locationsResult.status === 'fulfilled') setLocations(locationsResult.value)
        else errors.push(locationsResult.reason instanceof Error ? locationsResult.reason.message : 'Could not load locations.')
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

  const uniqueLocationSchema = locationSchema.superRefine((values, context) => {
    const duplicate = locations.some((location) => (
      location.company_id === values.company_id
      && location.location_code === values.location_code
      && location.id !== editingLocation?.id
    ))
    if (duplicate) {
      context.addIssue({
        code: 'custom',
        path: ['location_code'],
        message: 'Location code must be unique within the selected company.',
      })
    }
    if ((values.latitude === '') !== (values.longitude === '')) {
      context.addIssue({
        code: 'custom',
        path: [values.latitude === '' ? 'latitude' : 'longitude'],
        message: 'Enter both coordinates or leave both blank.',
      })
    }
  })

  const defaultValues: LocationFormValues = editingLocation
    ? {
        company_id: editingLocation.company_id,
        location_code: editingLocation.location_code,
        location_name: editingLocation.location_name,
        location_type: editingLocation.location_type,
        address_line1: editingLocation.address_line1 ?? '',
        region: editingLocation.region ?? '',
        psgc_region_code: editingLocation.psgc_region_code ?? '',
        psgc_province_code: editingLocation.psgc_province_code ?? '',
        psgc_city_code: editingLocation.psgc_city_code ?? '',
        psgc_barangay_code: editingLocation.psgc_barangay_code ?? '',
        barangay: editingLocation.barangay ?? '',
        city: editingLocation.city ?? '',
        province: editingLocation.province ?? '',
        postal_code: editingLocation.postal_code ?? '',
        latitude: editingLocation.latitude === null ? '' : Number(editingLocation.latitude),
        longitude: editingLocation.longitude === null ? '' : Number(editingLocation.longitude),
        timezone: editingLocation.timezone,
        status: editingLocation.status,
        is_active: editingLocation.is_active,
      }
    : { ...emptyLocation, company_id: companyId }

  const mappedLocations = locations.filter((location) => getCoordinates(location) !== null)
  const selectedMapLocation = mappedLocations.find((location) => location.id === selectedMapLocationId)
    ?? mappedLocations[0]
  const selectedCoordinates = selectedMapLocation ? getCoordinates(selectedMapLocation) : null
  const mapUrl = selectedMapLocation && selectedCoordinates
    ? (() => {
        const { latitude, longitude } = selectedCoordinates
        const params = new URLSearchParams({
          bbox: [
            Math.max(-180, longitude - 0.01),
            Math.max(-90, latitude - 0.01),
            Math.min(180, longitude + 0.01),
            Math.min(90, latitude + 0.01),
          ].join(','),
          layer: 'mapnik',
          marker: `${latitude},${longitude}`,
        })
        return `https://www.openstreetmap.org/export/embed.html?${params.toString()}`
      })()
    : null

  function companyLabel(companyId: string) {
    const company = companies.find((company) => company.id === companyId)
    return company ? `${company.company_code} — ${company.legal_name}` : 'Unknown company'
  }

  function openCreate() {
    setErrorMessage('')
    setSuccessMessage('')
    setEditingLocation(null)
    setIsFormOpen(true)
  }

  async function openEdit(location: Location) {
    setErrorMessage('')
    setSuccessMessage('')
    setLoadingEditId(location.id)
    try {
      const loadedLocation = await fetchLocation(location.id)
      if (!loadedLocation) {
        setErrorMessage('This location could not be found.')
        return
      }
      setEditingLocation(loadedLocation)
      setIsFormOpen(true)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not load this location.')
    } finally {
      setLoadingEditId(null)
    }
  }

  function closeForm() {
    setIsFormOpen(false)
    setEditingLocation(null)
    setErrorMessage('')
  }

  async function saveLocation(values: LocationFormValues) {
    setErrorMessage('')
    setSuccessMessage('')
    const latitude = values.latitude === '' ? null : values.latitude
    const longitude = values.longitude === '' ? null : values.longitude
    const payload: LocationWritePayload = {
      company_id: values.company_id,
      location_code: values.location_code,
      location_name: values.location_name,
      location_type: values.location_type,
      address_line1: nullable(values.address_line1),
      region: nullable(values.region),
      psgc_region_code: nullable(values.psgc_region_code),
      psgc_province_code: nullable(values.psgc_province_code),
      psgc_city_code: nullable(values.psgc_city_code),
      psgc_barangay_code: nullable(values.psgc_barangay_code),
      barangay: nullable(values.barangay),
      city: nullable(values.city),
      province: nullable(values.province),
      postal_code: nullable(values.postal_code),
      latitude,
      longitude,
      geo_point: latitude === null || longitude === null ? null : `SRID=4326;POINT(${longitude} ${latitude})`,
      timezone: values.timezone,
      status: values.status,
      is_active: values.is_active,
    }
    try {
      const wasEditing = Boolean(editingLocation)
      const savedLocation = editingLocation
        ? await updateLocation(editingLocation.id, payload)
        : await createLocation(payload)
      setLocations((current) => editingLocation
        ? current.map((item) => item.id === savedLocation.id ? savedLocation : item)
        : [savedLocation, ...current])
      closeForm()
      setSuccessMessage(`Location ${savedLocation.location_code} ${wasEditing ? 'updated' : 'created'} successfully.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not save the location.')
    }
  }

  const columns: DataTableColumn<Location>[] = [
    {
      key: 'location',
      header: 'Location',
      value: (location) => `${location.location_code} ${location.location_name}`,
      render: (location) => (
        <div>
          <p className="font-bold text-slate-900">{location.location_code}</p>
          <p className="max-w-xs truncate text-xs text-slate-500">{location.location_name}</p>
        </div>
      ),
    },
    { key: 'company', header: 'Company', value: (location) => companyLabel(location.company_id) },
    { key: 'type', header: 'Type', value: (location) => location.location_type },
    { key: 'city', header: 'City', value: (location) => location.city ?? '—' },
    {
      key: 'status',
      header: 'Status',
      value: (location) => location.status,
      render: (location) => (
        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${
          location.status === 'ACTIVE' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'
        }`}>
          {location.status}
        </span>
      ),
    },
    { key: 'updated', header: 'Updated', value: (location) => location.updated_at, render: (location) => formatUpdatedAt(location.updated_at) },
    {
      key: 'actions',
      header: '',
      value: () => '',
      sortable: false,
      searchable: false,
      render: (location) => (
        <div className="flex items-center">
          <button
            type="button"
            onClick={() => openEdit(location)}
            disabled={loadingEditId === location.id}
            aria-label={`Edit ${location.location_code}`}
            className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-50"
          >
            <Pencil className="h-4 w-4" />
          </button>
          {getCoordinates(location) && (
            <button
              type="button"
              onClick={() => {
                const isSelectedMapVisible = isMapVisible && selectedMapLocationId === location.id
                setSelectedMapLocationId(location.id)
                setIsMapVisible(!isSelectedMapVisible)
              }}
              aria-label={`${isMapVisible && selectedMapLocationId === location.id ? 'Hide' : 'View'} map for ${location.location_code}`}
              aria-expanded={isMapVisible && selectedMapLocationId === location.id}
              aria-controls="company-location-map"
              title="View map"
              className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700"
            >
              <MapPin className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="min-h-svh bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="locations" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] py-6">
        <div className="mb-3">
          <p className="text-xs text-slate-500">Manage company sites, addresses, coordinates, and location status.</p>
        </div>

        {errorMessage && !isFormOpen && <p role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
        {successMessage && <p role="status" className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{successMessage}</p>}

        {isMapVisible && <section id="company-location-map" aria-labelledby="location-map-heading" className="mb-5 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-col gap-3 border-b border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 id="location-map-heading" className="font-bold text-slate-900">Location map</h2>
              <p className="mt-1 text-xs text-slate-500">View saved locations with coordinates on OpenStreetMap.</p>
            </div>
            {mappedLocations.length > 0 && (
              <label className="text-xs font-semibold text-slate-700">
                Select location
                <select
                  value={selectedMapLocation?.id ?? ''}
                  onChange={(event) => setSelectedMapLocationId(event.target.value)}
                  className={`${inputClassName} mt-1 min-w-64`}
                >
                  {mappedLocations.map((location) => (
                    <option key={location.id} value={location.id}>
                      {location.location_code} — {location.location_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {mapUrl && selectedMapLocation && selectedCoordinates ? (
            <div>
              <iframe
                title={`Map showing ${selectedMapLocation.location_name}`}
                src={mapUrl}
                loading="lazy"
                className="h-72 w-full border-0"
              />
              <div className="flex flex-col gap-2 border-t border-slate-100 px-4 py-3 text-xs text-slate-600 sm:flex-row sm:items-center sm:justify-between">
                <span>
                  {companyLabel(selectedMapLocation.company_id)} · {selectedCoordinates.latitude}, {selectedCoordinates.longitude}
                </span>
                <a
                  href={`https://www.openstreetmap.org/?mlat=${selectedCoordinates.latitude}&mlon=${selectedCoordinates.longitude}#map=16/${selectedCoordinates.latitude}/${selectedCoordinates.longitude}`}
                  target="_blank"
                  rel="noreferrer"
                  className="font-semibold text-indigo-600 hover:text-indigo-700"
                >
                  Open in OpenStreetMap
                </a>
              </div>
            </div>
          ) : (
            <div className="flex min-h-52 flex-col items-center justify-center gap-2 px-4 text-center">
              <MapPin className="h-7 w-7 text-slate-400" aria-hidden="true" />
              <p className="text-sm font-semibold text-slate-700">No mapped locations yet</p>
              <p className="max-w-md text-xs text-slate-500">
                Add both latitude and longitude when creating or editing a location to display it here.
              </p>
            </div>
          )}
        </section>}

        <DataTable
          rows={locations}
          columns={columns}
          getRowKey={(location) => location.id}
          searchPlaceholder="Search code, name, company, or city"
          emptyMessage={isLoading ? 'Loading locations…' : 'No locations match your search.'}
          toolbar={(
            <button
              type="button"
              onClick={openCreate}
              disabled={isLoading || !companyId}
              className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus className="h-4 w-4" />
              New location
            </button>
          )}
        />
      </main>

      <FormModal<LocationFormValues>
        isOpen={isFormOpen}
        title={editingLocation ? 'Edit location' : 'Create location'}
        description="Maintain a company location and its optional map coordinates."
        defaultValues={defaultValues}
        resetKey={editingLocation?.id ?? 'new'}
        resolver={zodResolver(uniqueLocationSchema)}
        submitLabel={editingLocation ? 'Save changes' : 'Create location'}
        onClose={closeForm}
        onSubmit={saveLocation}
      >
        {({ register, watch, setValue, formState: { errors } }) => (
          <div className="space-y-4">
            {errorMessage && <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
            <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Identity</h3>
              <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                <label className={labelClassName}>Company<select {...register('company_id')} className={inputClassName} disabled={Boolean(companyId)}><option value="">Select a company</option>{companies.filter((company) => !companyId || company.id === companyId).map((company) => <option key={company.id} value={company.id}>{company.company_code} — {company.legal_name}</option>)}</select><FieldError message={errors.company_id?.message} /></label>
                <label className={labelClassName}>Location code<input {...register('location_code', { setValueAs: (value: string) => value.toUpperCase() })} className={inputClassName} /><FieldError message={errors.location_code?.message} /></label>
                <label className={labelClassName}>Location name<input {...register('location_name')} className={inputClassName} /><FieldError message={errors.location_name?.message} /></label>
                <label className={labelClassName}>Type<select {...register('location_type')} className={inputClassName}>{locationTypes.map((type) => <option key={type} value={type}>{type.replace('_', ' ')}</option>)}</select><FieldError message={errors.location_type?.message} /></label>
              </div>
            </section>

            <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Address and coordinates</h3>
              <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                <label className={`${labelClassName} sm:col-span-2 lg:col-span-1`}>Address<input {...register('address_line1')} className={inputClassName} /><FieldError message={errors.address_line1?.message} /></label>
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
                <label className={labelClassName}>Latitude<input type="number" step="any" {...register('latitude', { setValueAs: (value: string) => value === '' ? '' : Number(value) })} className={inputClassName} /><FieldError message={errors.latitude?.message} /></label>
                <label className={labelClassName}>Longitude<input type="number" step="any" {...register('longitude', { setValueAs: (value: string) => value === '' ? '' : Number(value) })} className={inputClassName} /><FieldError message={errors.longitude?.message} /></label>
              </div>
            </section>

            <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Settings</h3>
              <div className="mt-2 grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                <label className={labelClassName}>Timezone<input {...register('timezone')} className={inputClassName} /><FieldError message={errors.timezone?.message} /></label>
                <label className={labelClassName}>Status<select {...register('status')} className={inputClassName}><option value="ACTIVE">Active</option><option value="INACTIVE">Inactive</option></select><FieldError message={errors.status?.message} /></label>
                <label className="flex items-center gap-3 self-end rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700"><input type="checkbox" {...register('is_active')} className="h-4 w-4 accent-indigo-600" />Enabled for use</label>
              </div>
              <p className="mt-2 text-xs text-slate-500">Coordinates create a PostGIS point in longitude, latitude order (SRID 4326).</p>
            </section>
          </div>
        )}
      </FormModal>
    </div>
  )
}
