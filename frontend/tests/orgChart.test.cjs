const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

function load(file, dependencies = {}, context = {}) {
  const exports = {}
  const compiled = ts.transpileModule(readFileSync(join(__dirname, '..', 'src', 'features', 'orgUnits', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  runInNewContext(compiled, {
    exports,
    require: (name) => name in dependencies ? dependencies[name] : require(name),
    ...context,
  })
  return exports
}

const assignmentsApi = load(join('..', '..', 'lib', 'employeeRelatedApi.ts'), {
  './apiClient': { apiClient: {} },
})
const model = load('orgChartLayout.ts', { '../../lib/employeeRelatedApi': assignmentsApi })
const { buildOrgChart, buildOrgChartMembers, CHART_CARD_WIDTH, CHART_CARD_HEIGHT, MEMBER_CARD_WIDTH, MEMBER_CARD_HEIGHT } = model

function unit(id, parent = null, overrides = {}) {
  return {
    id, parent_org_unit_id: parent, company_id: 'company-a',
    org_unit_code: id.toUpperCase(), org_unit_name: id, org_unit_type: 'DEPARTMENT',
    manager_employee_id: null, status: 'ACTIVE', is_active: true,
    effective_from: '2026-01-01', effective_to: null, ...overrides,
  }
}

function chart(units, collapsed = []) {
  return buildOrgChart(units, 'company-a', new Set(collapsed))
}

function employee(id, name = id, overrides = {}) {
  return {
    id, employee_no: `EMP-${id}`, first_name: name, last_name: 'Test',
    middle_name: null, suffix: null, preferred_name: null,
    is_active: true, record_status: 'ACTIVE', ...overrides,
  }
}

function assignment(employeeId, unitId = 'head', overrides = {}) {
  return {
    id: `assignment-${employeeId}`, employee_id: employeeId, org_unit_id: unitId,
    company_id: 'company-a', is_active: true, status: 'ACTIVE',
    effective_from: '2026-01-01', effective_to: null, separation_date: null, ...overrides,
  }
}

test('unit members use current assignments, company scope, inclusive dates, and active employee records', () => {
  const employees = ['current', 'end-today', 'separation-today', 'future', 'expired', 'separated', 'disabled',
    'inactive-assignment', 'wrong-company', 'no-unit', 'inactive-employee', 'archived'].map((id) => employee(id, id, {
      is_active: id !== 'inactive-employee', record_status: id === 'archived' ? 'ARCHIVED' : 'ACTIVE',
    }))
  const result = buildOrgChartMembers([
    assignment('current'), assignment('current', 'head', { id: 'duplicate' }),
    assignment('end-today', 'head', { effective_to: '2026-11-06' }),
    assignment('separation-today', 'head', { separation_date: '2026-11-06' }),
    assignment('future', 'head', { effective_from: '2026-11-07' }),
    assignment('expired', 'head', { effective_to: '2026-11-05' }),
    assignment('separated', 'head', { separation_date: '2026-11-05' }),
    assignment('disabled', 'head', { is_active: false }),
    assignment('inactive-assignment', 'head', { status: 'INACTIVE' }),
    assignment('wrong-company', 'head', { company_id: 'company-b' }),
    assignment('no-unit', null), assignment('inactive-employee'), assignment('archived'),
    assignment('unavailable'),
  ], employees, 'company-a', '2026-11-06')
  assert.deepEqual(Array.from(result.get('head'), (member) => member.employeeId),
    ['current', 'end-today', 'separation-today', 'unavailable'])
  assert.equal(result.get('head').at(-1).employee, undefined)
})

test('parent and child unit membership remain separate regardless of assigned supervisor', () => {
  const people = [employee('a'), employee('b')]
  const result = buildOrgChartMembers([
    assignment('a', 'head', { supervisor_employee_id: 'other-manager' }),
    assignment('b', 'child', { supervisor_employee_id: 'head-manager' }),
    assignment('a', 'child'),
  ], people, 'company-a', '2026-11-06')
  assert.deepEqual(Array.from(result.get('head'), (member) => member.employeeId), ['a'])
  assert.deepEqual(Array.from(result.get('child'), (member) => member.employeeId), ['a', 'b'])
})

test('members form compact rows without overlap, managers are not duplicated, and child units move below them', () => {
  const units = [unit('head', null, { manager_employee_id: 'manager' }), unit('child', 'head'), unit('other')]
  const people = ['manager', ...Array.from({ length: 20 }, (_, index) => `e${index}`)].map((id) => employee(id))
  const members = buildOrgChartMembers(people.map((person) => assignment(person.id)), people, 'company-a', '2026-11-06')
  const result = buildOrgChart(units, 'company-a', new Set(), members, new Set(['head']))
  const head = result.nodes.find((node) => node.unit.id === 'head')
  const child = result.nodes.find((node) => node.unit.id === 'child')
  assert.equal(head.members.length, 20)
  assert.ok(!head.members.some((member) => member.employeeId === 'manager'))
  for (const member of head.members) {
    assert.ok(member.x >= 0 && member.x + MEMBER_CARD_WIDTH <= result.width)
    assert.ok(member.y > head.y + CHART_CARD_HEIGHT)
    assert.ok(child.y > member.y + MEMBER_CARD_HEIGHT)
    assert.ok(member.y + MEMBER_CARD_HEIGHT <= result.height)
    for (const other of head.members) {
      if (member.employeeId === other.employeeId) continue
      assert.ok(Math.abs(member.x - other.x) >= MEMBER_CARD_WIDTH || Math.abs(member.y - other.y) >= MEMBER_CARD_HEIGHT)
    }
  }
  assert.ok(child.y + CHART_CARD_HEIGHT <= result.height)
  assert.ok(result.width < 1500, 'many members wrap instead of creating an unbounded horizontal row')
  const closed = buildOrgChart(units, 'company-a', new Set(), members, new Set())
  assert.ok(closed.height < result.height)
  assert.equal(closed.nodes[0].members.length, 0)
})

test('builds a sorted forest from unordered data and positions parents above children', () => {
  const result = chart([unit('team', 'division'), unit('other'), unit('division', 'company'), unit('company')])
  assert.deepEqual(Array.from(result.nodes, (node) => node.unit.id), ['company', 'division', 'team', 'other'])
  assert.equal(result.rootCount, 2)
  assert.equal(result.warnings.length, 0)
  const byId = new Map(result.nodes.map((node) => [node.unit.id, node]))
  for (const node of result.nodes) {
    assert.ok(node.x >= 0)
    assert.ok(node.x + CHART_CARD_WIDTH <= result.width)
    assert.ok(node.y + CHART_CARD_HEIGHT <= result.height)
    if (node.parentId) assert.ok(node.y > byId.get(node.parentId).y + CHART_CARD_HEIGHT)
  }
})

test('siblings and separate roots do not overlap; parent centers over its subtree', () => {
  const result = chart([unit('root'), unit('a', 'root'), unit('b', 'root'), unit('c', 'a'), unit('d', 'a'), unit('z')])
  for (const node of result.nodes) {
    for (const other of result.nodes) {
      if (node.unit.id === other.unit.id || node.depth !== other.depth) continue
      assert.ok(Math.abs(node.x - other.x) >= CHART_CARD_WIDTH)
    }
  }
  const root = result.nodes.find((node) => node.unit.id === 'root')
  const leaves = result.nodes.filter((node) => ['c', 'd', 'b'].includes(node.unit.id))
  assert.equal(root.x, (Math.min(...leaves.map((node) => node.x)) + Math.max(...leaves.map((node) => node.x))) / 2)
})

test('collapse hides descendants, keeps direct child counts, and preserves nested collapse choices', () => {
  const units = [unit('root'), unit('child', 'root'), unit('grandchild', 'child')]
  const collapsed = chart(units, ['root', 'child'])
  assert.deepEqual(Array.from(collapsed.nodes, (node) => node.unit.id), ['root'])
  assert.equal(collapsed.nodes[0].children.length, 1)
  assert.equal(collapsed.allNodes.length, 3)
  assert.deepEqual(Array.from(chart(units, ['child']).nodes, (node) => node.unit.id), ['root', 'child'])
  assert.equal(chart(units).nodes.length, 3)
})

test('scopes to company and excludes deleted units but retains inactive, draft and future units', () => {
  const result = chart([
    unit('active'), unit('draft', null, { status: 'DRAFT' }),
    unit('inactive', null, { status: 'INACTIVE', is_active: false }),
    unit('future', null, { effective_from: '2099-01-01' }),
    unit('deleted', null, { deleted_at: '2026-01-01' }),
    unit('deleted-status', null, { status: 'DELETED' }),
    unit('other-company', null, { company_id: 'company-b' }),
  ])
  assert.deepEqual(Array.from(result.nodes, (node) => node.unit.id), ['active', 'draft', 'future', 'inactive'])
})

test('missing, deleted and cross-company parents produce warnings and separate display roots', () => {
  const result = chart([
    unit('a', 'missing'), unit('b', 'deleted'), unit('c', 'foreign'),
    unit('deleted', null, { status: 'DELETED' }), unit('foreign', null, { company_id: 'company-b' }),
  ])
  assert.equal(result.rootCount, 3)
  assert.equal(result.warnings.length, 3)
  assert.ok(result.nodes.every((node) => node.parentId === null))
  assert.ok(result.warnings.every((warning) => warning.includes('parent is unavailable')))
})

test('self-links and cycles stay visible without mutating persisted relationships', () => {
  const units = [unit('a', 'b'), unit('b', 'c'), unit('c', 'a'), unit('child', 'a'), unit('self', 'self')]
  const before = JSON.stringify(units)
  const result = chart(units)
  assert.equal(result.nodes.length, 5)
  assert.equal(new Set(result.nodes.map((node) => node.unit.id)).size, 5)
  assert.equal(result.rootCount, 2)
  assert.equal(result.warnings.length, 2)
  assert.ok(result.warnings.every((warning) => warning.includes('circular parent relationship')))
  assert.equal(JSON.stringify(units), before)
})

test('empty data and deeply nested hierarchies are handled without recursive rendering', () => {
  const empty = chart([])
  assert.equal(empty.width, 0)
  assert.equal(empty.height, 0)
  const deep = chart(Array.from({ length: 2000 }, (_, index) => unit(`${index}`, index ? `${index - 1}` : null)))
  assert.equal(deep.nodes.length, 2000)
  assert.equal(deep.nodes.at(-1).depth, 1999)
})

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return null
  if (predicate(tree)) return tree
  for (const child of React.Children.toArray(tree.props?.children)) {
    const result = find(child, predicate)
    if (result) return result
  }
  return null
}

function viewer(overrides = {}) {
  const slots = []
  let index = 0
  let effects = []
  function slot(initial) {
    const current = index++
    if (!(current in slots)) slots[current] = typeof initial === 'function' ? initial() : initial
    return [slots[current], (value) => {
      slots[current] = typeof value === 'function' ? value(slots[current]) : value
    }]
  }
  const Component = load('OrgChart.tsx', {
    './orgChartLayout': model,
    react: {
      ...React,
      useState: slot,
      useRef(initial) { return slot(() => ({ current: initial }))[0] },
      useMemo: (callback) => callback(),
      useLayoutEffect: (callback) => effects.push(callback),
    },
  }, { Element: class {} }).default
  const props = {
    companyId: 'company-a', companyName: 'Example Company',
    units: [unit('head'), unit('child', 'head')], employees: [],
    assignments: [], membersLoading: false, membersError: '',
    isLoading: false, loadFailed: false, loadingEditId: null,
    onCreate() {}, onEdit() {}, onRefresh() {}, ...overrides,
  }
  return () => {
    index = 0
    effects = []
    const tree = Component(props)
    const canvas = find(tree, (node) => node.props['aria-label'] === 'Org chart canvas')
    return {
      tree, canvas,
      html: renderToStaticMarkup(tree),
      effect() { effects.forEach((effect) => effect()) },
      button(label) {
        return find(tree, (node) => node.type === 'button'
          && (node.props['aria-label'] === label || renderToStaticMarkup(node).replace(/<[^>]*>/g, '').trim() === label))
      },
    }
  }
}

test('viewer renders manager names, explicit missing managers, statuses and hierarchy connectors', () => {
  const html = viewer({
    units: [
      unit('head', null, { manager_employee_id: 'manager' }),
      unit('child', 'head', { manager_employee_id: 'missing', status: 'DRAFT' }),
      unit('vacant', 'head', { is_active: false }),
    ],
    employees: [{ id: 'manager', employee_no: 'EMP-01', first_name: 'Alex', last_name: 'Smith', is_active: false }],
  })().html
  for (const text of ['Example Company', 'Alex Smith', '(Inactive)', 'Manager unavailable', 'No manager assigned', 'DRAFT', 'DISABLED', 'parent head']) {
    assert.ok(html.includes(text), text)
  }
  assert.equal((html.match(/stroke="#a5b4fc"/g) || []).length, 2)
  assert.ok(html.includes('tabindex="0"'))
  assert.ok(!html.includes('draggable="true"'))
})

test('clicking each manager shows only their unit employees as connected cards and toggles independently', () => {
  const props = {
    units: [unit('head', null, { manager_employee_id: 'manager' }), unit('child', 'head')],
    employees: [employee('manager'), employee('a'), employee('b')],
    assignments: [assignment('manager'), assignment('a'), assignment('b', 'child')],
  }
  const render = viewer(props)
  assert.ok(!render().html.includes('a Test, member of head'))
  render().button('Show members of HEAD').props.onClick()
  let state = render()
  assert.ok(state.html.includes('a Test, member of head'))
  assert.ok(!state.html.includes('b Test, member of child'))
  assert.ok(!state.html.includes('manager Test, member of head'))
  assert.ok(state.html.includes('stroke="#6ee7b7"'))
  assert.ok(state.html.includes('stroke-dasharray="4 3"'))
  assert.equal(state.button('Hide members of HEAD').props['aria-expanded'], true)
  state.button('Show members of CHILD').props.onClick()
  assert.ok(render().html.includes('b Test, member of child'))
  render().button('Hide members of HEAD').props.onClick()
  assert.ok(!render().html.includes('a Test, member of head'))
  assert.ok(render().html.includes('b Test, member of child'))
  render().button('Collapse all').props.onClick()
  assert.ok(!render().html.includes('member of child'))
  render().button('Expand all').props.onClick()
  assert.ok(render().html.includes('a Test, member of head'))
  assert.ok(render().html.includes('b Test, member of child'))
})

test('manager toggle labels use the unit description rather than the generic unit manager label', () => {
  const state = viewer({
    units: [unit('president', null, { org_unit_name: 'Office of the President', manager_employee_id: 'manager' })],
    employees: [employee('manager', 'Alex')],
  })()
  const button = state.button('Show members of PRESIDENT')
  const html = renderToStaticMarkup(button)
  assert.ok(html.includes('Office of the President'))
  assert.ok(html.includes('title="Office of the President"'))
  assert.ok(html.includes('Alex Test'))
  assert.ok(!html.includes('Unit manager'))
  const description = find(button, (node) => node.type === 'p' && node.props.title === 'Office of the President')
  assert.ok(description.props.className.includes('font-bold'))
  assert.equal(find(state.tree, (node) => node.type === 'h2' && node.props.title === 'Office of the President'), null)
  assert.equal((state.html.match(/>Office of the President</g) || []).length, 1)
})

test('loading and failed membership do not show misleading empty branches', () => {
  for (const props of [{ membersLoading: true }, { membersError: 'Permission denied.' }]) {
    const state = viewer(props)()
    assert.equal(state.button('Show members of HEAD').props.disabled, true)
    assert.ok(!state.html.includes('No other current members'))
    assert.ok(!state.html.includes('Show 0 members'))
  }
  const failed = viewer({ membersError: 'Permission denied.' })().html
  assert.ok(failed.includes('role="alert"'))
  assert.ok(failed.includes('Permission denied.'))
  assert.ok(failed.includes('use Refresh'))
  const render = viewer()
  render().button('Show members of HEAD').props.onClick()
  assert.ok(render().html.includes('No current members'))
  const managed = viewer({ units: [unit('head', null, { manager_employee_id: 'manager' })] })
  managed().button('Show members of HEAD').props.onClick()
  assert.ok(managed().html.includes('No other current members'))
})

test('unavailable employee records are explicit members, and units without managers remain expandable', () => {
  const render = viewer({ assignments: [assignment('missing')] })
  assert.ok(render().html.includes('unavailable to this account'))
  render().button('Show members of HEAD').props.onClick()
  assert.ok(render().html.includes('Employee unavailable, member of head'))
  assert.ok(render().html.includes('No manager assigned'))
})

test('viewer collapses and expands individual branches and all units', () => {
  const render = viewer()
  render().button('Collapse HEAD').props.onClick()
  assert.ok(!render().html.includes('aria-label="Edit CHILD"'))
  assert.equal(render().button('Expand HEAD').props['aria-expanded'], false)
  render().button('Expand HEAD').props.onClick()
  assert.ok(render().html.includes('aria-label="Edit CHILD"'))
  render().button('Collapse all').props.onClick()
  assert.ok(!render().html.includes('aria-label="Edit CHILD"'))
  render().button('Expand all').props.onClick()
  assert.ok(render().html.includes('aria-label="Edit CHILD"'))
})

test('existing form and refresh callbacks are wired without chart-side mutations', () => {
  const actions = []
  const render = viewer({
    onCreate: () => actions.push('create'),
    onEdit: (unit) => actions.push(unit.id),
    onRefresh: () => actions.push('refresh'),
  })
  render().button('New org unit').props.onClick()
  render().button('Edit HEAD').props.onClick()
  render().button('Refresh').props.onClick()
  assert.deepEqual(actions, ['create', 'head', 'refresh'])
  assert.equal(viewer({ loadingEditId: 'head' })().button('Edit HEAD').props.disabled, true)
})

test('zoom is bounded and Fit uses actual canvas dimensions', () => {
  const render = viewer()
  for (let index = 0; index < 20; index++) render().button('Zoom out').props.onClick()
  assert.ok(render().html.includes('25%'))
  assert.equal(render().button('Zoom out').props.disabled, true)
  for (let index = 0; index < 20; index++) render().button('Zoom in').props.onClick()
  assert.ok(render().html.includes('150%'))
  assert.equal(render().button('Zoom in').props.disabled, true)
  render().button('100%').props.onClick()
  assert.ok(render().html.includes('100%'))
  const state = render()
  const dimensions = chart([unit('head'), unit('child', 'head')])
  const element = { clientWidth: dimensions.width / 2, clientHeight: dimensions.height / 2, scrollLeft: 100, scrollTop: 100 }
  state.canvas.props.ref.current = element
  state.button('Fit').props.onClick()
  const fitted = render()
  fitted.effect()
  assert.ok(fitted.html.includes('50%'))
  assert.equal(element.scrollLeft, 0)
  assert.equal(element.scrollTop, 0)
})

test('loading, failed loading, no company and empty data have distinct states', () => {
  assert.ok(viewer({ isLoading: true })().html.includes('Loading organization chart'))
  const failed = viewer({ loadFailed: true })().html
  assert.ok(failed.includes('Chart unavailable'))
  assert.ok(!failed.includes('Your organization starts here'))
  const noCompany = viewer({ companyId: '', units: [] })()
  assert.ok(noCompany.html.includes('Select a company'))
  assert.equal(noCompany.button('New org unit').props.disabled, true)
  assert.ok(viewer({ units: [] })().html.includes('Your organization starts here'))
})

test('zoom retains the visual center when a centered chart becomes scrollable', () => {
  const render = viewer({ units: [unit('head'), unit('a', 'head'), unit('b', 'head'), unit('c', 'head')] })
  const state = render()
  const dimensions = chart([unit('head'), unit('a', 'head'), unit('b', 'head'), unit('c', 'head')])
  const element = { clientWidth: dimensions.width * 1.05, clientHeight: 300, scrollLeft: 0, scrollTop: 0 }
  state.canvas.props.ref.current = element
  state.button('Zoom in').props.onClick()
  render().effect()
  assert.ok(Math.abs(element.scrollLeft - dimensions.width * 0.025) < 0.00001)
  assert.ok(Math.abs(element.scrollTop - 15) < 0.00001)
})

test('mouse dragging pans the viewport, focuses it, and releases capture; touch and right click stay native', () => {
  const state = viewer()()
  const captures = new Set()
  const element = {
    scrollLeft: 40, scrollTop: 60, focused: false,
    focus() { this.focused = true },
    setPointerCapture(id) { captures.add(id) },
    hasPointerCapture(id) { return captures.has(id) },
    releasePointerCapture(id) { captures.delete(id) },
  }
  state.canvas.props.ref.current = element
  const event = {
    pointerType: 'mouse', button: 0, pointerId: 7, target: null,
    currentTarget: element, clientX: 100, clientY: 100,
    preventDefault() {},
  }
  state.canvas.props.onPointerDown({ ...event, pointerType: 'touch' })
  state.canvas.props.onPointerDown({ ...event, button: 2 })
  assert.equal(captures.size, 0)
  state.canvas.props.onPointerDown(event)
  assert.equal(element.focused, true)
  assert.ok(captures.has(7))
  state.canvas.props.onPointerMove({ ...event, clientX: 70, clientY: 80 })
  assert.equal(element.scrollLeft, 70)
  assert.equal(element.scrollTop, 80)
  state.canvas.props.onPointerUp()
  assert.equal(captures.size, 0)
  state.canvas.props.onPointerMove({ ...event, clientX: 0, clientY: 0 })
  assert.equal(element.scrollLeft, 70)
})

test('invalid relationships display warnings while retaining edit access', () => {
  const state = viewer({ units: [unit('bad', 'missing'), unit('self', 'self')] })()
  assert.ok(state.html.includes('role="alert"'))
  assert.ok(state.html.includes('parent is unavailable'))
  assert.ok(state.html.includes('circular parent relationship'))
  assert.ok(state.button('Edit BAD'))
  assert.ok(state.button('Edit SELF'))
})
