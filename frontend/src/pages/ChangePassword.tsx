import { useState, type FormEvent } from 'react'
import { CheckCircle2, Eye, EyeOff, KeyRound, LoaderCircle } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { changePassword } from '../lib/authApi'
import { MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, validatePasswordChange } from '../lib/passwordPolicy'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const inputClass = 'mt-1.5 w-full rounded-lg border border-slate-300 bg-white py-2.5 pl-3 pr-11 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50'

function PasswordField({
  id, label, value, autoComplete, disabled, onChange,
}: {
  id: string
  label: string
  value: string
  autoComplete: 'current-password' | 'new-password'
  disabled: boolean
  onChange: (value: string) => void
}) {
  const [isVisible, setIsVisible] = useState(false)
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-semibold text-slate-700">{label}</label>
      <div className="relative">
        <input
          id={id}
          type={isVisible ? 'text' : 'password'}
          value={value}
          autoComplete={autoComplete}
          maxLength={MAX_PASSWORD_LENGTH}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          className={inputClass}
        />
        <button
          type="button"
          onClick={() => setIsVisible((visible) => !visible)}
          aria-label={`${isVisible ? 'Hide' : 'Show'} ${label.toLowerCase()}`}
          aria-pressed={isVisible}
          className="absolute inset-y-0 right-0 mt-1.5 flex w-10 items-center justify-center rounded-r-lg text-slate-400 hover:text-slate-600"
        >
          {isVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </div>
  )
}

export default function ChangePassword({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSuccess('')
    const problem = validatePasswordChange({ current, next, confirm })
    if (problem) {
      setError(problem)
      return
    }
    setError('')
    setIsSaving(true)
    try {
      const result = await changePassword({ current_password: current, new_password: next })
      setSuccess(result.message)
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Your password could not be changed.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="change-password" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] max-w-xl py-8">
        <header className="mb-6 flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
            <KeyRound className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Change password</h1>
            <p className="text-sm text-slate-500">Confirm your current password, then choose a new one.</p>
          </div>
        </header>

        <form onSubmit={submit} noValidate className="space-y-5 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          {error && (
            <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>
          )}
          {success && (
            <p role="status" className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              {success}
            </p>
          )}

          <PasswordField id="current-password" label="Current password" value={current} autoComplete="current-password" disabled={isSaving} onChange={setCurrent} />
          <PasswordField id="new-password" label="New password" value={next} autoComplete="new-password" disabled={isSaving} onChange={setNext} />
          <PasswordField id="confirm-password" label="Confirm new password" value={confirm} autoComplete="new-password" disabled={isSaving} onChange={setConfirm} />

          <ul className="list-disc space-y-1 pl-5 text-xs text-slate-500">
            <li>Use {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters.</li>
            <li>It must be different from your current password.</li>
            <li>Repeated wrong current passwords temporarily lock your account.</li>
          </ul>

          <button
            type="submit"
            disabled={isSaving}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSaving && <LoaderCircle className="h-4 w-4 animate-spin" />}
            {isSaving ? 'Saving…' : 'Change password'}
          </button>
        </form>
      </main>
    </div>
  )
}
