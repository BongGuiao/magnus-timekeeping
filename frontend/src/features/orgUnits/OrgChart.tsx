import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  Building2, ChevronDown, ChevronUp, Maximize, Network, Pencil, Plus, RefreshCw, UserRound, ZoomIn, ZoomOut,
} from 'lucide-react'
import type { Employee } from '../../types/employee'
import type { OrgUnit } from '../../types/orgUnit'
import type { EmploymentAssignment } from '../../types/employeeRelated'
import {
  buildOrgChart, buildOrgChartMembers, orgChartEmployeeName,
  CHART_CARD_HEIGHT, CHART_CARD_WIDTH, MEMBER_CARD_HEIGHT, MEMBER_CARD_WIDTH,
} from './orgChartLayout'

interface Props {
  companyId: string
  companyName: string
  units: OrgUnit[]
  employees: Employee[]
  assignments: EmploymentAssignment[]
  membersLoading: boolean
  membersError: string
  isLoading: boolean
  loadFailed: boolean
  loadingEditId: string | null
  onEdit: (unit: OrgUnit) => void
  onCreate: () => void
  onRefresh: () => void
}

const toolClass = 'inline-flex min-h-8 items-center justify-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-indigo-600 disabled:opacity-40'
const MIN_ZOOM = 0.25
const MAX_ZOOM = 1.5

