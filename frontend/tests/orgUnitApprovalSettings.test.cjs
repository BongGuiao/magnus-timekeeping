const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const React = require('react')
const ts = require('typescript')

function load(file, mocks = {}) {
  const exports = {}
  const code = ts.transpileModule(readFileSync(join(__dirname, '..', 'src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  runInNewContext(code, { exports, require: (name) => name in mocks ? mocks[name] : require(name) })
  return exports
}

const hierarchy = load(join('features', 'orgUnits', 'orgUnitHierarchy.ts'))
const schema = load(join('features', 'orgUnits', 'orgUnitSchema.ts'))
const { descendantOrgUnitOptions } = hierarchy
const unit = (id, parent = null, overrides = {}) => ({
  id, parent_org_unit_id: parent, company_id: 'company-a',
  org_unit_code: id.toUpperCase(), org_unit_name: id,
  ...overrides,
})
const units = [
  unit('root'), unit('child', 'root'), unit('leaf', 'child'),
  unit('sibling'), unit('other-company', 'root', { company_id: 'company-b' }),
  unit('deleted', 'root', { deleted_at: '2026-11-01' }), unit('orphan', 'missing'),
]

test('only same-company descendants appear, with full hierarchy labels', () => {
  const options = descendantOrgUnitOptions(units, 'company-a', 'root')
  assert.deepEqual(Array.from(options, (option) => option.value), ['child', 'leaf'])
  assert.equal(options[1].label, 'CHILD — child / LEAF — leaf')
  assert.deepEqual(Array.from(descendantOrgUnitOptions(units, 'company-a', 'child'), (option) => option.value), ['leaf'])
})

test('unsaved units, company changes, unavailable roots and malformed cycles are safe', () => {
  for (const root of [undefined, 'missing', 'deleted']) {
    assert.equal(descendantOrgUnitOptions(units, 'company-a', root).length, 0)
  }
  assert.equal(descendantOrgUnitOptions(units, 'company-b', 'root').length, 0)
  const cyclic = [unit('root', 'leaf'), unit('child', 'root'), unit('leaf', 'child')]
  assert.deepEqual(Array.from(descendantOrgUnitOptions(cyclic, 'company-a', 'root'), (option) => option.value), ['child', 'leaf'])
})

test('approval defaults are enabled and edit values retain saved exclusions without sharing arrays', () => {
  assert.equal(schema.emptyOrgUnit.manager_is_approver, true)
  assert.equal(schema.emptyOrgUnit.excluded_approval_org_unit_ids.length, 0)
  const saved = {
    ...schema.emptyOrgUnit, parent_org_unit_id: null, manager_employee_id: null,
    manager_is_approver: false, excluded_approval_org_unit_ids: ['child'],
  }
  const edited = schema.toOrgUnitFormValues(saved)
  assert.equal(edited.manager_is_approver, false)
  assert.deepEqual(Array.from(edited.excluded_approval_org_unit_ids), ['child'])
  edited.excluded_approval_org_unit_ids.push('leaf')
  assert.deepEqual(saved.excluded_approval_org_unit_ids, ['child'])
})

function findAll(node, predicate) {
  if (Array.isArray(node)) return node.flatMap((child) => findAll(child, predicate))
  if (!React.isValidElement(node)) return []
  return [...(predicate(node) ? [node] : []), ...findAll(node.props.children, predicate)]
}

function harness(overrides = {}, editingId = 'root') {
  const values = { ...schema.emptyOrgUnit, company_id: 'company-a', ...overrides }
  const changes = []
  const SearchableSelect = () => null
  const { default: Form } = load(join('features', 'orgUnits', 'OrgUnitForm.tsx'), {
    '../../components/common/SearchableSelect': { __esModule: true, default: SearchableSelect },
    './orgUnitHierarchy': hierarchy,
  })
  const form = {
    control: {}, register: (name) => ({ name }), watch: (name) => values[name],
    formState: { errors: {} },
    setValue: (name, value, options) => { values[name] = value; changes.push({ name, value, options }) },
  }
  const render = () => Form({ form, companies: [], employees: [], orgUnits: units, orgUnitTypes: [], editingId })
  const select = () => findAll(render(), (node) => node.type === SearchableSelect && node.props.label === 'Excluded org units')[0]
  return { render, select, values, changes }
}

test('searchable multi-selection adds unique descendants and removes exclusions', () => {
  const app = harness()
  assert.deepEqual(Array.from(app.select().props.options, (option) => option.value), ['child', 'leaf'])
  app.select().props.onChange('child')
  assert.deepEqual(Array.from(app.values.excluded_approval_org_unit_ids), ['child'])
  assert.equal(app.changes[0].options.shouldDirty, true)
  assert.equal(app.changes[0].options.shouldValidate, true)
  assert.deepEqual(Array.from(app.select().props.options, (option) => option.value), ['leaf'])
  const remove = findAll(app.render(), (node) => node.type === 'button' && node.props['aria-label'].startsWith('Remove exclusion'))[0]
  remove.props.onClick()
  assert.equal(app.values.excluded_approval_org_unit_ids.length, 0)
})

test('unsaved and disabled approvers cannot add exclusions, but saved exclusions remain removable', () => {
  const unsaved = harness({}, '')
  assert.equal(unsaved.select().props.disabled, true)
  const disabled = harness({ manager_is_approver: false, excluded_approval_org_unit_ids: ['child'] })
  assert.equal(disabled.select().props.disabled, true)
  assert.equal(disabled.values.excluded_approval_org_unit_ids.length, 1)
  assert.equal(findAll(disabled.render(), (node) => node.type === 'button').length, 1)
})
