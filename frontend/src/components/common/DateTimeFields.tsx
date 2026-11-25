interface Props {
  label: string
  value: string
  onChange: (value: string) => void
  className: string
  min?: string
  max?: string
  step?: number
}

export default function DateTimeFields({ label, value, onChange, className, min, max, step = 60 }: Props) {
  const [date = '', time = ''] = value.split('T')
  const [minDate, minTime] = (min ?? '').split('T')
  const [maxDate, maxTime] = (max ?? '').split('T')

  function update(nextDate: string, nextTime: string) {
    onChange(nextDate || nextTime ? `${nextDate}T${nextTime}` : '')
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-xs font-semibold text-slate-700">{label} date
        <input required type="date" min={minDate || undefined} max={maxDate || undefined}
          value={date} onChange={(event) => update(event.target.value, time)} className={className} />
      </label>
      <label className="text-xs font-semibold text-slate-700">{label} time
        <input required type="time" step={step} min={date === minDate ? minTime || undefined : undefined}
          max={date === maxDate ? maxTime || undefined : undefined}
          value={time} onChange={(event) => update(date, event.target.value)} className={className} />
      </label>
    </div>
  )
}
