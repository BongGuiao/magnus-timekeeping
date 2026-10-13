import { useState } from 'react'
import type { ReactNode } from 'react'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ChevronsUpDown, Search } from 'lucide-react'

type SortDirection = 'asc' | 'desc'

export interface DataTableColumn<T> {
  key: string
  header: string
  value: (row: T) => string | number | boolean | null | undefined
  render?: (row: T) => ReactNode
  sortable?: boolean
  searchable?: boolean
  className?: string
}

interface DataTableProps<T> {
  rows: T[]
  columns: DataTableColumn<T>[]
  getRowKey: (row: T) => string
  searchPlaceholder?: string
  pageSize?: number
  emptyMessage?: string
  toolbar?: ReactNode
}

export default function DataTable<T>({
  rows,
  columns,
  getRowKey,
  searchPlaceholder = 'Search records',
  pageSize = 8,
  emptyMessage = 'No records found.',
  toolbar,
}: DataTableProps<T>) {
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const [page, setPage] = useState(1)

  const normalizedSearch = search.trim().toLowerCase()
  const searchableColumns = columns.filter((column) => column.searchable !== false)
  const filteredRows = normalizedSearch
    ? rows.filter((row) => searchableColumns.some((column) => String(column.value(row) ?? '').toLowerCase().includes(normalizedSearch)))
    : rows
  const sortedRows = [...filteredRows]
  const sortColumn = columns.find((column) => column.key === sortKey)
  if (sortColumn) {
    sortedRows.sort((left, right) => {
      const leftValue = sortColumn.value(left)
      const rightValue = sortColumn.value(right)
      const comparison = typeof leftValue === 'number' && typeof rightValue === 'number'
        ? leftValue - rightValue
        : String(leftValue ?? '').localeCompare(String(rightValue ?? ''), undefined, { numeric: true })
      return sortDirection === 'asc' ? comparison : -comparison
    })
  }

  const pageCount = Math.max(1, Math.ceil(sortedRows.length / pageSize))
  const currentPage = Math.min(page, pageCount)
  const pageRows = sortedRows.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  const firstVisibleRow = sortedRows.length === 0 ? 0 : (currentPage - 1) * pageSize + 1
  const lastVisibleRow = Math.min(currentPage * pageSize, sortedRows.length)

  function changeSort(column: DataTableColumn<T>) {
    if (column.sortable === false) return
    setPage(1)
    if (sortKey === column.key) {
      setSortDirection((direction) => direction === 'asc' ? 'desc' : 'asc')
      return
    }
    setSortKey(column.key)
    setSortDirection('asc')
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50 shadow-sm">
      <div className="flex flex-col gap-4 border-b border-slate-200 bg-slate-100 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <label className="relative block w-full sm:max-w-sm">
          <span className="sr-only">Search</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="search"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value)
              setPage(1)
            }}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            className="w-full rounded-md border border-slate-300 bg-white py-1.5 pl-9 pr-3 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
          />
        </label>
        {toolbar && <div className="flex items-center gap-2 sm:justify-end">{toolbar}</div>}
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-left text-sm">
          <thead className="bg-slate-200 text-[11px] uppercase text-slate-700">
            <tr>
              {columns.map((column) => {
                const activeSort = sortKey === column.key
                return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={activeSort ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                  className={`whitespace-nowrap border-b border-slate-300 px-4 py-2 font-bold ${column.className ?? ''}`}
                >
                  <button
                    type="button"
                    disabled={column.sortable === false}
                    onClick={() => changeSort(column)}
                    aria-label={column.sortable === false ? undefined : `Sort by ${column.header}${activeSort ? `, ${sortDirection === 'asc' ? 'ascending' : 'descending'}` : ''}`}
                    className="inline-flex items-center gap-1.5 rounded-sm text-left transition hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-default"
                  >
                    {column.header}
                    {column.sortable !== false && (
                      !activeSort
                        ? <ChevronsUpDown className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
                        : sortDirection === 'asc'
                          ? <ArrowUp className="h-3.5 w-3.5 text-indigo-600" aria-hidden="true" />
                          : <ArrowDown className="h-3.5 w-3.5 text-indigo-600" aria-hidden="true" />
                    )}
                  </button>
                </th>
              )})}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pageRows.map((row) => (
              <tr key={getRowKey(row)} className="text-slate-700 transition-colors hover:bg-indigo-50/35">
                {columns.map((column, columnIndex) => (
                  <td key={column.key} className={`whitespace-nowrap px-4 py-1.5 ${columnIndex === 0 ? 'font-medium text-slate-900' : ''} ${column.className ?? ''}`}>
                    {column.render ? column.render(row) : String(column.value(row) ?? '')}
                  </td>
                ))}
              </tr>
            ))}
            {pageRows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-14 text-center">
                  <div className="mx-auto flex max-w-sm flex-col items-center gap-3">
                    <span className="flex h-11 w-11 items-center justify-center rounded-full bg-slate-100 text-slate-400">
                      <Search className="h-5 w-5" aria-hidden="true" />
                    </span>
                    <p className="text-sm font-medium text-slate-600">{emptyMessage}</p>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-col gap-3 border-t border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <p className="text-xs font-medium text-slate-500">
          Showing {firstVisibleRow} to {lastVisibleRow} of {sortedRows.length} record{sortedRows.length === 1 ? '' : 's'}
          {normalizedSearch && ` (filtered from ${rows.length})`}
        </p>
        <nav aria-label="Table pagination" className="flex items-center justify-between gap-3 sm:justify-end">
          <button
            type="button"
            disabled={currentPage === 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
            aria-label="Previous page"
            title="Previous page"
            className="flex h-7 w-7 items-center justify-center rounded-md border border-slate-300 bg-white text-slate-600 transition hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </button>
          <span aria-live="polite" className="min-w-14 text-center text-xs font-semibold tabular-nums text-slate-600">
            {currentPage} / {pageCount}
          </span>
          <button
            type="button"
            disabled={currentPage === pageCount}
            onClick={() => setPage((value) => Math.min(pageCount, value + 1))}
            aria-label="Next page"
            title="Next page"
            className="flex h-7 w-7 items-center justify-center rounded-md border border-slate-300 bg-white text-slate-600 transition hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </button>
        </nav>
      </div>
    </div>
  )
}