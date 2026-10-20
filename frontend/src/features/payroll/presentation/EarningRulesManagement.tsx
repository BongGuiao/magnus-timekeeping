import { useEffect, useState } from 'react'
import { Check, Save } from 'lucide-react'
import type { PayrollUseCases } from '../application/useCases'
import {
  payrollComponentCodes,
  payrollComponentLabels,
  type EarningRule,
  type PayrollComponentCode,
} from '../domain/payroll'

interface Props {
  payrollGroupId: string
  payrollGroupLabel: string
  useCases: PayrollUseCases
}

const premiumOnlyComponents = new Set<PayrollComponentCode>(['NIGHT_REGULAR', 'NIGHT_OT'])

export default function EarningRulesManagement({ payrollGroupId, payrollGroupLabel, useCases }: Props) {
  const [rules, setRules] = useState<Map<PayrollComponentCode, string>>(new Map())
  const [savedRules, setSavedRules] = useState<Map<PayrollComponentCode, EarningRule>>(new Map())
  const [savingCode, setSavingCode] = useState<PayrollComponentCode | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let current = true
    setLoading(true)
    setError('')
    useCases.listEarningRules(payrollGroupId)
      .then((loadedRules) => {
        if (!current) return
        setSavedRules(new Map(loadedRules.map((rule) => [rule.componentCode, rule])))
        setRules(new Map(loadedRules.map((rule) => [rule.componentCode, String(rule.multiplier)])))
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load earning rules.')
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
  }, [payrollGroupId, useCases])

  async function saveRule(componentCode: PayrollComponentCode) {
    const multiplier = Number(rules.get(componentCode))
    setError('')
    setSuccess('')
    setSavingCode(componentCode)
    try {
      const saved = await useCases.saveEarningRule(payrollGroupId, componentCode, multiplier)
      setSavedRules((current) => new Map(current).set(componentCode, saved))
      setRules((current) => new Map(current).set(componentCode, String(saved.multiplier)))
      setSuccess(`${payrollComponentLabels[componentCode]} multiplier saved.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the earning rule.')
    } finally {
      setSavingCode(null)
    }
  }

  const configuredCount = savedRules.size

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 px-5 py-5">
        <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Pay configuration</p>
        <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold text-slate-900">Earning multipliers</h2>
            <p className="mt-1 text-sm text-slate-500">{payrollGroupLabel}. Configure every component before calculating gross pay.</p>
          </div>
          <span className={`rounded-full px-3 py-1.5 text-xs font-bold ${configuredCount === payrollComponentCodes.length ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>
            {configuredCount} / {payrollComponentCodes.length} configured
          </span>
        </div>
      </div>
      <div className="border-b border-amber-100 bg-amber-50 px-5 py-3 text-sm text-amber-900">
        Overtime and day multipliers represent the full pay rate. Night differential multipliers are premium-only add-ons (for example, enter <strong>0.10</strong> for a 10% differential).
      </div>
      {error && <p role="alert" className="mx-5 mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
      {success && <p role="status" className="mx-5 mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}
      <div className="divide-y divide-slate-100">
        {payrollComponentCodes.map((code) => {
          const configured = savedRules.has(code)
          const dirty = configured && rules.get(code) !== String(savedRules.get(code)?.multiplier)
          return (
            <div key={code} className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_10rem_auto] sm:items-center">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">{payrollComponentLabels[code]}</h3>
                <p className="mt-0.5 text-xs text-slate-500">
                  {premiumOnlyComponents.has(code) ? 'Premium-only portion per eligible minute' : 'Full base-rate multiple per eligible minute'}
                </p>
              </div>
              <label className="text-xs font-semibold text-slate-500">
                Multiplier
                <input
                  aria-label={`${payrollComponentLabels[code]} multiplier`}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                  type="number"
                  min="0"
                  max="9999.9999"
                  step="0.0001"
                  value={rules.get(code) ?? ''}
                  placeholder="Required"
                  onChange={(event) => setRules((current) => new Map(current).set(code, event.target.value))}
                />
              </label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void saveRule(code)}
                  disabled={loading || savingCode !== null || rules.get(code) === undefined || rules.get(code) === '' || (configured && !dirty)}
                  className="inline-flex min-w-24 items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {savingCode === code ? 'Saving…' : <><Save className="h-3.5 w-3.5" /> Save</>}
                </button>
                {configured && !dirty && <Check className="h-4 w-4 text-emerald-600" aria-label="Saved" />}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
