import { useEffect, useState, type FormEvent } from 'react'
import { Megaphone, Pencil, Plus, X } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { createAnnouncement, fetchManagedAnnouncements, updateAnnouncement } from '../lib/announcementApi'
import type { AnnouncementPayload, ManagedAnnouncement } from '../lib/announcementApi'
import { fetchCompanies } from '../lib/companyApi'
import type { Company } from '../types/company'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
const labelClass = 'text-sm font-semibold text-slate-700'

function localDateString(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const emptyForm: AnnouncementPayload = {
  title: '',
  body: '',
  company_id: null,
  is_active: true,
  effective_from: localDateString(new Date()),
  effective_to: null,
}

function errorText(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function formatPostedAt(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Date unavailable'
    : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

export default function Announcements({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [announcements, setAnnouncements] = useState<ManagedAnnouncement[]>([])
  const [companies, setCompanies] = useState<Company[]>([])
  const [form, setForm] = useState<AnnouncementPayload>(emptyForm)
  const [editing, setEditing] = useState<ManagedAnnouncement | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let current = true
    Promise.all([fetchManagedAnnouncements(), fetchCompanies()])
      .then(([nextAnnouncements, nextCompanies]) => {
        if (!current) return
        setAnnouncements(nextAnnouncements)
        setCompanies(nextCompanies)
      })
      .catch((cause: unknown) => {
        if (current) setError(errorText(cause, 'Could not load announcement details.'))
      })
      .finally(() => {
        if (current) setIsLoading(false)
      })
    return () => {
      current = false
    }
  }, [])

  function openCreateForm() {
    setEditing(null)
    setForm(emptyForm)
    setError('')
    setSuccess('')
    setIsFormOpen(true)
  }

  function openEditForm(announcement: ManagedAnnouncement) {
    setEditing(announcement)
    setForm({
      title: announcement.title,
      body: announcement.body,
      company_id: announcement.company_id,
      is_active: announcement.is_active,
      effective_from: announcement.effective_from,
      effective_to: announcement.effective_to,
    })
    setError('')
    setSuccess('')
    setIsFormOpen(true)
  }

  async function submitForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isSaving) return
    setError('')
    setSuccess('')
    setIsSaving(true)
    try {
      const saved = editing
        ? await updateAnnouncement(editing.id, form)
        : await createAnnouncement(form)
      const nextAnnouncements = await fetchManagedAnnouncements()
      setAnnouncements(nextAnnouncements)
      setEditing(null)
      setIsFormOpen(false)
      setForm(emptyForm)
      setSuccess(`Announcement "${saved.title}" ${editing ? 'updated' : 'created'}.`)
    } catch (cause: unknown) {
      setError(errorText(cause, 'Could not save the announcement.'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="announcements" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full space-y-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wide text-indigo-600">Company setup</p>
            <h1 className="mt-1 flex items-center gap-2 text-2xl font-bold text-slate-900">
              <Megaphone className="h-6 w-6 text-indigo-600" aria-hidden="true" />
              Announcements
            </h1>
            <p className="mt-1 text-sm text-slate-500">Create and manage messages shown to employees on their Dashboard.</p>
          </div>
          <button
            type="button"
            onClick={openCreateForm}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
          >
            <Plus className="h-4 w-4" /> New announcement
          </button>
        </header>

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{success}</p>}

        {isFormOpen && (
          <form onSubmit={(event) => void submitForm(event)} className="rounded-xl border border-indigo-100 bg-white p-5 shadow-sm sm:p-6">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-lg font-bold text-slate-900">{editing ? 'Edit announcement' : 'Create announcement'}</h2>
              <button type="button" onClick={() => setIsFormOpen(false)} aria-label="Close announcement form" className="rounded p-1 text-slate-500 hover:bg-slate-100">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <label className={labelClass}>
                Title
                <input
                  className={inputClass}
                  required
                  maxLength={200}
                  value={form.title}
                  onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
                />
              </label>
              <label className={labelClass}>
                Audience
                <select
                  className={inputClass}
                  value={form.company_id ?? ''}
                  onChange={(event) => setForm((current) => ({ ...current, company_id: event.target.value || null }))}
                >
                  <option value="">All companies</option>
                  {companies.map((company) => (
                    <option key={company.id} value={company.id}>{company.company_code} — {company.legal_name}</option>
                  ))}
                </select>
              </label>
              <label className={labelClass}>
                Effective from
                <input
                  className={inputClass}
                  type="date"
                  required
                  value={form.effective_from}
                  max={form.effective_to ?? undefined}
                  onChange={(event) => setForm((current) => ({ ...current, effective_from: event.target.value }))}
                />
              </label>
              <label className={labelClass}>
                Effective to <span className="font-normal text-slate-500">(optional)</span>
                <input
                  className={inputClass}
                  type="date"
                  min={form.effective_from}
                  value={form.effective_to ?? ''}
                  onChange={(event) => setForm((current) => ({ ...current, effective_to: event.target.value || null }))}
                />
              </label>
              <label className={`${labelClass} md:col-span-2`}>
                Message
                <textarea
                  className={`${inputClass} min-h-36 resize-y`}
                  required
                  maxLength={5000}
                  value={form.body}
                  onChange={(event) => setForm((current) => ({ ...current, body: event.target.value }))}
                />
                <span className="mt-1 block text-right text-xs font-normal text-slate-500">{form.body.length}/5000</span>
              </label>
              <label className="flex items-center gap-2 text-sm font-semibold text-slate-700 md:col-span-2">
                <input
                  type="checkbox"
                  checked={!form.is_active}
                  onChange={(event) => setForm((current) => ({ ...current, is_active: !event.target.checked }))}
                  className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                Disable this announcement
              </label>
            </div>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button type="button" onClick={() => setIsFormOpen(false)} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                Cancel
              </button>
              <button type="submit" disabled={isSaving} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-50">
                {isSaving ? 'Saving…' : editing ? 'Save changes' : 'Publish announcement'}
              </button>
            </div>
          </form>
        )}

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-5 py-4">
            <div>
              <h2 className="font-bold text-slate-900">All announcements</h2>
              <p className="mt-1 text-xs text-slate-500">Up to 1,000 most recent announcements, including inactive items.</p>
            </div>
            {!isLoading && <span className="text-sm text-slate-500">{announcements.length} total</span>}
          </div>
          {isLoading ? (
            <p role="status" className="px-5 py-10 text-center text-sm text-slate-500">Loading announcements…</p>
          ) : announcements.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <Megaphone className="mx-auto h-8 w-8 text-slate-300" aria-hidden="true" />
              <p className="mt-3 font-semibold text-slate-700">No announcements yet</p>
              <p className="mt-1 text-sm text-slate-500">Create an announcement to share an update with employees.</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {announcements.map((announcement) => {
                const company = companies.find((item) => item.id === announcement.company_id)
                return (
                  <article key={announcement.id} className="flex flex-col gap-4 px-5 py-5 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-semibold text-slate-900">{announcement.title}</h3>
                        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${announcement.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
                          {announcement.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </div>
                      <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-600">{announcement.body}</p>
                      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                        <span>{company ? `${company.company_code} — ${company.legal_name}` : announcement.company_id ? 'Company unavailable' : 'All companies'}</span>
                        <span>Effective {announcement.effective_from} – {announcement.effective_to ?? 'No end date'}</span>
                        <span>Posted {formatPostedAt(announcement.posted_at)}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => openEditForm(announcement)}
                      className="inline-flex shrink-0 items-center justify-center gap-2 self-start rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    >
                      <Pencil className="h-4 w-4" /> Edit
                    </button>
                  </article>
                )
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
