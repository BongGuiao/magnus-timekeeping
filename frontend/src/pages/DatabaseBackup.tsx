import { useState } from 'react'
import { Database, Download, LoaderCircle } from 'lucide-react'
import TopNav, { type NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { downloadDatabaseBackup } from '../lib/databaseBackupApi'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

export default function DatabaseBackup({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  async function backup() {
    if (busy) return
    setError('')
    setSuccess('')
    setBusy(true)
    try {
      await downloadDatabaseBackup()
      setSuccess('Backup download started. Check your browser downloads and save the file to your local drive.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The database backup could not be downloaded.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="database-backup" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full px-4 py-6 sm:px-6 lg:px-8">
        <section className="rounded-xl border border-indigo-100 bg-white p-5 shadow-sm">
          <h1 className="flex items-center gap-2 text-xl font-bold text-indigo-950"><Database size={22} /> Database Backup</h1>
          <p className="mt-2 text-sm text-slate-600">Create a consistent PostgreSQL backup and download it to your computer. Only system administrators can use this feature.</p>
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-slate-600">
            <li>Includes the current database schema and data across all companies, including sensitive payroll and employee information.</li>
            <li>The .dump file is not encrypted. Store it on an encrypted drive with restricted access and keep a separate off-site copy.</li>
            <li>Does not include uploaded files, Elasticsearch logs, or server-wide PostgreSQL roles.</li>
            <li>Keep this tab open until the download starts. Generation may take up to five minutes; large databases need an operational backup job.</li>
            <li>Use pg_restore in a separate database to test recovery. This screen does not restore or change production records.</li>
          </ul>
          {error && <p role="alert" className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
          {success && <p role="status" className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">{success}</p>}
          {busy && <p role="status" className="mt-4 text-sm text-slate-600">Creating database backup. Please wait...</p>}
          <button type="button" disabled={busy} onClick={() => void backup()}
            className="mt-5 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50">
            {busy ? <LoaderCircle size={18} className="animate-spin" aria-hidden="true" /> : <Download size={18} aria-hidden="true" />}
            {busy ? 'Creating backup...' : 'Create & download backup'}
          </button>
        </section>
      </main>
    </div>
  )
}
