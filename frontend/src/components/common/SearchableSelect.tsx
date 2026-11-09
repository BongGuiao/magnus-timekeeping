import { useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown } from 'lucide-react'

export interface SelectOption {
  value: string
  label: string
}

const MAX_VISIBLE_OPTIONS = 100

interface Props {
  options: SelectOption[]
  value: string
  onChange: (value: string) => void
  onBlur?: () => void
  inputRef?: (element: HTMLInputElement | null) => void
  name?: string
  label: string
  placeholder?: string
  disabled?: boolean
  required?: boolean
  className?: string
  'aria-describedby'?: string
}

export default function SearchableSelect({
  options, value, onChange, onBlur, inputRef, name, label, placeholder = 'Select an option',
  disabled, required, className, 'aria-describedby': describedBy,
}: Props) {
  const id = useId()
  const input = useRef<HTMLInputElement | null>(null)
  const list = useRef<HTMLDivElement | null>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [position, setPosition] = useState({ left: 0, top: 0, width: 0, maxHeight: 240 })
  const selected = options.find((option) => option.value === value)
  const matches = options.filter((option) => !option.value || option.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  const visibleMatches = matches.slice(0, MAX_VISIBLE_OPTIONS)
  const expanded = open && !disabled
  const activeIndex = Math.min(active, Math.max(0, visibleMatches.length - 1))

  useLayoutEffect(() => {
    if (!expanded) return
    function reposition() {
      const rect = input.current?.getBoundingClientRect()
      if (!rect) return
      const below = window.innerHeight - rect.bottom - 8
      const above = rect.top - 8
      const height = Math.min(240, Math.max(0, below >= 160 || below >= above ? below : above))
      setPosition({
        left: rect.left, width: rect.width,
        top: below >= 160 || below >= above ? rect.bottom + 4 : rect.top - height - 4,
        maxHeight: height,
      })
    }
    reposition()
    window.addEventListener('resize', reposition)
    window.addEventListener('scroll', reposition, true)
    return () => {
      window.removeEventListener('resize', reposition)
      window.removeEventListener('scroll', reposition, true)
    }
  }, [expanded])

  useLayoutEffect(() => {
    if (expanded) list.current?.children[activeIndex]?.scrollIntoView({ block: 'nearest' })
  }, [expanded, activeIndex, query])

  function close() {
    setOpen(false)
    setQuery('')
  }

  function select(option: SelectOption) {
    if (input.current?.matches(':disabled')) {
      close()
      return
    }
    onChange(option.value)
    close()
  }

  return (
    <>
      <span className="relative block">
      <input
        ref={(element) => {
          input.current = element
          inputRef?.(element)
        }}
        name={name}
        role="combobox"
        aria-label={label}
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={`${id}-options`}
        aria-activedescendant={expanded && matches.length ? `${id}-option-${activeIndex}` : undefined}
        aria-describedby={describedBy}
        aria-required={required}
        disabled={disabled}
        autoComplete="off"
        placeholder={placeholder}
        className={`${className ?? ''} pr-8`}
        value={expanded ? query : selected?.label ?? (value ? 'Previously selected option unavailable' : '')}
        onFocus={() => {
          setOpen(true)
          setQuery('')
          setActive(Math.max(0, options.findIndex((option) => option.value === value)))
        }}
        onClick={() => setOpen(true)}
        onBlur={() => { close(); onBlur?.() }}
        onChange={(event) => { setQuery(event.target.value); setActive(0); setOpen(true) }}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && expanded) {
            event.preventDefault()
            event.stopPropagation()
            close()
          } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            event.stopPropagation()
            setOpen(true)
            setActive(expanded
              ? Math.max(0, Math.min(matches.length - 1, activeIndex + (event.key === 'ArrowDown' ? 1 : -1)))
              : Math.max(0, options.findIndex((option) => option.value === value)))
          } else if (event.key === 'Enter') {
            event.preventDefault()
            event.stopPropagation()
            if (expanded && matches[activeIndex]) select(matches[activeIndex])
            else setOpen(true)
          }
        }}
      />
      <ChevronDown aria-hidden="true" className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
      </span>
      {expanded && createPortal(
        <div
          ref={list}
          id={`${id}-options`}
          role="listbox"
          aria-label={`${label} options`}
          style={{ position: 'fixed', ...position, zIndex: 100 }}
          className="overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 text-xs font-normal shadow-lg"
          onMouseDown={(event) => event.preventDefault()}
        >
          {visibleMatches.map((option, index) => (
            <div
              key={option.value}
              id={`${id}-option-${index}`}
              role="option"
              aria-selected={value === option.value}
              onMouseMove={() => setActive(index)}
              onClick={() => select(option)}
              className={`cursor-pointer px-3 py-2 ${index === activeIndex ? 'bg-indigo-50 text-indigo-800' : 'text-slate-700'} ${value === option.value ? 'font-semibold' : ''}`}
            >
              {option.label}
            </div>
          ))}
          {!matches.length && <p role="status" className="px-3 py-2 text-slate-500">No matching options.</p>}
          {matches.length > MAX_VISIBLE_OPTIONS && (
            <p role="status" className="border-t border-slate-100 px-3 py-2 text-slate-500">
              Showing the first {MAX_VISIBLE_OPTIONS} results. Refine your search to see more.
            </p>
          )}
        </div>,
        document.body,
      )}
    </>
  )
}
