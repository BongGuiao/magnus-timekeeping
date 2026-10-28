import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import ErrorBoundary, { reloadForStaleBuild } from './components/common/ErrorBoundary'

// Fired by Vite when a lazily loaded chunk no longer exists (e.g. after a redeploy).
window.addEventListener('vite:preloadError', (event) => {
  if (reloadForStaleBuild()) event.preventDefault()
})

window.addEventListener('unhandledrejection', (event) => {
  console.error('[Unhandled promise rejection]', event.reason)
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary label="app">
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
