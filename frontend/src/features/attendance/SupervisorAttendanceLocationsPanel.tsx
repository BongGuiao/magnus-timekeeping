import { useEffect, useState, type FormEvent } from 'react'
import { LoaderCircle, MapPin } from 'lucide-react'
import AttendancePunchMap from './AttendancePunchMap'
import { fetchSupervisorAttendanceLocations, fetchSupervisorTeamEmployees } from '../../lib/attendanceApi'
import type { SupervisorAttendanceLocations, SupervisorTeamEmployee } from '../../lib/attendanceApi'

function manilaToday(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Manila',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
}

export default function SupervisorAttendanceLocationsPanel() {
  const [employees, setEmployees] = useState<SupervisorTeamEmployee[]>([])
  const [employeeSearch, setEmployeeSearch] = useState('')
  const [employeeCode, setEmployeeCode] = useState('')
  const [isEmployeeListOpen, setIsEmployeeListOpen] = useState(false)
  const [workDate, setWorkDate] = useState(manilaToday)
  const [result, setResult] = useState<SupervisorAttendanceLocations | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingEmployees, setIsLoadingEmployees] = useState(true)
  const [employeeLoadError, setEmployeeLoadError] = useState<string | null>(null)
  const matchingEmployees = employees.filter((employee) => {
    const query = employeeSearch.trim().toLocaleLowerCase()
    return query.length > 0
      && `${employee.employee_code} ${employee.employee_name}`.toLocaleLowerCase().includes(query)
  })

  useEffect(() => {
    let isCurrent = true
    fetchSupervisorTeamEmployees()
      .then((teamEmployees) => {
        if (isCurrent) setEmployees(teamEmployees)
      })
      .catch((loadError: unknown) => {
        if (isCurrent) {
          setEmployeeLoadError(
            loadError instanceof Error ? loadError.message : 'Could not load your team employees.',
          )
        }
      })
      .finally(() => {
        if (isCurrent) setIsLoadingEmployees(false)
      })
    return () => {
      isCurrent = false
    }
  }, [])

  async function searchLocations(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (result) {
      setResult(null)
      setError(null)
      return
    }
    const normalizedEmployeeCode = employeeCode.trim()
    if (!normalizedEmployeeCode || !workDate) return

    setIsLoading(true)
    setError(null)
    setResult(null)
    try {
      setResult(await fetchSupervisorAttendanceLocations(normalizedEmployeeCode, workDate))
    } catch (searchError) {
      setError(searchError instanceof Error ? searchError.message : 'Could not load attendance punch locations.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <h2 className="text-lg font-extrabold text-slate-900">Team punch locations</h2>
        <p className="mt-1 text-sm text-slate-500">
          View clock-in and clock-out GPS locations for an employee currently assigned to you.
        </p>
      </div>

      <form onSubmit={(event) => void searchLocations(event)} className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="relative flex-1">
          <label htmlFor="attendance-location-employee-search" className="mb-1 block text-sm font-medium text-slate-700">
            Search employee by code or name
          </label>
          <input
            id="attendance-location-employee-search"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={isEmployeeListOpen}
            aria-controls="attendance-location-employee-options"
            aria-label="Search team employee by code or name"
            value={employeeSearch}
            onFocus={() => setIsEmployeeListOpen(true)}
            onBlur={() => setIsEmployeeListOpen(false)}
            onChange={(event) => {
              const value = event.target.value
              const exactMatch = employees.find((employee) => employee.employee_code.toLocaleLowerCase() === value.trim().toLocaleLowerCase())
              setEmployeeSearch(value)
              setEmployeeCode(exactMatch?.employee_code ?? '')
              setIsEmployeeListOpen(true)
            }}
            required
            disabled={isLoadingEmployees || Boolean(employeeLoadError)}
            autoComplete="off"
            placeholder={isLoadingEmployees ? 'Loading team employees…' : 'Type an employee code or name'}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-800 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
          />
          {employeeLoadError && <p role="alert" className="mt-1 text-xs text-rose-700">{employeeLoadError}</p>}
          {isEmployeeListOpen && !isLoadingEmployees && !employeeLoadError && employeeSearch.trim() && (
            <div
              id="attendance-location-employee-options"
              role="listbox"
              aria-label="Matching team employees"
              className="absolute inset-x-0 top-full z-20 mt-1 max-h-56 overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
            >
              {matchingEmployees.length ? matchingEmployees.slice(0, 50).map((employee) => (
                <button
                  key={employee.employee_id}
                  type="button"
                  role="option"
                  aria-selected={employee.employee_code === employeeCode}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    setEmployeeSearch(`${employee.employee_name} · ${employee.employee_code}`)
                    setEmployeeCode(employee.employee_code)
                    setIsEmployeeListOpen(false)
                  }}
                  className="block w-full px-3 py-2 text-left hover:bg-indigo-50 focus:bg-indigo-50 focus:outline-none"
                >
                  <span className="block text-sm font-medium text-slate-800">{employee.employee_name}</span>
                  <span className="block text-xs text-slate-500">{employee.employee_code}</span>
                </button>
              )) : (
                <p className="px-3 py-2 text-sm text-slate-500">No team employee matches that search.</p>
              )}
            </div>
          )}
          {!isLoadingEmployees && !employeeLoadError && employees.length === 0 && (
            <p className="mt-1 text-xs text-slate-500">No active direct reports are currently assigned to you.</p>
          )}
        </div>
        <div>
          <label htmlFor="attendance-location-work-date" className="mb-1 block text-sm font-medium text-slate-700">
            Work date
          </label>
          <input
            id="attendance-location-work-date"
            type="date"
            value={workDate}
            onChange={(event) => setWorkDate(event.target.value)}
            required
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-800 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
          />
        </div>
        <button
          type="submit"
          disabled={isLoading || isLoadingEmployees || !employeeCode.trim() || !workDate}
          aria-label={isLoading ? 'Loading locations' : result ? 'Hide locations' : 'Show locations'}
          title={isLoading ? 'Loading locations' : result ? 'Hide locations' : 'Show locations'}
          className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-indigo-200 bg-white text-indigo-600 transition hover:bg-indigo-50 focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading
            ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" />
            : <MapPin className="h-5 w-5" aria-hidden="true" />}
        </button>
      </form>

      {error && (
        <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </p>
      )}
      {isLoading && <p className="mt-4 text-sm text-slate-500">Loading attendance locations…</p>}
      {result && (
        <div className="mt-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm">
            <p className="font-semibold text-slate-800">
              {result.employee_code} · {result.work_date}
            </p>
            <p className="text-slate-500">
              {result.punches.length} {result.punches.length === 1 ? 'location' : 'locations'}
              {' · '}
              <span className="text-green-700">Clock in</span>
              {' / '}
              <span className="text-blue-700">Clock out</span>
            </p>
          </div>
          {result.punches.length ? (
            <div className="lg:w-[150%]">
              <AttendancePunchMap punches={result.punches} />
            </div>
          ) : (
            <p className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
              No clock-in or clock-out GPS locations were recorded for this employee on that date.
            </p>
          )}
        </div>
      )}
    </section>
  )
}
