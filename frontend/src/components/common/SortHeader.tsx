import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'

export default function SortHeader({ label, active, direction, onClick, disabled, className }: {
  label: string
  active: boolean
  direction: 'asc' | 'desc'
  onClick: () => void
  disabled?: boolean
  className: string
}) {
  return (
    <th scope="col" aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'} className={className}>
      <button type="button" disabled={disabled} onClick={onClick}
        aria-label={`Sort by ${label}${active ? `, ${direction === 'asc' ? 'ascending' : 'descending'}` : ''}`}
        className="inline-flex items-center gap-1.5 rounded-sm text-left transition hover:text-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50">
        {label}
        {!active ? <ChevronsUpDown className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
          : direction === 'asc' ? <ArrowUp className="h-3.5 w-3.5 text-indigo-600" aria-hidden="true" />
            : <ArrowDown className="h-3.5 w-3.5 text-indigo-600" aria-hidden="true" />}
      </button>
    </th>
  )
}
