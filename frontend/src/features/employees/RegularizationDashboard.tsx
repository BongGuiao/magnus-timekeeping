import { useEffect, useRef, useState } from 'react'
import SortHeader from '../../components/common/SortHeader'
import { EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT, getManilaDate } from '../../lib/employeeRelatedApi'
import {
  dismissRegularizationNotification,
  fetchRegularizationReview,
  type RegularizationCandidate, type RegularizationReview,
} from '../../lib/regularizationApi'

type CandidateSortKey = 'employee' | 'company' | 'employment_type' | 'hire_date' | 'six_month_date' | 'days_remaining'
type Direction = 'asc' | 'desc'

export function useRegularizationDashboard(enabled: boolean) {
  const [review, setReview] = useState<RegularizationReview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dismissError, setDismissError] = useState<string | null>(null)
  const [dismissing, setDismissing] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const requestVersion = useRef(0)
  const loadedDate = useRef('')

  useEffect(() => {
    if (!enabled) return
    let active = true
    async function refresh() {
      const version = ++requestVersion.current
      try {
        const next = await fetchRegularizationReview()
        if (active && version === requestVersion.current) {
          loadedDate.current = next.as_of
          setReview(next)
          setError(null)
          setDismissError(null)
        }
      } catch (cause) {
        if (active && version === requestVersion.current) {
          setReview(null)
          setError(cause instanceof Error ? cause.message : 'Could not load regularization candidates.')
        }
      }
    }
    void refresh()
    const timer = window.setInterval(() => {
      if (loadedDate.current !== getManilaDate()) void refresh()
    }, 60_000)
    window.addEventListener('focus', refresh)
    window.addEventListener(EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT, refresh)
    return () => {
      active = false
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      window.removeEventListener(EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT, refresh)
    }
  }, [enabled, refreshKey])

  async function dismiss() {
    if (!review || dismissing) return
    setDismissing(true)
    try {
      await dismissRegularizationNotification(review.as_of)
      requestVersion.current += 1
      setReview((current) => current && current.as_of === review.as_of
        ? { ...current, notification_pending: false }
        : current)
      setDismissError(null)
    } catch (cause) {
      setDismissError(cause instanceof Error ? cause.message : 'Could not dismiss the regularization notification.')
    } finally {
      setDismissing(false)
    }
  }

  return { review, error, dismissError, dismissing, dismiss, refresh: () => setRefreshKey((key) => key + 1) }
}

type RegularizationState = ReturnType<typeof useRegularizationDashboard>

export function RegularizationNotice({ state }: { state: RegularizationState }) {
  const { review, error, dismissError, dismissing, dismiss, refresh } = state
  if (error) return (
    <div role="alert" className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">
      Regularization monitoring unavailable: {error}{' '}
      <button type="button" onClick={refresh} className="font-semibold underline">Retry</button>
    </div>
  )
  if (!review?.candidates.length || !review.notification_pending) return null
  return (
    <div className="mb-3">
      <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-indigo-50 px-3 py-2 text-sm text-indigo-900">
        <span>Daily reminder: {review.candidates.length} assignment{review.candidates.length === 1 ? '' : 's'} need regularization review.</span>
        <button type="button" onClick={() => void dismiss()} disabled={dismissing} className="font-semibold underline disabled:opacity-50">
          {dismissing ? 'Dismissing…' : 'Dismiss reminder'}
        </button>
      </div>
      {dismissError && <p role="alert" className="mt-2 text-sm text-rose-700">{dismissError}</p>}
    </div>
  )
}

export default function RegularizationDashboard({ state }: { state: RegularizationState }) {
  const { review, refresh } = state
  const [sortKey, setSortKey] = useState<CandidateSortKey>('six_month_date')
  const [direction, setDirection] = useState<Direction>('asc')
  const columns: Array<{ key: CandidateSortKey; label: string }> = [
    { key: 'employee', label: 'Employee' }, { key: 'company', label: 'Company / org unit' },
    { key: 'employment_type', label: 'Employment type' }, { key: 'hire_date', label: 'Hire date' },
    { key: 'six_month_date', label: 'Six months' }, { key: 'days_remaining', label: 'Remaining' },
  ]
  function value(candidate: RegularizationCandidate): string | number {
    if (sortKey === 'employee') return candidate.employee_name
    if (sortKey === 'company') return `${candidate.company_name} ${candidate.org_unit_name ?? ''}`
    return candidate[sortKey]
  }
  const candidates = [...(review?.candidates ?? [])].sort((a, b) => {
    const left = value(a)
    const right = value(b)
    const comparison = typeof left === 'number' && typeof right === 'number'
      ? left - right : String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: 'base' })
    return (direction === 'asc' ? comparison : -comparison)
      || a.employee_no.localeCompare(b.employee_no, undefined, { numeric: true })
      || a.assignment_id.localeCompare(b.assignment_id)
  })
  function changeSort(key: CandidateSortKey) {
    setDirection(sortKey === key && direction === 'asc' ? 'desc' : 'asc')
    setSortKey(key)
  }
  return (
    <section id="regularization-candidate-list" className="mt-4 rounded-xl border border-indigo-200 bg-white p-4 shadow-sm" aria-label="Regularization candidates">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-bold text-slate-900">Regularization candidates</h2>
        <button type="button" onClick={refresh} className="text-sm font-semibold text-indigo-700 underline">Refresh</button>
      </div>
      {review && (
        <div className="mt-3 max-h-80 overflow-auto">
          <p className="mb-2 text-xs text-slate-500">Active non-regular assignments appear from 15 days before six months until their employment type is REGULAR. Review does not change employment status.</p>
          {review.candidates.length === 0 && <p className="text-sm text-slate-500">No regularization candidates.</p>}
          <table className="w-full min-w-[700px] text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
              <tr>{columns.map((column) => <SortHeader key={column.key} label={column.label} active={sortKey === column.key}
                direction={direction} onClick={() => changeSort(column.key)} className="p-2" />)}</tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {candidates.map((candidate) => (
                <tr key={candidate.assignment_id}>
                  <td className="p-2"><span className="font-semibold">{candidate.employee_name}</span><br />{candidate.employee_no}</td>
                  <td className="p-2">{candidate.company_name}<br />{candidate.org_unit_name ?? 'No org unit'}</td>
                  <td className="p-2">{candidate.employment_type}</td>
                  <td className="p-2">{candidate.hire_date}</td>
                  <td className="p-2">{candidate.six_month_date}</td>
                  <td className="p-2">
                    {candidate.days_remaining === 0
                      ? 'Due today'
                      : `${Math.abs(candidate.days_remaining)} ${Math.abs(candidate.days_remaining) === 1 ? 'day' : 'days'}${candidate.days_remaining < 0 ? ' overdue' : ''}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
