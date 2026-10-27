import { useEffect, useRef, useState } from 'react'
import {
  fetchPsgcBarangays,
  fetchPsgcProvinceCities,
  fetchPsgcProvinces,
  fetchPsgcRegionCities,
  fetchPsgcRegions,
} from '../../lib/psgcApi'
import type { PsgcPlace } from '../../types/psgc'

export type PsgcAddressField =
  | 'region'
  | 'province'
  | 'city'
  | 'barangay'
  | 'psgc_region_code'
  | 'psgc_province_code'
  | 'psgc_city_code'
  | 'psgc_barangay_code'

interface Props {
  region: string
  province: string
  city: string
  barangay: string
  psgcRegionCode: string | null
  psgcProvinceCode: string | null
  psgcCityCode: string | null
  psgcBarangayCode: string | null
  onChange: (field: PsgcAddressField, value: string) => void
  errors?: Partial<Record<'province' | 'city' | 'barangay', string>>
  includeBarangay?: boolean
}

const inputClassName =
  'mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
const labelClassName = 'text-xs font-semibold text-slate-700'

export default function PsgcAddressFields({
  region,
  province,
  city,
  barangay,
  psgcRegionCode,
  psgcProvinceCode,
  psgcCityCode,
  psgcBarangayCode,
  onChange,
  errors = {},
  includeBarangay = true,
}: Props) {
  const [regions, setRegions] = useState<PsgcPlace[]>([])
  const [provinces, setProvinces] = useState<PsgcPlace[]>([])
  const [cities, setCities] = useState<PsgcPlace[]>([])
  const [barangays, setBarangays] = useState<PsgcPlace[]>([])
  const [regionCode, setRegionCode] = useState(psgcRegionCode ?? (region ? 'legacy' : ''))
  const [provinceCode, setProvinceCode] = useState(psgcProvinceCode ?? (province ? 'legacy' : ''))
  const [cityCode, setCityCode] = useState(psgcCityCode ?? (city ? 'legacy' : ''))
  const [barangayCode, setBarangayCode] = useState(psgcBarangayCode ?? (barangay ? 'legacy' : ''))
  const [isLoadingRegions, setIsLoadingRegions] = useState(true)
  const [isLoadingProvinces, setIsLoadingProvinces] = useState(false)
  const [isLoadingCities, setIsLoadingCities] = useState(false)
  const [isLoadingBarangays, setIsLoadingBarangays] = useState(false)
  const [error, setError] = useState('')
  const initialPsgcCodes = useRef({
    region: psgcRegionCode,
    province: psgcProvinceCode,
    city: psgcCityCode,
    barangay: psgcBarangayCode,
  })

  useEffect(() => {
    let isCurrent = true
    const initialCodes = initialPsgcCodes.current
    async function loadReferenceData() {
      try {
        const regionOptions = await fetchPsgcRegions()
        if (!isCurrent) return
        setRegions(regionOptions)
        if (!initialCodes.region) return

        const selectedRegion = regionOptions.find((item) => item.code === initialCodes.region)
        if (!selectedRegion) return
        setRegionCode(initialCodes.region)
        const provinceOptions = await fetchPsgcProvinces(initialCodes.region)
        if (!isCurrent) return
        setProvinces(provinceOptions)

        let cityOptions: PsgcPlace[] = []
        if (initialCodes.province) {
          cityOptions = await fetchPsgcProvinceCities(initialCodes.province)
          if (!isCurrent) return
          setProvinceCode(initialCodes.province)
        } else if (provinceOptions.length === 0) {
          cityOptions = await fetchPsgcRegionCities(initialCodes.region)
          if (!isCurrent) return
        }
        setCities(cityOptions)

        if (initialCodes.city) {
          setCityCode(initialCodes.city)
          if (!includeBarangay) return
          const barangayOptions = await fetchPsgcBarangays(initialCodes.city)
          if (!isCurrent) return
          setBarangays(barangayOptions)
        }
        if (initialCodes.barangay) setBarangayCode(initialCodes.barangay)
      } catch (loadError) {
        if (isCurrent) {
          setError(loadError instanceof Error ? loadError.message : 'Could not load Philippine geographic data.')
        }
      } finally {
        if (isCurrent) setIsLoadingRegions(false)
      }
    }
    void loadReferenceData()
    return () => {
      isCurrent = false
    }
  }, [includeBarangay])

  async function changeRegion(nextRegionCode: string) {
    if (nextRegionCode === 'legacy') {
      setRegionCode('legacy')
      return
    }
    setRegionCode(nextRegionCode)
    setProvinceCode('')
    setCityCode('')
    setBarangayCode('')
    setProvinces([])
    setCities([])
    setBarangays([])
    const selectedRegion = regions.find((item) => item.code === nextRegionCode)
    onChange('region', selectedRegion?.name ?? '')
    onChange('psgc_region_code', nextRegionCode)
    onChange('province', '')
    onChange('psgc_province_code', '')
    onChange('city', '')
    onChange('psgc_city_code', '')
    onChange('barangay', '')
    onChange('psgc_barangay_code', '')
    setError('')
    if (!nextRegionCode) return

    setIsLoadingProvinces(true)
    try {
      const nextProvinces = await fetchPsgcProvinces(nextRegionCode)
      setProvinces(nextProvinces)
      if (nextProvinces.length === 0) {
        setIsLoadingCities(true)
        setCities(await fetchPsgcRegionCities(nextRegionCode))
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load locations for this region.')
    } finally {
      setIsLoadingProvinces(false)
      setIsLoadingCities(false)
    }
  }

  async function changeProvince(nextProvinceCode: string) {
    if (nextProvinceCode === 'legacy') {
      setProvinceCode('legacy')
      return
    }
    setProvinceCode(nextProvinceCode)
    setCityCode('')
    setBarangayCode('')
    setCities([])
    setBarangays([])
    const selectedProvince = provinces.find((item) => item.code === nextProvinceCode)
    onChange('province', selectedProvince?.name ?? '')
    onChange('psgc_province_code', nextProvinceCode)
    onChange('city', '')
    onChange('psgc_city_code', '')
    onChange('barangay', '')
    onChange('psgc_barangay_code', '')
    setError('')
    if (!nextProvinceCode) return

    setIsLoadingCities(true)
    try {
      setCities(await fetchPsgcProvinceCities(nextProvinceCode))
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load cities and municipalities.')
    } finally {
      setIsLoadingCities(false)
    }
  }

  async function changeCity(nextCityCode: string) {
    if (nextCityCode === 'legacy') {
      setCityCode('legacy')
      return
    }
    setCityCode(nextCityCode)
    setBarangayCode('')
    setBarangays([])
    const selectedCity = cities.find((item) => item.code === nextCityCode)
    onChange('city', selectedCity?.name ?? '')
    onChange('psgc_city_code', nextCityCode)
    onChange('barangay', '')
    onChange('psgc_barangay_code', '')
    setError('')
    if (!nextCityCode) return

    if (!includeBarangay) return
    setIsLoadingBarangays(true)
    try {
      setBarangays(await fetchPsgcBarangays(nextCityCode))
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load barangays.')
    } finally {
      setIsLoadingBarangays(false)
    }
  }

  function changeBarangay(nextBarangayCode: string) {
    if (nextBarangayCode === 'legacy') {
      setBarangayCode('legacy')
      return
    }
    setBarangayCode(nextBarangayCode)
    onChange('psgc_barangay_code', nextBarangayCode)
    onChange(
      'barangay',
      barangays.find((item) => item.code === nextBarangayCode)?.name ?? '',
    )
  }

  return (
    <>
      {error && (
        <p role="alert" className="sm:col-span-2 lg:col-span-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {error} Previously saved address text is preserved; you can also choose a new value when available.
        </p>
      )}
      <label className={labelClassName}>
        Region
        <select
          value={regionCode}
          onChange={(event) => void changeRegion(event.target.value)}
          className={inputClassName}
        >
          <option value="">{isLoadingRegions ? 'Loading regions…' : 'Select a region'}</option>
          {regionCode === 'legacy' && region && <option value="legacy">{region} (saved value)</option>}
          {regions.map((region) => (
            <option key={region.code} value={region.code}>{region.name}</option>
          ))}
        </select>
      </label>
      <label className={labelClassName}>
        Province
        <select
          value={provinceCode}
          onChange={(event) => void changeProvince(event.target.value)}
          disabled={!regionCode && provinceCode !== 'legacy'}
          className={inputClassName}
        >
          <option value="">{isLoadingProvinces ? 'Loading provinces…' : 'Select a region first'}</option>
          {provinceCode === 'legacy' && province && <option value="legacy">{province} (saved value)</option>}
          {provinces.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
        </select>
        {errors.province && <p className="mt-1 text-xs font-medium text-rose-600">{errors.province}</p>}
      </label>
      <label className={labelClassName}>
        City / Municipality
        <select
          value={cityCode}
          onChange={(event) => void changeCity(event.target.value)}
          disabled={(!regionCode && cityCode !== 'legacy') || isLoadingCities}
          className={inputClassName}
        >
          <option value="">
            {isLoadingCities ? 'Loading cities…' : regionCode ? 'Select a city or municipality' : 'Select a region first'}
          </option>
          {cityCode === 'legacy' && city && <option value="legacy">{city} (saved value)</option>}
          {cities.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
        </select>
        {errors.city && <p className="mt-1 text-xs font-medium text-rose-600">{errors.city}</p>}
      </label>
      {includeBarangay && (
        <label className={labelClassName}>
          Barangay
          <select
            value={barangayCode}
            onChange={(event) => changeBarangay(event.target.value)}
            disabled={!cityCode || cityCode === 'legacy' || isLoadingBarangays}
            className={inputClassName}
          >
            <option value="">{isLoadingBarangays ? 'Loading barangays…' : 'Select a city first'}</option>
            {barangayCode === 'legacy' && barangay && <option value="legacy">{barangay} (saved value)</option>}
            {barangays.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
          </select>
          {errors.barangay && <p className="mt-1 text-xs font-medium text-rose-600">{errors.barangay}</p>}
        </label>
      )}
    </>
  )
}
