import { FileText } from 'lucide-react'
import NoticeTemplates from '../components/attendance/NoticeTemplates'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

export default function NoticeTemplatesPage({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  return (
    <div className="min-h-screen bg-slate-50/80">
      <TopNav employeeName={employeeName} activeView="notice-templates" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto max-w-7xl space-y-6 px-4 py-7 sm:px-6 sm:py-9 lg:px-8">
        <header className="flex items-start gap-4">
          <div className="hidden h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm sm:flex">
            <FileText className="h-6 w-6" aria-hidden="true" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-indigo-700">HR administration</p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">Notice Templates</h1>
            <p className="mt-1.5 text-sm text-slate-600">Manage template versions for each notice module.</p>
          </div>
        </header>
        <NoticeTemplates defaultOpen />
      </main>
    </div>
  )
}
