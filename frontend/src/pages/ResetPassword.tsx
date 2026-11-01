import { useState, type FormEvent } from 'react'
import { CheckCircle2, LoaderCircle, RotateCcw, Search } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { lookupPasswordResetTarget, resetPasswordToDefault } from '../lib/authApi'
import type { PasswordResetTarget } from '../types/auth'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

export default function ResetPassword({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [employeeCode, setEmployeeCode] = useState('')
  const [target, setTarget] = useState<PasswordResetTarget | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [isResetting, setIsResetting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const isBusy = isSearching || isResetting

  function changeEmployeeCode(value: string) {
    setEmployeeCode(value)
    // A different code must be looked up again before it can be reset.
    setTarget(null)
    setError('')
    setSuccess('')
  }

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const code = employeeCode.trim()
    setSuccess('')
    setTarget(null)
    if (!code) {
      setError('Enter an employee code.')
      return
    }
    setError('')
    setIsSearching(true)
    try {
      setTarget(await lookupPasswordResetTarget(code))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The employee code could not be found.')
    } finally {
      setIsSearching(false)
    }
  }

  async function reset() {
    if (!target) return
    if (!window.confirm(`Reset the password of ${target.employee_name} (${target.employee_code}) to the default password?`)) return
    setError('')
    setSuccess('')
    setIsResetting(true)
    try {
      const result = await resetPasswordToDefault(target.employee_code)
      setSuccess(result.message)
      setTarget(null)
      setEmployeeCode('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The password could not be reset.')
    } finally {
      setIsResetting(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="reset-password" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-6 flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
            <RotateCcw className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Reset password</h1>
            <p className="text-sm text-slate-500">Find an employee, then reset their password to the default password.</p>
          </div>
        </header>

        <div className="mx-auto max-w-xl space-y-5 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          {error && (
            <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>
          )}
          {success && (
            <p role="status" className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              {success}
            </p>
          )}

          <form onSubmit={search} noValidate>
            <label htmlFor="reset-employee-code" className="block text-sm font-semibold text-slate-700">Employee code</label>
            <div className="mt-1.5 flex gap-2">
              <input
                id="reset-employee-code"
                type="text"
                value={employeeCode}
                maxLength={50}
                autoComplete="off"
                disabled={isBusy}
                onChange={(event) => changeEmployeeCode(event.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50"
              />
              <button
                type="submit"
                disabled={isBusy}
                className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSearching ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                Search
              </button>
            </div>
          </form>

          {target && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Employee name</p>
              <p className="text-base font-bold text-slate-900">{target.employee_name}</p>
              <p className="mt-1 text-xs text-slate-500">
                {target.employee_code} · {target.is_active ? 'Active' : `Account ${target.account_status.toLowerCase()}`}
              </p>
            </div>
          )}

          <ul className="list-disc space-y-1 pl-5 text-xs text-slate-500">
            <li>The password becomes <span className="font-semibold">Default123!</span> and any temporary lockout is cleared.</li>
            <li>The employee will be asked to change it after signing in.</li>
          </ul>

          <button
            type="button"
            onClick={reset}
            disabled={!target || isBusy}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isResetting && <LoaderCircle className="h-4 w-4 animate-spin" />}
            {isResetting ? 'Resetting…' : 'Reset Password'}
          </button>
        </div>
      </main>
    </div>
  )
}
