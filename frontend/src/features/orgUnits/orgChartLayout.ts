import type { OrgUnit } from '../../types/orgUnit'
import type { Employee } from '../../types/employee'
import type { EmploymentAssignment } from '../../types/employeeRelated'
import { isCurrentEmploymentAssignment, getManilaDate } from '../../lib/employeeRelatedApi'

export const CHART_CARD_WIDTH = 240
export const CHART_CARD_HEIGHT = 224
const HORIZONTAL_GAP = 24
const VERTICAL_GAP = 48
const PADDING = 24
export const MEMBER_CARD_WIDTH = 208
export const MEMBER_CARD_HEIGHT = 88
const MEMBER_GAP = 20
const MEMBER_TOP_GAP = 56

export interface OrgChartMember {
  employeeId: string
  employee: Employee | undefined
}

export function orgChartEmployeeName(employee: Employee): string {
  return employee.preferred_name
    || [employee.first_name, employee.middle_name, employee.last_name, employee.suffix].filter(Boolean).join(' ')
}

export function buildOrgChartMembers(
  assignments: EmploymentAssignment[],
  employees: Employee[],
  companyId: string,
  today = getManilaDate(),
): Map<string, OrgChartMember[]> {
  const employeeMap = new Map(employees.map((employee) => [employee.id, employee]))
  const grouped = new Map<string, Map<string, OrgChartMember>>()
  for (const assignment of assignments) {
    if (assignment.company_id !== companyId || !assignment.org_unit_id || !isCurrentEmploymentAssignment(assignment, today)) continue
    const employee = employeeMap.get(assignment.employee_id)
    if (employee && (!employee.is_active || employee.record_status === 'ARCHIVED')) continue
    const members = grouped.get(assignment.org_unit_id) ?? new Map<string, OrgChartMember>()
    members.set(assignment.employee_id, { employeeId: assignment.employee_id, employee })
    grouped.set(assignment.org_unit_id, members)
  }
  return new Map([...grouped].map(([id, members]) => [
    id,
    [...members.values()].sort((a, b) => (
      (a.employee ? orgChartEmployeeName(a.employee) : a.employeeId)
        .localeCompare(b.employee ? orgChartEmployeeName(b.employee) : b.employeeId)
      || a.employeeId.localeCompare(b.employeeId)
    )),
  ]))
}

export interface OrgChartMemberNode extends OrgChartMember {
  x: number
  y: number
}

export interface OrgChartNode {
  unit: OrgUnit
  parentId: string | null
  children: string[]
  x: number
  y: number
  depth: number
  members: OrgChartMemberNode[]
  memberAreaHeight: number
  branchX: number
}

