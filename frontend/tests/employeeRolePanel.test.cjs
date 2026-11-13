const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const React = require('react')
const ts = require('typescript')

const compiled = ts.transpileModule(readFileSync(join(__dirname, '..', 'src', 'features', 'employees', 'EmployeeRolePanel.tsx'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText

function findAll(node, predicate) {
  if (Array.isArray(node)) return node.flatMap((child) => findAll(child, predicate))
  if (!React.isValidElement(node)) return []
  return [...(predicate(node) ? [node] : []), ...findAll(node.props.children, predicate)]
}

function text(node) {
  if (Array.isArray(node)) return node.map(text).join('')
  if (React.isValidElement(node)) return text(node.props.children)
  return typeof node === 'string' ? node : ''
}

const unit = (id, overrides = {}) => ({
  id, company_id: 'company-a', org_unit_code: id, org_unit_name: id,
  is_active: true, status: 'ACTIVE', ...overrides,
})
const units = [
  unit('old'), unit('new'), unit('foreign', { company_id: 'company-b' }),
  unit('inactive', { is_active: false, status: 'INACTIVE' }), unit('draft', { status: 'DRAFT' }),
]
const assignment = (overrides = {}) => ({
  id: 'assignment', user_id: 'employee', role_id: 'role',
  company_id: 'company-a', org_unit_id: 'old',
  effective_from: '2026-11-01', effective_to: null, ...overrides,
})
const settle = () => new Promise(setImmediate)

async function harness(saved = [assignment()]) {
  const state = []
  const effects = []
  const updates = []
  let cursor = 0
  let loading = true
  let assignments = saved
  const SearchableSelect = () => null
  const exports = {}
  runInNewContext(compiled, {
    exports, window: { addEventListener() {}, removeEventListener() {} },
    require(name) {
      if (name === 'react') return {
        ...React,
        useState(initial) {
          const index = cursor++
          if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial
          return [state[index], (value) => { state[index] = typeof value === 'function' ? value(state[index]) : value }]
        },
        useEffect(callback) { if (loading) effects.push(callback) },
      }
      if (name === '../../components/common/SearchableSelect') return { __esModule: true, default: SearchableSelect }
      if (name === '../../lib/userRoleApi') return {
        fetchAvailableRoles: async () => [{ id: 'role', role_name: 'Employee', role_code: 'EMPLOYEE' }],
        fetchUserRoleAssignments: async () => assignments,
        updateUserRoleAssignment: async (id, payload) => {
          updates.push({ id, ...payload })
          assignments = assignments.map((row) => row.id === id ? { ...row, ...payload } : row)
          return assignments.find((row) => row.id === id)
        },
      }
      if (name === '../../lib/employeeRelatedApi') return {
        getManilaDate: () => '2026-11-13',
        fetchEmploymentAssignments: async () => [{ company_id: 'company-b' }],
        isCurrentEmploymentAssignment: () => true,
        EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT: 'employment-assignment-changed',
      }
      return require(name)
    },
  })
  function render() {
    cursor = 0
    return exports.default({
      employee: { id: 'employee', first_name: 'Synthetic', last_name: 'Employee' },
      companies: [], orgUnits: units,
    })
  }
  render()
  loading = false
  effects.forEach((callback) => callback())
  await settle()
  const row = () => findAll(render(), (node) => node.type === 'li' && node.key === saved[0].id)[0]
  const button = (label) => findAll(row(), (node) => node.type === 'button' && text(node) === label)[0]
  button('Edit assignment').props.onClick()
  return {
    render, updates, button,
    scope: () => findAll(row(), (node) => node.type === SearchableSelect && node.props.label === 'Edit org unit scope')[0],
    dates: () => findAll(row(), (node) => node.type === 'input' && node.props.type === 'date'),
    error: () => text(findAll(render(), (node) => node.props.role === 'alert')),
    async save() { button('Save changes').props.onClick(); await settle() },
  }
}

test('editing uses the assignment company and saves org-unit scope without changing company or role', async () => {
  const app = await harness()
  assert.equal(app.scope().props.value, 'old')
  assert.deepEqual(Array.from(app.scope().props.options, (option) => option.value), ['', 'old', 'new'])
  app.scope().props.onChange('new')
  await app.save()
  assert.deepEqual(app.updates, [{
    id: 'assignment', org_unit_id: 'new', effective_from: '2026-11-01', effective_to: null,
  }])
})

test('clearing the org unit saves company-wide scope and conflicting scopes cannot overlap', async () => {
  const app = await harness()
  app.scope().props.onChange('')
  await app.save()
  assert.equal(app.updates[0].org_unit_id, null)
  for (const scope of ['new', '']) {
    const conflict = await harness([assignment(), assignment({ id: 'other', org_unit_id: 'new' })])
    conflict.scope().props.onChange(scope)
    await conflict.save()
    assert.equal(conflict.updates.length, 0)
    assert.match(conflict.error(), /scope and dates overlap/)
  }
})

test('invalid org-unit selections are rejected while unchanged legacy scope permits date edits', async () => {
  for (const scope of ['foreign', 'inactive', 'draft', 'unknown']) {
    const app = await harness()
    app.scope().props.onChange(scope)
    await app.save()
    assert.equal(app.updates.length, 0)
    assert.match(app.error(), /active org unit within/)
  }
  const legacy = await harness([assignment({ org_unit_id: 'inactive' })])
  legacy.dates()[1].props.onChange({ target: { value: '2026-11-30' } })
  await legacy.save()
  assert.deepEqual(legacy.updates, [{
    id: 'assignment', effective_from: '2026-11-01', effective_to: '2026-11-30',
  }])
  const global = await harness([assignment({ company_id: null, org_unit_id: null })])
  assert.equal(global.scope().props.disabled, true)
  await global.save()
  assert.equal(global.updates[0].org_unit_id, undefined)
})

test('scope updates retain date validation and permit non-overlapping assignments', async () => {
  const invalid = await harness()
  invalid.scope().props.onChange('new')
  invalid.dates()[1].props.onChange({ target: { value: '2026-10-31' } })
  await invalid.save()
  assert.equal(invalid.updates.length, 0)
  assert.match(invalid.error(), /expiration date must be on or after/)

  const app = await harness([
    assignment(),
    assignment({ id: 'other', org_unit_id: 'new', effective_from: '2026-12-01' }),
  ])
  app.scope().props.onChange('new')
  app.dates()[1].props.onChange({ target: { value: '2026-11-30' } })
  await app.save()
  assert.equal(app.updates[0].org_unit_id, 'new')
})
