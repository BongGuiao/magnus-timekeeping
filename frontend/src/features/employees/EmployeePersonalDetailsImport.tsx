import { useState } from 'react'
import { Download, FileUp } from 'lucide-react'
import { fetchPersonalDetailsTemplateExample, importEmployeePersonalDetails } from '../../lib/employeeApi'
import {
  parsePersonalDetailsCsv, personalDetailsCsvTemplate,
} from '../../lib/employeePersonalDetails'
import type { PersonalDetailsImportResult, PersonalDetailsImportRow } from '../../lib/employeePersonalDetails'

export default function EmployeePersonalDetailsImport() {
  const [isOpen, setIsOpen] = useState(false)
  const [rows, setRows] = useState<PersonalDetailsImportRow[]>([])
  const [results, setResults] = useState<PersonalDetailsImportResult[]>([])
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function downloadTemplate() {
    setIsBusy(true)
    setError('')
    setMessage('')
    try {
      const example = await fetchPersonalDetailsTemplateExample()
      const url = URL.createObjectURL(new Blob([personalDetailsCsvTemplate(example)], { type: 'text/csv;charset=utf-8' }))
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'employee-personal-details.csv'
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setMessage(example
        ? 'Template downloaded with the earliest saved personal-details record. It contains employee information; handle it carefully.'
        : 'No personal-details records exist yet. The template contains placeholder values instead.')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not download the template.')
    } finally {
      setIsBusy(false)
    }
  }

  async function selectFile(file: File | undefined) {
    setRows([])
    setResults([])
    setError('')
    setMessage('')
    if (!file) return
    setIsBusy(true)
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error('Maximum CSV file size is 5 MB.')
      const parsed = parsePersonalDetailsCsv(await file.text())
      const preview = await importEmployeePersonalDetails(parsed, true)
      setRows(parsed)
      setResults(preview)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not preview the upload.')
    } finally {
      setIsBusy(false)
    }
  }

  async function importRows() {
    setIsBusy(true)
    setError('')
    try {
      const imported = await importEmployeePersonalDetails(rows, false)
      setResults(imported)
      setRows([])
      setMessage('Import complete. Existing values and employee profiles were not overwritten. Conflicting fields were skipped.')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not import the upload.')
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <section className="mb-5">
      <button type="button" disabled={isBusy} onClick={() => setIsOpen((current) => !current)} aria-expanded={isOpen} className="inline-flex items-center gap-2 rounded-lg border border-indigo-200 bg-white px-4 py-2 text-sm font-semibold text-indigo-700 disabled:opacity-50">
        <FileUp className="h-4 w-4" />Import personal information
      </button>
      {isOpen && (
        <div className="mt-3 space-y-3 rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-bold text-slate-900">Import employee personal information</h2>
            <button type="button" disabled={isBusy} onClick={() => void downloadTemplate()} className="inline-flex items-center gap-2 text-xs font-semibold text-indigo-700 disabled:opacity-50"><Download className="h-4 w-4" />Download template</button>
          </div>
          <p className="text-xs leading-5 text-slate-600">
            Match existing employees by employee_no. Only empty fields are filled; blank cells leave data unchanged.
            Conflicting fields are skipped, while other empty fields in the same row can be filled.
            Format account and government ID cells as text to preserve leading zeroes.
            Address columns import text only; use the employee form to select PSGC codes.
            The template includes the earliest saved personal-details record and may contain sensitive information.
            If no record exists, replace or delete every EXAMPLE_ value in the placeholder row before importing.
            All columns except employee_no are optional. Civil status: SINGLE, MARRIED, WIDOWED, SEPARATED, DIVORCED, OTHER.
            Maximum 5 MB and 500 rows. No changes are saved until you confirm the preview.
          </p>
          <label className="block text-xs font-semibold text-slate-700">
            Personal information CSV
            <input type="file" accept=".csv,text/csv" disabled={isBusy} onChange={(event) => {
              const file = event.target.files?.[0]
              event.target.value = ''
              void selectFile(file)
            }} className="mt-2 block w-full text-xs" />
          </label>
          {isBusy && <p role="status" className="text-xs text-slate-600">Processing personal information...</p>}
          {error && <p role="alert" className="text-xs text-rose-700">{error}</p>}
          {message && <p role="status" className="text-xs text-emerald-700">{message}</p>}
          {results.length > 0 && (
            <div className="max-h-72 overflow-auto">
              <table className="w-full text-left text-xs">
                <thead><tr><th className="p-2">Employee</th><th className="p-2">Status</th><th className="p-2">Fields to fill / filled</th><th className="p-2">Conflicts (kept unchanged)</th></tr></thead>
                <tbody>{results.map((result) => (
                  <tr key={result.employee_no} className="border-t border-slate-100">
                    <td className="p-2">{result.employee_no}</td><td className="p-2">{result.status}</td>
                    <td className="p-2">{result.filled_fields.join(', ') || 'None'}</td>
                    <td className="p-2">{result.conflicting_fields.join(', ') || 'None'}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
          {rows.length > 0 && (
            <button type="button" disabled={isBusy || !results.some((result) => result.filled_fields.length)} onClick={() => void importRows()} className="rounded-md bg-indigo-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50">
              Confirm import (fill empty fields only)
            </button>
          )}
        </div>
      )}
    </section>
  )
}
