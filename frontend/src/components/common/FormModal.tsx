import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { LoaderCircle, X } from 'lucide-react'
import { useForm } from 'react-hook-form'
import type { DefaultValues, FieldValues, Resolver, UseFormReturn } from 'react-hook-form'

interface FormModalProps<T extends FieldValues> {
  isOpen: boolean
  title: ReactNode
  description?: string
  defaultValues: DefaultValues<T>
  resetKey: string
  resolver: Resolver<T>
  submitLabel: string
  showSubmit?: boolean
  onClose: () => void
  onSubmit: (values: T) => void | Promise<void>
  children: (form: UseFormReturn<T>) => ReactNode
}

export default function FormModal<T extends FieldValues>({
  isOpen,
  resetKey,
  ...props
}: FormModalProps<T>) {
  if (!isOpen) return null
  return <FormModalContent<T> key={resetKey} {...props} />
}

function FormModalContent<T extends FieldValues>({
  title,
  description,
  defaultValues,
  resolver,
  submitLabel,
  showSubmit = true,
  onClose,
  onSubmit,
  children,
}: Omit<FormModalProps<T>, 'isOpen' | 'resetKey'>) {
  const form = useForm<T>({ defaultValues, resolver })
  const dialogRef = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)
  const titleId = useId()
  const descriptionId = useId()
  onCloseRef.current = onClose

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const focusFrame = window.requestAnimationFrame(() => {
      const firstField = dialogRef.current?.querySelector<HTMLElement>(
        'form input:not([disabled]), form select:not([disabled]), form textarea:not([disabled])',
      )
      ;(firstField ?? dialogRef.current)?.focus()
    })

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }

      if (event.key !== 'Tab' || !dialogRef.current) return
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ))
      if (focusable.length === 0) {
        event.preventDefault()
        dialogRef.current.focus()
        return
      }

      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      window.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
      previouslyFocused?.focus()
    }
  }, [])

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/55 p-0 backdrop-blur-[2px]       sm:items-center sm:p-4"
          >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className="flex max-h-[94svh]         w-full flex-col overflow-hidden rounded-t-lg border border-slate-200 bg-white shadow-2xl outline-none sm:rounded-lg"
              >
        <div className="h-1 shrink-0 bg-indigo-600" />
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-3 sm:px-6">
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-bold text-slate-900">{title}</h2>
            {description && <p id={descriptionId} className="mt-0.5 text-xs leading-5 text-slate-500">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            title="Close"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={form.handleSubmit(onSubmit)} aria-busy={form.formState.isSubmitting} className="flex min-h-0 flex-1 flex-col">
          <div className="scrollbar-hidden min-h-0 flex-1 overflow-y-auto px-5 py-4 sm:px-6">{children(form)}</div>
          <div className="flex shrink-0 flex-col-reverse gap-2 border-t border-slate-200 bg-slate-50/80 px-5 py-3 sm:flex-row sm:justify-end sm:gap-3 sm:px-6">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-300 bg-white px-4 py-1.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
            >
              Cancel
            </button>
            {showSubmit && (
              <button
                type="submit"
                disabled={form.formState.isSubmitting}
                className="inline-flex items-center justify-center gap-2 rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {form.formState.isSubmitting && <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />}
                {form.formState.isSubmitting ? 'Saving...' : submitLabel}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>,
    document.body,
  )
}