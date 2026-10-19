export function formatPeriod(effectiveFrom: string | null, effectiveTo: string | null) {
  if (!effectiveFrom) return '—'
  return `${effectiveFrom} → ${effectiveTo ?? 'open-ended'}`
}

export function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

export function formatTime(value: string) {
  return value.slice(0, 5)
}
