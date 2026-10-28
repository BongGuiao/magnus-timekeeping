import { Component, type ErrorInfo, type ReactNode } from 'react'

const CHUNK_RELOAD_KEY = 'chunk_reload_attempted_at'
const CHUNK_RELOAD_COOLDOWN_MS = 60_000

export function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? `${error.name} ${error.message}` : String(error)
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|ChunkLoadError|Unable to preload CSS|is not a valid JavaScript MIME type/i.test(message)
}

// Reloads once per cooldown window so a stale deploy recovers without looping forever.
export function reloadForStaleBuild(): boolean {
  const lastAttempt = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) ?? 0)
  if (Date.now() - lastAttempt < CHUNK_RELOAD_COOLDOWN_MS) return false
  sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()))
  window.location.reload()
  return true
}

interface ErrorBoundaryProps {
  children: ReactNode
  label?: string
  onReset?: () => void
}

interface ErrorBoundaryState {
  error: Error | null
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[ErrorBoundary${this.props.label ? `: ${this.props.label}` : ''}]`, error, info.componentStack)
    if (isChunkLoadError(error)) reloadForStaleBuild()
  }

  private handleRetry = () => {
    this.setState({ error: null })
    this.props.onReset?.()
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="flex min-h-[60vh] items-center justify-center bg-slate-50 p-6 text-slate-900">
        <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold">Something went wrong</h2>
          <p className="mt-2 text-sm text-slate-600">
            This screen hit an unexpected error. Any data you already saved is not affected.
            Try again, or reload the page if the problem continues.
          </p>
          <pre className="mt-4 max-h-32 overflow-auto rounded-lg bg-slate-100 p-3 text-xs text-red-700">
            {error.message || String(error)}
          </pre>
          <div className="mt-5 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={this.handleRetry}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Try again
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
            >
              Reload page
            </button>
          </div>
        </div>
      </div>
    )
  }
}
