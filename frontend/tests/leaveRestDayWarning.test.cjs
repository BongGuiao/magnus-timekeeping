const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const ts = require('typescript')

const source = readFileSync(join(__dirname, '..', 'src', 'pages', 'LeaveApplication.tsx'), 'utf8')
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText

function harness(check) {
  const cells = []
  const effects = []
  let hook = 0
  const hooks = {
    useState(initial) {
      const index = hook++
      if (!(index in cells)) cells[index] = typeof initial === 'function' ? initial() : initial
      return [cells[index], (value) => { cells[index] = typeof value === 'function' ? value(cells[index]) : value }]
    },
    useEffect(effect, dependencies) {
      const index = hook++
      const prior = cells[index]
      if (!prior || dependencies.some((value, i) => value !== prior.dependencies[i])) {
        prior?.cleanup?.()
        effects.push(() => { cells[index] = { dependencies, cleanup: effect() } })
      }
    },
  }
  const types = [{
    id: 'leave', company_id: 'company', leave_name: 'Vacation', unit_type: 'DAYS',
    is_active: true, status: 'ACTIVE', effective_from: '2020-01-01', effective_to: null,
  }]
  const dependencies = {
    react: hooks,
    '../components/common/AttendanceDeadlines': { __esModule: true, default: () => null },
    '../components/dashboard/TopNav': { __esModule: true, default: () => null },
    '../hooks/useLogout': { useLogout: () => ({ logout() {} }) },
    '../lib/employeeRelatedApi': { fetchCurrentEmploymentAssignments: async () => [{ company_id: 'company', primary_location_id: 'location' }] },
    '../lib/leaveApi': {
      previewLeaveDuration: check,
      getAuthenticatedEmployeeId: () => 'employee',
      fetchLeaveTypes: async () => types,
      fetchMyLeaveApplications: async () => [],
      leaveUnitsToMinutes: (value) => value * 480,
      minutesToLeaveUnits: (value) => value / 480,
    },
  }
  const exports = {}
  runInNewContext(code, {
    exports, Error,
    require: (name) => name in dependencies ? dependencies[name] : require(name),
  })
  return () => {
    hook = 0
    const tree = exports.default({ employeeName: 'Employee' })
    while (effects.length) effects.shift()()
    return tree
  }
}

function find(node, predicate) {
  if (Array.isArray(node)) return node.map((item) => find(item, predicate)).find(Boolean)
  if (!React.isValidElement(node)) return null
  if (predicate(node)) return node
  return find(node.props.children, predicate)
}

const settle = () => new Promise((resolve) => setImmediate(resolve))

test('duration preview excludes rest days and holidays; changing dates recalculates', async () => {
  const checks = []
  const render = harness(async () => checks.shift())
  checks.push({ rest_days: ['2026-12-05'], holidays: ['2026-12-06'], requested_minutes: 480 })
  render()
  await settle()
  let tree = render()
  assert.match(renderToStaticMarkup(tree), /Rest days excluded: 2026-12-05/)
  assert.match(renderToStaticMarkup(tree), /Non-working holidays excluded: 2026-12-06/)
  assert.equal(find(tree, (node) => node.type === 'button' && node.props.type === 'submit').props.disabled, false)

  checks.push({ rest_days: [], holidays: [], requested_minutes: 480 })
  const end = find(tree, (node) => node.type === 'input' && node.props.type === 'datetime-local' && node.props.value.endsWith('18:00'))
  end.props.onChange({ target: { value: end.props.value.replace('18:00', '19:00') } })
  tree = render()
  assert.match(renderToStaticMarkup(tree), /Calculating leave duration/)
  await settle()
  tree = render()
  assert.doesNotMatch(renderToStaticMarkup(tree), /Rest days excluded/)
})

test('zero duration and failed calculations prevent filing', async () => {
  const responses = [
    { rest_days: [], holidays: ['2026-12-05'], requested_minutes: 0 },
    new Error('Schedule service unavailable'),
  ]
  const render = harness(async () => {
    const response = responses.shift()
    if (response instanceof Error) throw response
    return response
  })
  render()
  await settle()
  let tree = render()
  assert.match(renderToStaticMarkup(tree), /no leave application is required/)
  assert.equal(find(tree, (node) => node.type === 'button' && node.props.type === 'submit').props.disabled, true)
  const end = find(tree, (node) => node.type === 'input' && node.props.type === 'datetime-local' && node.props.value.endsWith('18:00'))
  end.props.onChange({ target: { value: end.props.value.replace('18:00', '19:00') } })
  render()
  await settle()
  tree = render()
  assert.match(renderToStaticMarkup(tree), /Leave calculation unavailable: Schedule service unavailable/)
  assert.equal(find(tree, (node) => node.type === 'button' && node.props.type === 'submit').props.disabled, true)
})

test('a late response for previous dates cannot replace the current warning', async () => {
  const pending = []
  const render = harness(() => new Promise((resolve) => pending.push(resolve)))
  render()
  await settle()
  let tree = render()
  const end = find(tree, (node) => node.type === 'input' && node.props.type === 'datetime-local' && node.props.value.endsWith('18:00'))
  end.props.onChange({ target: { value: end.props.value.replace('18:00', '19:00') } })
  render()
  pending[1]({ rest_days: ['2026-12-06'], holidays: [], requested_minutes: 480 })
  await settle()
  pending[0]({ rest_days: ['2026-12-05'], holidays: [], requested_minutes: 480 })
  await settle()
  tree = render()
  const html = renderToStaticMarkup(tree)
  assert.match(html, /2026-12-06/)
  assert.doesNotMatch(html, /2026-12-05/)
})
