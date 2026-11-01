import { useId, useRef, useState, type ReactNode } from 'react'
import { Download, Upload } from 'lucide-react'
import {
  applyEntitlementUpload,
  downloadEntitlementUploadTemplate,
  previewEntitlementUpload,
} from '../../lib/entitlementUploadApi'
import type {
  EntitlementUploadBalances,
  EntitlementUploadPreview,
  EntitlementUploadResult,
} from '../../lib/entitlementUploadApi'
import { formatLeaveBalance } from '../../lib/leaveApi'
import type { LeaveUnitType } from '../../lib/leaveApi'

interface Props {
  children: ReactNode
  onUploaded: (result: EntitlementUploadResult) => Promise<void>
}

const BALANCE_FIELDS: { key: keyof EntitlementUploadBalances; label: string }[] = [
  { key: 'opening_minutes', label: 'Opening balance' },
  { key: 'granted_minutes', label: 'Granted' },
  { key: 'accrued_minutes', label: 'Accrued' },
  { key: 'carryover_minutes', label: 'Carryover' },
  { key: 'adjustment_minutes', label: 'Adjustment' },
  { key: 'used_minutes', label: 'Used' },
  { key: 'reserved_minutes', label: 'Reserved' },
  { key: 'expired_minutes', label: 'Expired' },
  { key: 'converted_minutes', label: 'Converted' },
  { key: 'available_minutes', label: 'Available (calculated)' },
]

