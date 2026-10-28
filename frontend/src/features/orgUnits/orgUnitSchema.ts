import { z } from 'zod'
import type { OrgUnit } from '../../types/orgUnit'

const optionalUuid = z.string().trim().refine(
  (value) => !value || z.uuid().safeParse(value).success,
  'Enter a valid employee UUID.',
)

export const orgUnitSchema = z.object({
  company_id: z.uuid('Company is required.'),
  parent_org_unit_id: z.string(),
  org_unit_code: z.string().trim().min(1, 'Org unit code is required.').max(30).regex(/^[A-Z0-9_-]+$/, 'Use uppercase letters, numbers, hyphens, or underscores.'),
  org_unit_name: z.string().trim().min(1, 'Org unit name is required.').max(150),
  org_unit_type: z.string().trim().min(1, 'Org unit type is required.').max(30),
  manager_employee_id: optionalUuid,
  cost_center_code: z.string().trim().max(30),
  effective_from: z.iso.date('Effective-from date is required.'),
  effective_to: z.union([z.literal(''), z.iso.date()]),
  status: z.enum(['DRAFT', 'ACTIVE', 'INACTIVE']),
  is_active: z.boolean(),
}).superRefine((values, context) => {
  if (values.effective_to && values.effective_to < values.effective_from) {
    context.addIssue({
      code: 'custom',
      path: ['effective_to'],
      message: 'Effective-to date cannot be earlier than effective-from date.',
    })
  }
})

export type OrgUnitFormValues = z.infer<typeof orgUnitSchema>

export const emptyOrgUnit: OrgUnitFormValues = {
  company_id: '',
  parent_org_unit_id: '',
  org_unit_code: '',
  org_unit_name: '',
  org_unit_type: '',
  manager_employee_id: '',
  cost_center_code: '',
  effective_from: new Date().toISOString().slice(0, 10),
  effective_to: '',
  status: 'ACTIVE',
  is_active: true,
}

export function toOrgUnitFormValues(orgUnit: OrgUnit): OrgUnitFormValues {
  return {
    company_id: orgUnit.company_id,
    parent_org_unit_id: orgUnit.parent_org_unit_id ?? '',
    org_unit_code: orgUnit.org_unit_code,
    org_unit_name: orgUnit.org_unit_name,
    org_unit_type: orgUnit.org_unit_type,
    manager_employee_id: orgUnit.manager_employee_id ?? '',
    cost_center_code: orgUnit.cost_center_code ?? '',
    effective_from: orgUnit.effective_from,
    effective_to: orgUnit.effective_to ?? '',
    status: orgUnit.status === 'DELETED' ? 'INACTIVE' : orgUnit.status,
    is_active: orgUnit.is_active,
  }
}