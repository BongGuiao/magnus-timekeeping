import { createContext, useContext, type ReactNode } from 'react'
import type { NavView } from './TopNav'

export interface WorkspaceTabsState {
  views: NavView[]
  activeView: NavView
  onSelect: (view: NavView) => void
  onClose: (view: NavView) => void
}

const WorkspaceTabsContext = createContext<WorkspaceTabsState | null>(null)

export function WorkspaceTabsProvider({
  value,
  children,
}: {
  value: WorkspaceTabsState
  children: ReactNode
}) {
  return (
    <WorkspaceTabsContext.Provider value={value}>
      {children}
    </WorkspaceTabsContext.Provider>
  )
}

export function useWorkspaceTabs() {
  return useContext(WorkspaceTabsContext)
}