function errorText(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function BalanceReview({
  before, after, unit,
}: {
  before: EntitlementUploadBalances | null
  after: EntitlementUploadBalances
  unit: LeaveUnitType
}) {
  return (
    <div className="space-y-1">
      <p>
        Available: {before && <>{formatLeaveBalance(before.available_minutes, unit)} &rarr; </>}
        {formatLeaveBalance(after.available_minutes, unit)}
      </p>
      <p>
        Used: {before && <>{formatLeaveBalance(before.used_minutes, unit)} &rarr; </>}
        {formatLeaveBalance(after.used_minutes, unit)}
      </p>
      <details>
        <summary className="cursor-pointer font-semibold text-indigo-700">Review all balances</summary>
        <ul className="mt-1 space-y-0.5 text-slate-600">
          {BALANCE_FIELDS.map(({ key, label }) => (
            <li key={key}>
              {label}: {before && <>{formatLeaveBalance(before[key], unit)} &rarr; </>}
              {formatLeaveBalance(after[key], unit)}
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function PreviewTable({ preview }: { preview: EntitlementUploadPreview }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-[760px] w-full text-left text-xs">
        <thead className="bg-slate-50 uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2">Row</th>
            <th className="px-3 py-2">Employee</th>
            <th className="px-3 py-2">Leave type</th>
            <th className="px-3 py-2">Year</th>
            <th className="px-3 py-2">Action</th>
            <th className="px-3 py-2">Review</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {preview.rows.map((row) => (
            <tr key={row.row_no} className={row.errors.length ? 'bg-rose-50/60' : ''}>
              <td className="px-3 py-2 align-top">{row.row_no}</td>
              <td className="px-3 py-2 align-top">
                <p className="font-semibold text-slate-800">{row.employee_name ?? row.employee_no}</p>
                {row.employee_name && <p className="text-slate-500">{row.employee_no}</p>}
              </td>
              <td className="px-3 py-2 align-top">
                <p>{row.leave_name ?? row.leave_code}</p>
                {row.leave_name && <p className="text-slate-500">{row.leave_code}</p>}
              </td>
              <td className="px-3 py-2 align-top">{row.entitlement_year ?? 'Missing'}</td>
              <td className="px-3 py-2 align-top font-semibold">
                {row.action === 'UPDATE' ? 'Update' : row.action === 'CREATE' ? 'Create' : 'Invalid'}
              </td>
              <td className="px-3 py-2 align-top">
                {row.errors.length > 0 ? (
                  <ul className="list-disc space-y-0.5 pl-4 text-rose-700">
                    {row.errors.map((message) => <li key={message}>{message}</li>)}
                  </ul>
                ) : row.after && row.unit_type ? (
                  <BalanceReview before={row.before} after={row.after} unit={row.unit_type} />
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function EntitlementUpload({ children, onUploaded }: Props) {
  const panelId = useId()
  const fileInput = useRef<HTMLInputElement>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<EntitlementUploadPreview | null>(null)
  const [operation, setOperation] = useState<'download' | 'check' | 'apply' | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const busy = operation !== null

  async function downloadTemplate() {
    setError('')
    setOperation('download')
    try {
      const blob = await downloadEntitlementUploadTemplate()
      const url = URL.createObjectURL(blob)
      try {
        const link = document.createElement('a')
        link.href = url
        link.download = 'entitlement_upload_template.csv'
        link.click()
      } finally {
        URL.revokeObjectURL(url)
      }
    } catch (cause) {
      setError(errorText(cause, 'Could not download the entitlement template.'))
    } finally {
      setOperation(null)
    }
  }

  function chooseFile(next: File | null) {
    setFile(next)
    setPreview(null)
    setError('')
    setSuccess('')
  }

  async function checkFile() {
    if (!file) return
    setPreview(null)
    setError('')
    setSuccess('')
    setOperation('check')
    try {
      setPreview(await previewEntitlementUpload(file))
    } catch (cause) {
      setError(errorText(cause, 'Could not check the entitlement file.'))
    } finally {
      setOperation(null)
    }
  }

  async function submitFile() {
    if (!file || !preview?.is_valid || !preview.preview_token) return
    setError('')
    setSuccess('')
    setOperation('apply')
    try {
      const result = await applyEntitlementUpload(file, preview.preview_token)
      setPreview(null)
      setFile(null)
      if (fileInput.current) fileInput.current.value = ''
      setSuccess(`Upload completed: ${result.created} created and ${result.updated} updated.`)
      try {
        await onUploaded(result)
      } catch (cause) {
        setError(`Upload completed, but the displayed balances could not be refreshed: ${errorText(cause, 'Refresh the page.')}`)
      }
    } catch (cause) {
      setPreview(null)
      setError(errorText(cause, 'Could not confirm the entitlement upload. Check the file again before retrying.'))
    } finally {
      setOperation(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>{children}</div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setIsOpen((current) => !current)}
            disabled={busy}
            aria-expanded={isOpen}
            aria-controls={panelId}
            className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <Upload className="h-3.5 w-3.5" aria-hidden="true" /> Upload entitlements
          </button>
          <button
            type="button"
            onClick={() => void downloadTemplate()}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" /> Download template
          </button>
        </div>
      </div>
      {error && <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
      {success && <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{success}</p>}
      {isOpen && (
        <section id={panelId} aria-label="Upload entitlements" className="space-y-3 rounded-lg border border-slate-200 bg-slate-50/60 p-3">
          <div className="space-y-1 text-xs text-slate-600">
            <p>Upload up to 1,000 rows for multiple employees (CSV, maximum 1 MB). Every column is required; enter 0 for an empty balance.</p>
            <p>Use each leave type&apos;s configured unit: days, hours, or minutes. One day is 8 hours. Keep employee numbers as text to preserve leading zeroes.</p>
            <p className="font-semibold text-amber-800">Matching employee, active company leave type, and year will be replaced, including used and reserved balances. Existing leave ledger entries are not changed.</p>
            <p>The entire file is rejected if any row is invalid. Review the changes before applying them.</p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs font-semibold text-slate-700">
              Entitlement CSV file
              <input
                ref={fileInput}
                type="file"
                accept=".csv,text/csv"
                disabled={busy}
                onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
                className="mt-1 block max-w-full text-xs font-normal file:mr-3 file:rounded-md file:border-0 file:bg-slate-200 file:px-3 file:py-2 file:text-xs file:font-semibold"
              />
            </label>
            <button type="button" onClick={() => void checkFile()} disabled={!file || busy} className="rounded-md border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50">
              {operation === 'check' ? 'Checking...' : 'Check file'}
            </button>
            <button type="button" onClick={() => void submitFile()} disabled={!file || !preview?.is_valid || !preview.preview_token || busy} className="rounded-md bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
              {operation === 'apply' ? 'Applying...' : 'Apply entitlements'}
            </button>
          </div>
          {preview && (
            <div className="space-y-3">
              <p role="status" className={`text-xs font-semibold ${preview.is_valid ? 'text-emerald-700' : 'text-rose-700'}`}>
                {preview.is_valid
                  ? `All ${preview.rows.length} row(s) are valid. Review the changes, then apply them.`
                  : `${preview.error_count} error(s) found. Correct the file and check it again.`}
              </p>
              {preview.file_errors.length > 0 && (
                <ul className="list-disc rounded-lg border border-rose-200 bg-rose-50 py-2 pl-8 pr-3 text-xs text-rose-700">
                  {preview.file_errors.map((message) => <li key={message}>{message}</li>)}
                </ul>
              )}
              {preview.rows.length > 0 && <PreviewTable preview={preview} />}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
