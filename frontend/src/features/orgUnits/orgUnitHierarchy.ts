import type { SelectOption } from '../../components/common/SearchableSelect'
import type { OrgUnit } from '../../types/orgUnit'

export function descendantOrgUnitOptions(
  units: OrgUnit[], companyId: string, rootId?: string,
): SelectOption[] {
  if (!rootId) return []
  const available = units.filter((unit) => unit.company_id === companyId && !unit.deleted_at)
  if (!available.some((unit) => unit.id === rootId)) return []
  const children = new Map<string, OrgUnit[]>()
  for (const unit of available) {
    if (!unit.parent_org_unit_id) continue
    const siblings = children.get(unit.parent_org_unit_id) ?? []
    siblings.push(unit)
    children.set(unit.parent_org_unit_id, siblings)
  }
  const visited = new Set([rootId])
  const options: SelectOption[] = []
  const pending = [{ id: rootId, path: '' }]
  while (pending.length) {
    const parent = pending.pop()!
    for (const unit of children.get(parent.id) ?? []) {
      if (visited.has(unit.id)) continue
      visited.add(unit.id)
      const label = `${unit.org_unit_code} — ${unit.org_unit_name}`
      const path = parent.path ? `${parent.path} / ${label}` : label
      options.push({ value: unit.id, label: path })
      pending.push({ id: unit.id, path })
    }
  }
  return options.sort((a, b) => a.label.localeCompare(b.label))
}
