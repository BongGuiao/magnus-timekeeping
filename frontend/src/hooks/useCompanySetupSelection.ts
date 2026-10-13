import { useSyncExternalStore } from 'react'

const STORAGE_KEY = 'company_setup_selected_company_id'
const CHANGE_EVENT = 'company-setup-company-change'

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange)
  return () => window.removeEventListener(CHANGE_EVENT, onChange)
}

function getSnapshot() {
  return sessionStorage.getItem(STORAGE_KEY) ?? ''
}

function selectCompany(nextCompanyId: string) {
  if (nextCompanyId) sessionStorage.setItem(STORAGE_KEY, nextCompanyId)
  else sessionStorage.removeItem(STORAGE_KEY)
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

export function useCompanySetupSelection() {
  const companyId = useSyncExternalStore(subscribe, getSnapshot, () => '')

  return { companyId, selectCompany }
}