export default function OrgChart({
  companyId, companyName, units, employees, assignments, membersLoading, membersError,
  isLoading, loadFailed, loadingEditId, onEdit, onCreate, onRefresh,
}: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set())
  const [zoom, setZoom] = useState(1)
  const [expandedMembers, setExpandedMembers] = useState<Set<string>>(() => new Set())
  const viewport = useRef<HTMLDivElement>(null)
  const drag = useRef<{ pointerId: number; x: number; y: number; left: number; top: number } | null>(null)
  const zoomCenter = useRef<{ x: number; y: number } | null>(null)
  const membersByUnit = useMemo(() => buildOrgChartMembers(assignments, employees, companyId), [assignments, employees, companyId])
  const canShowMembers = !membersLoading && !membersError
  const chart = useMemo(
    () => buildOrgChart(units, companyId, collapsed, canShowMembers ? membersByUnit : new Map(), expandedMembers),
    [units, companyId, collapsed, membersByUnit, expandedMembers, canShowMembers],
  )
  const employeeMap = useMemo(() => new Map(employees.map((employee) => [employee.id, employee])), [employees])
  const visibleMap = new Map(chart.nodes.map((node) => [node.unit.id, node]))
  const managerCount = new Set(chart.allNodes.flatMap(({ unit }) => unit.manager_employee_id ? [unit.manager_employee_id] : [])).size
  const hasUnavailableMembers = chart.allNodes.some(({ unit }) => membersByUnit.get(unit.id)?.some((member) => !member.employee))

  useLayoutEffect(() => {
    const element = viewport.current
    if (element && zoomCenter.current) {
      const offset = Math.max(0, (element.clientWidth - chart.width * zoom) / 2)
      element.scrollLeft = zoomCenter.current.x * zoom + offset - element.clientWidth / 2
      element.scrollTop = zoomCenter.current.y * zoom - element.clientHeight / 2
      zoomCenter.current = null
    }
  }, [zoom, chart.width])

  function changeZoom(nextZoom: number) {
    const element = viewport.current
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextZoom))
    if (next === zoom) return
    if (element) {
      const offset = Math.max(0, (element.clientWidth - chart.width * zoom) / 2)
      zoomCenter.current = {
        x: (element.scrollLeft + element.clientWidth / 2 - offset) / zoom,
        y: (element.scrollTop + element.clientHeight / 2) / zoom,
      }
    }
    setZoom(next)
  }

  function fitChart() {
    const element = viewport.current
    if (!element || !chart.width || !chart.height) return
    zoomCenter.current = null
    setZoom(Math.max(MIN_ZOOM, Math.min(1, element.clientWidth / chart.width, element.clientHeight / chart.height)))
    element.scrollLeft = 0
    element.scrollTop = 0
  }

  function toggleUnit(id: string) {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleMembers(id: string) {
    setExpandedMembers((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function endDrag() {
    const element = viewport.current
    if (element && drag.current && element.hasPointerCapture(drag.current.pointerId)) {
      element.releasePointerCapture(drag.current.pointerId)
    }
    drag.current = null
  }

  return (
    <section aria-label="Organizational chart" className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="rounded-lg bg-indigo-50 p-2 text-indigo-600"><Network className="h-5 w-5" /></span>
          <div>
            <h1 className="text-base font-bold text-slate-900">Organizational chart</h1>
            <p className="text-xs text-slate-500">{companyName || 'Select a company to view its structure'}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={toolClass} onClick={onRefresh} disabled={isLoading || !companyId}>
            <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />Refresh
          </button>
          <button type="button" onClick={onCreate} disabled={isLoading || !companyId} className="inline-flex min-h-8 items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-40">
            <Plus className="h-4 w-4" />New org unit
          </button>
        </div>
      </div>

      {isLoading ? (
        <p role="status" className="p-12 text-center text-sm text-slate-500">Loading organization chart...</p>
      ) : loadFailed ? (
        <p className="p-12 text-center text-sm text-rose-700">Chart unavailable. Use Refresh to try again.</p>
      ) : !companyId || !chart.nodes.length ? (
        <div className="px-6 py-16 text-center">
          <Building2 className="mx-auto mb-3 h-10 w-10 text-indigo-300" />
          <h2 className="text-base font-bold text-slate-800">{companyId ? 'Your organization starts here' : 'Select a company'}</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
            {companyId ? 'Create an org unit, then choose its parent and manager in the existing form to build your chart.' : 'Use the company selector in the navigation to load its org units.'}
          </p>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-slate-50/70 px-4 py-2">
            <p className="text-xs text-slate-500">
              <strong className="text-slate-800">{chart.allNodes.length}</strong> units
              <span className="mx-2 text-slate-300">/</span>
              <strong className="text-slate-800">{chart.rootCount}</strong> top-level
              <span className="mx-2 text-slate-300">/</span>
              <strong className="text-slate-800">{managerCount}</strong> assigned managers
            </p>
            <div className="flex flex-wrap items-center gap-1.5">
              <button type="button" className={toolClass} onClick={() => {
                setCollapsed(new Set())
                if (canShowMembers) setExpandedMembers(new Set(chart.allNodes.map((node) => node.unit.id)))
              }}>Expand all</button>
              <button type="button" className={toolClass} onClick={() => {
                setCollapsed(new Set(chart.allNodes.map((node) => node.unit.id)))
                setExpandedMembers(new Set())
              }}>Collapse all</button>
              <div className="flex items-center gap-1">
                <button type="button" className={toolClass} aria-label="Zoom out" disabled={zoom <= MIN_ZOOM} onClick={() => changeZoom(zoom - 0.1)}><ZoomOut className="h-4 w-4" /></button>
                <output aria-label="Chart zoom" className="w-12 text-center text-xs font-semibold text-slate-600">{Math.round(zoom * 100)}%</output>
                <button type="button" className={toolClass} aria-label="Zoom in" disabled={zoom >= MAX_ZOOM} onClick={() => changeZoom(zoom + 0.1)}><ZoomIn className="h-4 w-4" /></button>
              </div>
              <button type="button" className={toolClass} onClick={fitChart}><Maximize className="h-3.5 w-3.5" />Fit</button>
              <button type="button" className={toolClass} onClick={() => changeZoom(1)}>100%</button>
            </div>
          </div>
          {chart.warnings.length > 0 && (
            <div role="alert" className="border-b border-amber-200 bg-amber-50 px-5 py-3 text-xs text-amber-900">
              <p className="font-bold">Some parent relationships need attention</p>
              <ul className="mt-1 list-inside list-disc">{chart.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
            </div>
          )}
          {membersLoading && <p role="status" className="border-b border-slate-200 px-5 py-3 text-xs text-slate-500">Loading current org unit members...</p>}
          {membersError && <p role="alert" className="border-b border-rose-200 bg-rose-50 px-5 py-3 text-xs text-rose-700">{membersError} Member branches are unavailable; use Refresh to try again.</p>}
          {canShowMembers && hasUnavailableMembers && (
            <p role="alert" className="border-b border-amber-200 bg-amber-50 px-5 py-3 text-xs text-amber-900">
              Some current assignments reference employee records unavailable to this account. They are shown as unavailable members.
            </p>
          )}
          <div
            ref={viewport}
            role="region"
            aria-label="Org chart canvas"
            aria-describedby="org-chart-help"
            tabIndex={0}
            className="relative h-[620px] max-h-[70svh] min-h-72 cursor-grab overflow-auto bg-slate-50 outline-offset-[-2px] active:cursor-grabbing focus-visible:outline-2 focus-visible:outline-indigo-500"
            style={{ backgroundImage: 'radial-gradient(#cbd5e1 1px, transparent 1px)', backgroundSize: '20px 20px' }}
            onPointerDown={(event) => {
              if (event.pointerType !== 'mouse' || event.button !== 0 || (event.target instanceof Element && event.target.closest('button'))) return
              const element = event.currentTarget
              element.focus({ preventScroll: true })
              drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, left: element.scrollLeft, top: element.scrollTop }
              element.setPointerCapture(event.pointerId)
              event.preventDefault()
            }}
            onPointerMove={(event) => {
              if (!drag.current || drag.current.pointerId !== event.pointerId) return
              event.currentTarget.scrollLeft = drag.current.left - (event.clientX - drag.current.x)
              event.currentTarget.scrollTop = drag.current.top - (event.clientY - drag.current.y)
            }}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onLostPointerCapture={() => { drag.current = null }}
          >
            <div className="relative mx-auto overflow-hidden" style={{ width: chart.width * zoom, height: chart.height * zoom }}>
              <div className="absolute left-0 top-0 origin-top-left" style={{ width: chart.width, height: chart.height, transform: `scale(${zoom})` }}>
                <svg aria-hidden="true" className="pointer-events-none absolute inset-0" width={chart.width} height={chart.height}>
                  {chart.nodes.map((node) => {
                    const parent = node.parentId ? visibleMap.get(node.parentId) : undefined
                    if (!parent) return null
                    const startX = parent.x + CHART_CARD_WIDTH / 2
                    const startY = parent.y + CHART_CARD_HEIGHT
                    const branchBottom = startY + parent.memberAreaHeight
                    const endX = node.x + CHART_CARD_WIDTH / 2
                    const middleY = (branchBottom + node.y) / 2
                    const path = parent.members.length
                      ? `M ${startX} ${startY} V ${startY + 16} H ${parent.branchX} V ${middleY} H ${endX} V ${node.y}`
                      : `M ${startX} ${startY} V ${middleY} H ${endX} V ${node.y}`
                    return <path key={node.unit.id} d={path} fill="none" stroke="#a5b4fc" strokeWidth="2" />
                  })}
                  {chart.nodes.flatMap((node) => node.members.map((member) => (
                    <path
                      key={`${node.unit.id}:${member.employeeId}`}
                      d={`M ${node.x + CHART_CARD_WIDTH / 2} ${node.y + CHART_CARD_HEIGHT} V ${node.y + CHART_CARD_HEIGHT + 32} H ${member.x - 12} V ${member.y + MEMBER_CARD_HEIGHT / 2} H ${member.x}`}
                      fill="none" stroke="#6ee7b7" strokeWidth="2" strokeDasharray="4 3"
                    />
                  )))}
                </svg>
                {chart.nodes.map(({ unit, x, y, depth, children, parentId }) => {
                  const manager = unit.manager_employee_id ? employeeMap.get(unit.manager_employee_id) : undefined
                  const managerName = manager
                    ? orgChartEmployeeName(manager)
                    : unit.manager_employee_id ? 'Manager unavailable' : 'No manager assigned'
                  const memberCount = (membersByUnit.get(unit.id) ?? []).filter((member) => member.employeeId !== unit.manager_employee_id).length
                  const peopleOpen = expandedMembers.has(unit.id) && canShowMembers
                  const memberLabel = membersLoading ? 'Loading members...'
                    : membersError ? 'Members unavailable'
                      : peopleOpen && memberCount === 0 ? unit.manager_employee_id ? 'No other current members' : 'No current members'
                        : `${peopleOpen ? 'Hide' : 'Show'} ${memberCount} ${memberCount === 1 ? 'member' : 'members'}`
                  const parent = parentId ? visibleMap.get(parentId) : undefined
                  const status = !unit.is_active && unit.status === 'ACTIVE' ? 'DISABLED' : unit.status
                  return (
                    <article
                      key={unit.id}
                      aria-label={`${unit.org_unit_name}, ${unit.org_unit_code}${parent ? `, parent ${parent.unit.org_unit_name}` : ', top level'}`}
                      className={`absolute flex flex-col rounded-lg border bg-white p-3 shadow-sm ${depth === 0 ? 'border-indigo-300 border-t-4 border-t-indigo-500' : 'border-slate-200 border-t-4 border-t-slate-300'}`}
                      style={{ left: x, top: y, width: CHART_CARD_WIDTH, height: CHART_CARD_HEIGHT }}
                    >
                      <div className="flex items-center justify-between gap-2 text-[10px] font-bold uppercase tracking-wide">
                        <span className="truncate text-indigo-600" title={unit.org_unit_type}>{unit.org_unit_type}</span>
                        <span className={`shrink-0 rounded px-1.5 py-0.5 ${status === 'ACTIVE' ? 'bg-emerald-50 text-emerald-700' : status === 'DRAFT' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-500'}`}>{status}</span>
                      </div>
                      <p className="mt-0.5 truncate text-[11px] text-slate-400" title={unit.org_unit_code}>{unit.org_unit_code}</p>
                      <button
                        type="button"
                        onClick={() => toggleMembers(unit.id)}
                        aria-label={`${peopleOpen ? 'Hide' : 'Show'} members of ${unit.org_unit_code}`}
                        aria-expanded={peopleOpen}
                        disabled={!canShowMembers}
                        className="mt-auto flex items-center gap-2 rounded-lg border border-indigo-100 bg-indigo-50/40 p-2 text-left hover:bg-indigo-50 focus-visible:outline-2 focus-visible:outline-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <span className="rounded-full bg-indigo-50 p-1.5 text-indigo-500"><UserRound className="h-4 w-4" /></span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[10px] font-bold uppercase text-slate-700" title={unit.org_unit_name}>{unit.org_unit_name}</p>
                          <p className={`truncate text-xs font-semibold ${manager ? 'text-slate-700' : 'text-amber-700'}`} title={manager ? `${manager.employee_no} - ${managerName}${manager.is_active ? '' : ' (Inactive)'}` : unit.manager_employee_id || managerName}>{managerName}{manager && !manager.is_active ? ' (Inactive)' : ''}</p>
                          <p className="mt-0.5 text-[10px] font-semibold text-indigo-600">{memberLabel}</p>
                        </div>
                        {peopleOpen ? <ChevronUp className="h-3.5 w-3.5 shrink-0 text-indigo-500" /> : <ChevronDown className="h-3.5 w-3.5 shrink-0 text-indigo-500" />}
                      </button>
                      <div className="mt-2 flex items-center justify-between gap-1.5">
                        <button type="button" onClick={() => onEdit(unit)} disabled={loadingEditId === unit.id} aria-label={`Edit ${unit.org_unit_code}`} className="inline-flex items-center gap-1 rounded px-1 py-1 text-[11px] font-semibold text-indigo-600 hover:bg-indigo-50 disabled:opacity-40">
                          <Pencil className="h-3 w-3" />{loadingEditId === unit.id ? 'Loading...' : 'Edit unit'}
                        </button>
                        {children.length > 0 ? (
                          <button type="button" onClick={() => toggleUnit(unit.id)} aria-expanded={!collapsed.has(unit.id)} aria-label={`${collapsed.has(unit.id) ? 'Expand' : 'Collapse'} ${unit.org_unit_code}`} className="inline-flex items-center gap-1 rounded bg-slate-50 px-2 py-1 text-[11px] font-semibold text-slate-600 hover:bg-indigo-50">
                            {children.length} {children.length === 1 ? 'unit' : 'units'}
                            {collapsed.has(unit.id) ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
                          </button>
                        ) : <span className="text-[10px] text-slate-400">No child units</span>}
                      </div>
                    </article>
                  )
                })}
                {chart.nodes.filter((node) => node.members.length > 0).map((node) => (
                  <p
                    key={`members-label:${node.unit.id}`}
                    className="absolute truncate text-[10px] font-bold uppercase tracking-wide text-emerald-700"
                    style={{ left: node.branchX + 20, top: node.y + CHART_CARD_HEIGHT + 36, width: MEMBER_CARD_WIDTH }}
                    title={`Current members of ${node.unit.org_unit_name}`}
                  >{node.members.length} current {node.members.length === 1 ? 'member' : 'members'} / {node.unit.org_unit_code}</p>
                ))}
                {chart.nodes.flatMap((node) => node.members.map((member) => {
                  const name = member.employee ? orgChartEmployeeName(member.employee) : 'Employee unavailable'
                  return (
                    <article
                      key={`${node.unit.id}:${member.employeeId}`}
                      aria-label={`${name}, member of ${node.unit.org_unit_name}`}
                      className="absolute flex items-center gap-2 rounded-lg border border-emerald-200 bg-white p-2.5 shadow-sm"
                      style={{ left: member.x, top: member.y, width: MEMBER_CARD_WIDTH, height: MEMBER_CARD_HEIGHT }}
                    >
                      <span className="shrink-0 rounded-full bg-emerald-50 p-1.5 text-emerald-600"><UserRound className="h-4 w-4" /></span>
                      <div className="min-w-0">
                        <h3 className={`line-clamp-2 text-xs leading-4 font-bold ${member.employee ? 'text-slate-800' : 'text-amber-700'}`} title={name}>{name}</h3>
                        <p className="mt-0.5 truncate text-[11px] leading-4 text-slate-500">{member.employee?.employee_no ?? 'Record unavailable'}</p>
                        <p className="truncate text-[10px] leading-3 text-emerald-600">Org unit member</p>
                      </div>
                    </article>
                  )
                }))}
              </div>
            </div>
          </div>
          <p id="org-chart-help" className="border-t border-slate-200 px-4 py-2 text-[11px] leading-4 text-slate-500">
            Drag the canvas or scroll to pan; on touch screens, swipe. Keyboard: focus the canvas and use arrow keys to scroll.
            {' '}Click a manager to show current members of that org unit only. The manager is already shown in the unit card and is not repeated.
            {' '}Purple lines show parent org units; dashed green lines show unit membership, not supervisor reporting or approval routes.
            {' '}All non-deleted units are shown, including draft, inactive, and future-effective units.
          </p>
        </>
      )}
    </section>
  )
}