export function buildOrgChart(
  units: OrgUnit[],
  companyId: string,
  collapsed: ReadonlySet<string>,
  membersByUnit: ReadonlyMap<string, OrgChartMember[]> = new Map(),
  expandedMembers: ReadonlySet<string> = new Set(),
) {
  const sorted = units
    .filter((unit) => unit.company_id === companyId && !unit.deleted_at && unit.status !== 'DELETED')
    .sort((a, b) => a.org_unit_name.localeCompare(b.org_unit_name) || a.org_unit_code.localeCompare(b.org_unit_code))
  const nodes = new Map<string, OrgChartNode>(sorted.map((unit) => [
    unit.id, {
      unit, parentId: unit.parent_org_unit_id, children: [], x: 0, y: 0, depth: 0,
      members: [], memberAreaHeight: 0, branchX: 0,
    },
  ]))
  const warnings: string[] = []

  for (const node of nodes.values()) {
    if (node.parentId && !nodes.has(node.parentId)) {
      warnings.push(`${node.unit.org_unit_code}: parent is unavailable in this company. Shown separately.`)
      node.parentId = null
    }
  }

  // Break only the displayed edge; never modify a saved reporting relationship.
  const checked = new Set<string>()
  for (const node of nodes.values()) {
    const path = new Set<string>()
    let current: OrgChartNode | undefined = node
    while (current && !checked.has(current.unit.id)) {
      if (path.has(current.unit.id)) {
        warnings.push(`${current.unit.org_unit_code}: circular parent relationship. Shown as a separate root; correct it using Edit unit.`)
        current.parentId = null
        break
      }
      path.add(current.unit.id)
      current = current.parentId ? nodes.get(current.parentId) : undefined
    }
    for (const id of path) checked.add(id)
  }

  const roots: OrgChartNode[] = []
  for (const node of nodes.values()) {
    if (node.parentId) nodes.get(node.parentId)!.children.push(node.unit.id)
    else roots.push(node)
  }

  const visible: OrgChartNode[] = []
  const stack = [...roots].reverse()
  while (stack.length) {
    const node = stack.pop()!
    visible.push(node)
    if (collapsed.has(node.unit.id)) continue
    for (const childId of [...node.children].reverse()) {
      const child = nodes.get(childId)!
      child.depth = node.depth + 1
      stack.push(child)
    }
  }

  const widths = new Map<string, number>()
  const levelHeights: number[] = []
  for (const node of [...visible].reverse()) {
    if (expandedMembers.has(node.unit.id)) {
      node.members = (membersByUnit.get(node.unit.id) ?? [])
        .filter((member) => member.employeeId !== node.unit.manager_employee_id)
        .map((member) => ({ ...member, x: 0, y: 0 }))
    }
    const columns = Math.min(3, node.members.length)
    const rows = columns ? Math.ceil(node.members.length / columns) : 0
    node.memberAreaHeight = rows ? MEMBER_TOP_GAP + rows * (MEMBER_CARD_HEIGHT + MEMBER_GAP) : 0
    levelHeights[node.depth] = Math.max(levelHeights[node.depth] ?? 0, CHART_CARD_HEIGHT + node.memberAreaHeight)
    const childrenWidth = collapsed.has(node.unit.id) ? 0 : node.children.reduce(
      (total, id, index) => total + widths.get(id)! + (index ? HORIZONTAL_GAP : 0), 0,
    )
    const memberWidth = columns * (MEMBER_CARD_WIDTH + MEMBER_GAP) + MEMBER_GAP
    widths.set(node.unit.id, Math.max(CHART_CARD_WIDTH, childrenWidth, memberWidth))
  }

  const levelOffsets = [PADDING]
  for (let depth = 1; depth < levelHeights.length; depth++) {
    levelOffsets[depth] = levelOffsets[depth - 1] + levelHeights[depth - 1] + VERTICAL_GAP
  }
  let rootOffset = PADDING
  for (const root of roots) {
    root.x = rootOffset
    rootOffset += widths.get(root.unit.id)! + HORIZONTAL_GAP
  }
  for (const node of visible) {
    const left = node.x
    node.x += (widths.get(node.unit.id)! - CHART_CARD_WIDTH) / 2
    node.y = levelOffsets[node.depth]
    const columns = Math.min(3, node.members.length)
    const memberWidth = columns * (MEMBER_CARD_WIDTH + MEMBER_GAP) + MEMBER_GAP
    const memberLeft = left + (widths.get(node.unit.id)! - memberWidth) / 2 + MEMBER_GAP
    node.branchX = memberLeft - MEMBER_GAP
    for (const [index, member] of node.members.entries()) {
      member.x = memberLeft + (index % columns) * (MEMBER_CARD_WIDTH + MEMBER_GAP)
      member.y = node.y + CHART_CARD_HEIGHT + MEMBER_TOP_GAP + Math.floor(index / columns) * (MEMBER_CARD_HEIGHT + MEMBER_GAP)
    }
    if (collapsed.has(node.unit.id)) continue
    let childOffset = left
    for (const id of node.children) {
      nodes.get(id)!.x = childOffset
      childOffset += widths.get(id)! + HORIZONTAL_GAP
    }
  }

  return {
    nodes: visible,
    allNodes: [...nodes.values()],
    warnings,
    rootCount: roots.length,
    width: roots.length ? rootOffset - HORIZONTAL_GAP + PADDING : 0,
    height: visible.reduce((height, node) => Math.max(height, node.y + CHART_CARD_HEIGHT + node.memberAreaHeight + PADDING), 0),
  }
}
