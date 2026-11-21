import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ChevronDown, FileText, ShieldCheck, Upload } from 'lucide-react'
import {
  activateNoticeTemplate,
  getNoticeTemplate,
  listNoticeTemplates,
  uploadNoticeTemplate,
  type NoticeTemplate,
  type NoticeTemplateDetail,
  type NoticeTemplateModule,
} from '../../lib/noticeTemplateApi'
import { formatManilaDateTime } from '../../lib/officialBusinessApi'

const moduleLabels: Record<NoticeTemplateModule, string> = {
  TARDINESS: 'Tardiness',
  RETURN_TO_WORK: 'Return to Work',
}
const commonFields = ['employee_name', 'employee_no', 'employee_position', 'notice_date', 'signatory_name', 'signatory_title', 'signature']
const moduleFields: Record<NoticeTemplateModule, string[]> = {
  TARDINESS: ['period_start', 'period_end', 'late_dates', 'attendance_records'],
  RETURN_TO_WORK: ['employee_address', 'salutation', 'last_attendance_date', 'consecutive_absence_days', 'expected_return_date', 'signatory_contact'],
}

function previewDocument(content: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><style>body{font:15px/1.6 system-ui,sans-serif;color:#1e293b;margin:24px;overflow-wrap:anywhere}table{border-collapse:collapse;max-width:100%}td,th{border:1px solid #cbd5e1;padding:6px}</style></head><body>${content}</body></html>`
}

export default function NoticeTemplates({ defaultOpen = false }: { defaultOpen?: boolean } = {}) {
  const [open, setOpen] = useState(defaultOpen)
  const [templates, setTemplates] = useState<NoticeTemplate[]>([])
  const [selected, setSelected] = useState<NoticeTemplateDetail | null>(null)
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(defaultOpen)
  const [saving, setSaving] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [error, setError] = useState('')
  const [listError, setListError] = useState('')
  const [message, setMessage] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [module, setModule] = useState<NoticeTemplateModule>('TARDINESS')
  const fileInput = useRef<HTMLInputElement>(null)
  const previewRequest = useRef(0)

  useEffect(() => {
    if (!open) return
    let active = true
    listNoticeTemplates()
      .then((result) => {
        if (!active) return
        setTemplates(result)
        setSelected((current) => {
          if (!current) return null
          const matching = result.find((item) => item.id === current.id)
          return matching ? { ...current, is_active: matching.is_active } : null
        })
      })
      .catch((cause: unknown) => {
        if (active) setListError(cause instanceof Error ? cause.message : 'Could not load notice templates.')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [open, refreshKey])

  function refreshTemplates() {
    setLoading(true)
    setListError('')
    setRefreshKey((current) => current + 1)
  }

  function toggleOpen() {
    if (!open) {
      setLoading(true)
      setListError('')
    }
    setOpen((value) => !value)
  }

  async function preview(id: string) {
    const request = ++previewRequest.current
    setPreviewLoading(true)
    setSelected(null)
    setError('')
    setMessage('')
    try {
      const result = await getNoticeTemplate(id)
      if (request === previewRequest.current) setSelected(result)
    } catch (cause) {
      if (request === previewRequest.current) setError(cause instanceof Error ? cause.message : 'Could not load the preview.')
    } finally {
      if (request === previewRequest.current) setPreviewLoading(false)
    }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || saving) return
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const result = await uploadNoticeTemplate(name.trim(), module, file)
      previewRequest.current++
      setPreviewLoading(false)
      setSelected(result)
      setName('')
      setFile(null)
      if (fileInput.current) fileInput.current.value = ''
      setMessage('Draft uploaded. Review the sanitized preview before activating it.')
      refreshTemplates()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not upload the template.')
    } finally {
      setSaving(false)
    }
  }

  async function activate() {
    if (!selected || saving || selected.is_active) return
    const moduleLabel = moduleLabels[selected.module]
    if (!window.confirm(`Activate this version for ${moduleLabel}? It will replace the currently active version for that module.`)) return
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const result = await activateNoticeTemplate(selected.id)
      setSelected(result)
      setMessage(`Template activated for ${moduleLabel}. No notice has been issued.`)
      refreshTemplates()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not activate the template.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <button type="button" onClick={toggleOpen} aria-expanded={open} aria-controls="notice-template-panel"
        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-indigo-600">
        <span className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600"><FileText className="h-5 w-5" aria-hidden="true" /></span>
          <span><span className="block font-semibold text-slate-900">Notice templates</span><span className="block text-xs text-slate-500">Upload, preview and activate templates by module</span></span>
        </span>
        <ChevronDown className={`h-5 w-5 shrink-0 text-slate-500 transition ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {open && (
        <div id="notice-template-panel" className="space-y-5 border-t border-slate-100 p-5">
          <div className="flex gap-2 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-900">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <p>HTML is sanitized: scripts, styles, links and images are removed. Check the preview carefully before activation. Each upload creates a separate version; it does not issue a notice.</p>
          </div>
          <form onSubmit={(event) => void upload(event)} className="grid gap-3 lg:grid-cols-[1fr_180px_1fr_auto] lg:items-end">
            <label className="block text-sm font-medium text-slate-700">Template name
              <input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Notice to Explain"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-2 focus:outline-indigo-100" />
            </label>
            <label className="block text-sm font-medium text-slate-700">Module
              <select value={module} disabled={saving} onChange={(event) => {
                if (event.target.value === 'TARDINESS' || event.target.value === 'RETURN_TO_WORK') setModule(event.target.value)
              }} className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
                <option value="TARDINESS">Tardiness</option>
                <option value="RETURN_TO_WORK">Return to Work</option>
              </select>
            </label>
            <label className="block text-sm font-medium text-slate-700">HTML file
              <input ref={fileInput} required type="file" accept=".html,.htm,text/html" onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm file:mr-2 file:rounded file:border-0 file:bg-slate-100 file:px-2 file:py-1 file:text-slate-700" />
            </label>
            <button type="submit" disabled={saving || !name.trim() || !file} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">
              <Upload className="h-4 w-4" aria-hidden="true" />{saving ? 'Saving...' : 'Upload draft'}
            </button>
          </form>
          <details className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
            <summary className="cursor-pointer font-semibold text-slate-700">Available template fields</summary>
            <p className="mt-2">Use these placeholders in the HTML. <code>{'{{signature}}'}</code> is required; the HR head’s signature is added at issuance.</p>
            <p className="mt-2 break-words leading-6">{[...commonFields, ...moduleFields[module]].map((field) => <code key={field} className="mr-2 inline-block">{`{{${field}}}`}</code>)}</p>
            {module === 'TARDINESS' && <p className="mt-2">Use <code>{'{{attendance_records}}'}</code> for dated arrival and scheduled-start details.</p>}
          </details>
          {module === 'RETURN_TO_WORK' && <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">Return-to-work issuance and automatic absence detection are not implemented. Have HR or legal review the wording before using it.</p>}
          {error && <p role="alert" className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</p>}
          {message && <p role="status" className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{message}</p>}
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
            <div>
              <h3 className="text-sm font-bold text-slate-800">Saved versions</h3>
              {loading && <p role="status" className="mt-2 text-sm text-slate-500">Loading templates...</p>}
              {listError && <p role="alert" className="mt-2 text-sm text-rose-700">{listError} <button type="button" onClick={refreshTemplates} className="font-semibold underline">Retry</button></p>}
              {!loading && !listError && templates.length === 0 && <p className="mt-2 text-sm text-slate-500">No templates uploaded yet.</p>}
              <ul className="mt-2 space-y-2">
                {templates.map((template) => (
                  <li key={template.id}>
                    <button type="button" disabled={saving} onClick={() => void preview(template.id)}
                      className={`w-full rounded-lg border p-3 text-left hover:border-indigo-300 disabled:opacity-50 ${selected?.id === template.id ? 'border-indigo-400 bg-indigo-50' : 'border-slate-200'}`}>
                      <span className="flex items-center justify-between gap-2"><span className="break-words font-semibold text-slate-800">{template.name}</span><span className={`shrink-0 rounded-full px-2 py-1 text-xs font-semibold ${template.is_active ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'}`}>{template.is_active ? 'Active' : 'Inactive'}</span></span>
                      <span className="mt-1 block text-xs text-slate-500">{formatManilaDateTime(template.created_at)} · {moduleLabels[template.module]}</span>
                      <span className="mt-1 block break-all text-xs text-slate-400">Version {template.id}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-bold text-slate-800">Sanitized preview</h3>
                {selected && !selected.is_active && <button type="button" disabled={saving || previewLoading} onClick={() => void activate()} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">Activate version</button>}
              </div>
              {selected && <p className="mt-2 break-all text-xs text-slate-500">{selected.name} · {moduleLabels[selected.module]} · Version {selected.id}</p>}
              {selected?.module === 'RETURN_TO_WORK' && module !== 'RETURN_TO_WORK' && (
                <p className="mt-2 text-sm text-amber-800">Return-to-work wording requires HR or legal review before use.</p>
              )}
              {previewLoading ? <p role="status" className="mt-2 text-sm text-slate-500">Loading preview...</p> : selected ? (
                <iframe title={`Sanitized preview of ${selected.name}`} sandbox="" srcDoc={previewDocument(selected.sanitized_html)}
                  className="mt-2 h-96 w-full rounded-lg border border-slate-200 bg-white" />
              ) : <p className="mt-2 rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500">Select a saved version to review its content.</p>}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
