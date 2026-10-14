interface StatCardProps {
  label: string
  value: string | number
  hint?: string
  icon: string
  accent?: 'indigo' | 'rose' | 'amber' | 'emerald'
  compact?: boolean
}

const accentClasses: Record<NonNullable<StatCardProps['accent']>, { bar: string; icon: string; hint: string }> = {
  indigo: { bar: 'before:bg-indigo-500', icon: 'bg-indigo-50 text-indigo-600', hint: 'text-slate-400' },
  rose: { bar: 'before:bg-rose-500', icon: 'bg-rose-50 text-rose-600', hint: 'text-rose-600' },
  amber: { bar: 'before:bg-amber-500', icon: 'bg-amber-50 text-amber-600', hint: 'text-amber-600' },
  emerald: { bar: 'before:bg-emerald-500', icon: 'bg-emerald-50 text-emerald-600', hint: 'text-emerald-600' },
}

export default function StatCard({ label, value, hint, icon, accent = 'indigo', compact = false }: StatCardProps) {
  const styles = accentClasses[accent]

  return (
    <div
      className={`relative overflow-hidden rounded-xl border border-slate-200 bg-white p-4 shadow-sm before:absolute before:left-0 before:top-0 before:h-full before:w-1 ${styles.bar}`}
    >
      <div className="flex items-start justify-between">
        <p className={compact
          ? 'text-sm font-semibold text-slate-600'
          : 'text-[11px] font-bold uppercase tracking-wide text-slate-400'}
        >
          {label}
        </p>
        <span className={`flex items-center justify-center rounded-full ${compact ? 'h-7 w-7 text-xs' : 'h-8 w-8 text-sm'} ${styles.icon}`}>{icon}</span>
      </div>
      <p className={`mt-3 font-extrabold text-slate-900 ${compact ? 'text-xl' : 'text-2xl'}`}>{value}</p>
      {hint && <p className={`mt-1 font-medium ${compact ? 'text-[11px]' : 'text-xs'} ${styles.hint}`}>{hint}</p>}
    </div>
  )
}
