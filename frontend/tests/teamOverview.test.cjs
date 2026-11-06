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
  const compiled = ts.transpileModule(readFileSync(join(__dirname, '..', 'src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  runInNewContext(compiled, {
    exports,
    require: (name) => name in dependencies ? dependencies[name] : require(name),
    ...context,
  })
  return exports
}

const TeamOverview = load(join('components', 'dashboard', 'TeamOverview.tsx')).default

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return null
  if (predicate(tree)) return tree
  for (const child of React.Children.toArray(tree.props?.children)) {
    const match = find(child, predicate)
    if (match) return match
  }
  return null
}

function dashboard(role, permissions, admin = false, onNavigate, apiOverrides = {}) {
  let index = 0
  const states = []
  const dependencies = {
    react: {
      ...React,
      useEffect() {},
      useState(initial) {
        const slot = index++
        if (!(slot in states)) states[slot] = typeof initial === 'function' ? initial() : initial
        return [states[slot], (value) => {
          states[slot] = typeof value === 'function' ? value(states[slot]) : value
        }]
      },
    },
    '../components/dashboard/TeamOverview': { __esModule: true, default: TeamOverview },
    '../hooks/useLogout': { useLogout: () => ({ logout() {} }) },
    '../data/mockDashboard': { mockDashboardData: {
      workHours: { weeklyTarget: 40 }, attendanceExceptions: { periodLabel: 'This month' },
      leaveRequests: [], leaveBalances: [],
    } },
    '../types/role': {
      getSelectedDashboardRole: () => role,
      getAvailableRoleCodes: () => ['SUPERVISOR'],
      normalizeDashboardRole: (value) => value,
      hasPermission: (permission) => permissions.includes(permission),
      hasAnyPermission: (values) => values.some((permission) => permissions.includes(permission)),
    },
    '../lib/attendanceApi': { fetchSupervisorInvalidAttendance: async () => [], ...apiOverrides.attendance },
    '../lib/leaveApi': { fetchSupervisorPendingLeaves: async () => [], formatLeaveBalance: () => '', ...apiOverrides.leave },
    '../lib/deviceApi': {}, '../lib/dashboardContentApi': {},
  }
  const source = readFileSync(join(__dirname, '..', 'src', 'pages', 'Dashboard.tsx'), 'utf8')
  for (const [, path] of source.matchAll(/from '([^']+)'/g)) {
    if (!path.includes('/components/') && !path.includes('/features/')) continue
    if (path in dependencies) continue
    const name = path.split('/').at(-1)
    const component = () => React.createElement('div', { 'data-component': name })
    dependencies[path] = name === 'SideCards'
      ? { AnnouncementsCard: component, HolidaysCard: component, LeaveRequestsCard: component }
      : { __esModule: true, default: component }
  }
  const Dashboard = load(join('pages', 'Dashboard.tsx'), dependencies, {
    Error,
    localStorage: { getItem: () => admin ? 'administrator' : role },
  }).default
  return () => {
    index = 0
    const tree = Dashboard({ employeeName: 'Test employee', onNavigate })
    const overview = find(tree, (node) => node.type === TeamOverview)
    return { tree, overview, html: renderToStaticMarkup(tree) }
  }
}

test('compact overview displays counts and invokes accessible review actions', () => {
  let clicked = false
  const tree = TeamOverview({
    role: 'supervisor',
    metrics: [{ id: 'hours', label: 'Hours this week', value: '32h 15m', open: false, onClick() {} }],
    reviews: [{ id: 'correction', label: 'Attendance corrections', value: 3, open: true, onClick() { clicked = true } }],
  })
  const html = renderToStaticMarkup(tree)
  assert.ok(html.includes('Review queue'))
  assert.ok(html.includes('32h 15m'))
  assert.ok(html.includes('aria-expanded="true"'))
  find(tree, (node) => node.type === 'button' && node.props['aria-expanded'] === true).props.onClick()
  assert.equal(clicked, true)
})

const permissions = ['attendance.read_team', 'leave.approve_team', 'overtime.approve_team',
  'official_business.approve_team', 'attendance.approve_corrections_team']

test('team categories retain distinct soft colors and emphasize the selected review', () => {
  const { overview } = dashboard('supervisor', permissions, true)()
  const tree = TeamOverview(overview.props)
  const html = renderToStaticMarkup(tree)
  for (const color of ['rose', 'amber', 'emerald', 'indigo', 'violet', 'sky', 'teal']) {
    assert.ok(html.includes(`bg-${color}-50`), color)
  }
  const selected = TeamOverview({
    ...overview.props,
    reviews: overview.props.reviews.map((item) => ({ ...item, open: item.id === 'correction' })),
  })
  const button = find(selected, (node) => node.type === 'button' && node.props['aria-expanded'] === true)
  assert.ok(button.props.className.includes('ring-current'))
  assert.ok(button.props.className.includes('bg-teal-50'))
})

for (const role of ['supervisor', 'manager']) {
  test(`${role} groups permitted reviews, removes hero and duplicate leave card, and collapses reports`, () => {
    const { tree, overview, html } = dashboard(role, permissions)()
    assert.deepEqual(Array.from(overview.props.reviews, (item) => item.id),
      ['leave', 'invalid', 'overtime', 'ob', 'correction', ...(role === 'supervisor' ? ['locations'] : [])])
    assert.equal(overview.props.metrics.length, 3)
    assert.equal(overview.props.metrics[0].label, 'Recorded absences')
    assert.ok(!html.includes('Missing clock-in'))
    assert.ok(!html.includes('data-component="HeroBanner"'))
    assert.ok(!html.includes('Pending Team Leave'))
    assert.equal(find(tree, (node) => node.props?.id === 'team-hours-this-week').props.hidden, true)
    const locations = find(tree, (node) => node.props?.id === 'team-punch-locations')
    assert.equal(Boolean(locations), role === 'supervisor')
    if (locations) assert.equal(locations.props.hidden, true)
  })
}

test('permission-limited team dashboard omits ungranted metrics and approval actions', () => {
  const { overview } = dashboard('manager', ['overtime.approve_team'])()
  assert.equal(overview.props.metrics.length, 0)
  assert.deepEqual(Array.from(overview.props.reviews, (item) => item.id), ['overtime'])
  const adminPreview = dashboard('supervisor', permissions, true)().overview
  assert.ok(adminPreview.props.reviews.some((item) => item.id === 'devices'))
})

test('switching every review category keeps only the selected review open; clicking again closes it', async () => {
  const render = dashboard('supervisor', permissions, true)
  for (const id of ['leave', 'invalid', 'overtime', 'ob', 'correction', 'devices', 'locations']) {
    render().overview.props.reviews.find((item) => item.id === id).onClick()
    await new Promise((resolve) => setImmediate(resolve))
    const open = render().overview.props.reviews.filter((item) => item.open)
    assert.deepEqual(Array.from(open, (item) => item.id), [id])
    assert.equal(find(render().tree, (node) => node.props?.id === 'team-punch-locations').props.hidden, id !== 'locations')
    assert.ok(render().overview.props.metrics.filter((item) => item.id !== 'hours').every((item) => !item.open))
  }
  render().overview.props.metrics.find((item) => item.id === 'missing-in').onClick()
  assert.ok(render().html.includes('Recorded team absences'))
  assert.ok(render().html.includes('Days without an attendance record are not included.'))
  assert.ok(render().overview.props.reviews.every((item) => !item.open))
  render().overview.props.reviews.find((item) => item.id === 'correction').onClick()
  assert.equal(render().overview.props.metrics.find((item) => item.id === 'missing-in').open, false)
  render().overview.props.reviews.find((item) => item.id === 'correction').onClick()
  assert.ok(render().overview.props.reviews.every((item) => !item.open))
})

test('all dashboard roles use the standard full-width form spacing', () => {
  for (const role of ['employee', 'administrator', 'supervisor', 'manager']) {
    const { tree } = dashboard(role, [], role === 'administrator')()
    const main = find(tree, (node) => node.type === 'main')
    for (const spacing of ['w-full', 'px-4', 'pt-4', 'sm:px-6', 'lg:px-8']) {
      assert.ok(main.props.className.split(' ').includes(spacing))
    }
    assert.ok(!main.props.className.includes('max-w-'))
  }
})

test('team hours participates in exclusive panels through both hours buttons', () => {
  const render = dashboard('supervisor', permissions, true)
  for (const clickHours of [
    () => render().overview.props.metrics.find((item) => item.id === 'hours').onClick(),
    () => find(render().tree, (node) => node.type === 'button' && node.props['aria-controls'] === 'team-hours-this-week').props.onClick(),
  ]) {
    for (const id of ['leave', 'invalid', 'overtime', 'ob', 'correction', 'devices', 'locations', 'missing-in', 'missing-out']) {
      clickHours()
      assert.equal(find(render().tree, (node) => node.props?.id === 'team-hours-this-week').props.hidden, false)
      assert.equal(find(render().tree, (node) => node.props?.['aria-label'] === 'Team hours details').props.hidden, false)
      const overview = render().overview
      const other = [...overview.props.reviews, ...overview.props.metrics].find((item) => item.id === id)
      other.onClick()
      assert.equal(find(render().tree, (node) => node.props?.id === 'team-hours-this-week').props.hidden, true, id)
      assert.equal(find(render().tree, (node) => node.props?.['aria-label'] === 'Team hours details').props.hidden, true, id)
      clickHours()
      assert.ok(render().overview.props.reviews.every((item) => !item.open))
      assert.ok(render().overview.props.metrics.filter((item) => item.id !== 'hours').every((item) => !item.open))
      clickHours()
      assert.equal(render().overview.props.metrics.find((item) => item.id === 'hours').open, false)
    }
  }
})

test('punch locations uses the review styling without a fabricated pending count', () => {
  const { overview } = dashboard('supervisor', permissions)()
  const item = overview.props.reviews.find((item) => item.id === 'locations')
  assert.equal(item.value, undefined)
  const button = find(TeamOverview(overview.props), (node) => node.props?.['aria-controls'] === 'team-punch-locations')
  assert.ok(button.props.className.includes('bg-cyan-50'))
  assert.ok(button.props.className.includes('border-l-4'))
})

test('all roles share the compact welcome header without duplicate overview titles or hero banners', () => {
  for (const role of ['employee', 'administrator', 'supervisor', 'manager']) {
    const { overview, html } = dashboard(role, [], role === 'administrator')()
    assert.equal(overview.props.role, role)
    assert.ok(html.includes('Welcome,'))
    assert.ok(html.includes('Test employee'))
    assert.ok(html.includes('Today'))
    assert.ok(html.includes(new Intl.DateTimeFormat('en-PH', {
      timeZone: 'Asia/Manila', weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
    }).format(new Date())))
    assert.ok(html.includes('from-indigo-950 to-violet-900'))
    assert.ok(!html.includes('My overview'))
    assert.ok(!html.includes('data-component="HeroBanner"'))
    const heading = find(TeamOverview(overview.props), (node) => node.type === 'h1')
    assert.ok(heading.props.className.includes('font-bold'))
  }
})

test('Administrator metrics and review categories are permission-filtered and mutually exclusive', () => {
  const render = dashboard('administrator', [...permissions, 'attendance.read_org'], true)
  assert.deepEqual(Array.from(render().overview.props.metrics, (item) => item.id), ['missing-in', 'missing-out', 'hours'])
  assert.deepEqual(Array.from(render().overview.props.reviews, (item) => item.id),
    ['leave', 'invalid', 'assigned-leave', 'overtime', 'ob', 'correction', 'devices', 'offline'])
  for (const id of ['leave', 'invalid', 'assigned-leave', 'overtime', 'ob', 'correction', 'devices', 'offline', 'missing-in', 'missing-out', 'hours']) {
    const overview = render().overview
    const item = [...overview.props.metrics, ...overview.props.reviews].find((item) => item.id === id)
    item.onClick()
    const updated = render().overview
    assert.deepEqual(Array.from([...updated.props.metrics, ...updated.props.reviews].filter((item) => item.open), (item) => item.id), [id])
    assert.equal(find(render().tree, (node) => node.props?.id === 'offline-attendance-review').props.hidden, id !== 'offline')
  }
  const limited = dashboard('administrator', [], true)().overview
  assert.equal(limited.props.metrics.length, 0)
  assert.deepEqual(Array.from(limited.props.reviews, (item) => item.id), ['devices', 'offline'])
  const approvalOnly = dashboard('administrator', ['leave.approve_team'], true)().overview
  assert.ok(approvalOnly.props.reviews.some((item) => item.id === 'assigned-leave'))
  assert.ok(!approvalOnly.props.reviews.some((item) => item.id === 'leave'))
})

test('assigned leave and invalid-attendance failures do not show empty approval queues', async () => {
  const render = dashboard('manager', permissions, false, undefined, {
    leave: { fetchSupervisorPendingLeaves: async () => { throw new Error('Leave unavailable') } },
    attendance: { fetchSupervisorInvalidAttendance: async () => { throw new Error('Attendance unavailable') } },
  })
  render().overview.props.reviews.find((item) => item.id === 'leave').onClick()
  await new Promise((resolve) => setImmediate(resolve))
  let page = render()
  assert.equal(page.overview.props.reviews.find((item) => item.id === 'leave').value, 'Unavailable')
  assert.match(page.html, /Leave unavailable/)
  assert.doesNotMatch(page.html, /There are no pending leave applications assigned to you/)

  page.overview.props.reviews.find((item) => item.id === 'invalid').onClick()
  await new Promise((resolve) => setImmediate(resolve))
  page = render()
  assert.equal(page.overview.props.reviews.find((item) => item.id === 'invalid').value, 'Unavailable')
  assert.match(page.html, /Attendance unavailable/)
  assert.doesNotMatch(page.html, /There are no invalid attendance records awaiting your approval/)
})

const employeePermissions = ['attendance.read_own', 'attendance.correct_own', 'leave.read_own',
  'leave.submit', 'overtime.submit_own', 'official_business.submit_own', 'payroll.read_own']

test('Employee uses the compact colored overview with permission-gated filing and navigation', () => {
  const navigated = []
  const { overview, html } = dashboard('employee', employeePermissions, false, (view) => navigated.push(view))()
  assert.equal(overview.props.role, 'employee')
  assert.equal(overview.props.employeeName, 'Test employee')
  assert.ok(html.includes('My actions &amp; records'))
  assert.ok(!html.includes('data-component="HeroBanner"'))
  assert.equal(overview.props.metrics.length, 4)
  assert.deepEqual(Array.from(overview.props.reviews.slice(0, 2), (item) => item.id), ['apply-leave', 'correction'])
  assert.equal(new Set(overview.props.reviews.map((item) => item.id)).size, overview.props.reviews.length)
  for (const id of ['apply-leave', 'overtime', 'ob', 'payroll']) {
    overview.props.reviews.find((item) => item.id === id).onClick()
  }
  assert.deepEqual(navigated, ['leave-application', 'overtime-application', 'official-business', 'payroll-review'])
  assert.ok(!html.includes('data-component="WorkHoursCard"'))
  assert.ok(!html.includes('data-component="RecentAttendanceTable"'))
})

test('Employee panels replace each other, hide on repeat selection, and expand attendance immediately', () => {
  const render = dashboard('employee', employeePermissions)
  for (const id of ['balances', 'leave', 'correction', 'attendance', 'updates']) {
    const item = render().overview.props.reviews.find((item) => item.id === id && item.controls)
    item.onClick()
    assert.ok(find(render().tree, (node) => node.props?.id === item.controls))
    assert.deepEqual(Array.from(render().overview.props.reviews.filter((item) => item.open), (item) => item.id), [id])
    if (id === 'attendance') {
      const table = find(render().tree, (node) => node.props?.initiallyExpanded)
      assert.equal(table.props.initiallyExpanded, true)
    }
  }
  render().overview.props.metrics.find((item) => item.id === 'hours').onClick()
  assert.ok(find(render().tree, (node) => node.props?.id === 'employee-hours'))
  assert.equal(find(render().tree, (node) => node.props?.id === 'employee-updates'), null)
  render().overview.props.metrics.find((item) => item.id === 'hours').onClick()
  assert.equal(find(render().tree, (node) => node.props?.id === 'employee-hours'), null)
  assert.ok(render().overview.props.metrics.every((item) => !item.open))
})

test('Employee without module rights sees no restricted actions, metrics, or panels', () => {
  const { overview, html } = dashboard('employee', [])()
  assert.equal(overview.props.metrics.length, 0)
  assert.deepEqual(Array.from(overview.props.reviews, (item) => item.id), ['updates'])
  for (const name of ['LeaveBalanceGrid', 'WorkHoursCard', 'RecentAttendanceTable', 'AttendanceCorrectionsPanel']) {
    assert.ok(!html.includes(`data-component="${name}"`))
  }
  const correctionsOnly = dashboard('employee', ['attendance.correct_own'])()
  assert.ok(correctionsOnly.overview.props.reviews.some((item) => item.id === 'correction'))
  assert.ok(!correctionsOnly.overview.props.reviews.some((item) => item.id === 'leave'))
})

test('employee approvers can open assigned reviews without leaving another employee panel open', async () => {
  const render = dashboard('employee', [...employeePermissions, ...permissions])
  const expected = ['review-leave', 'review-invalid', 'review-overtime', 'review-ob', 'review-correction']
  assert.deepEqual(
    Array.from(render().overview.props.reviews.filter((item) => item.id.startsWith('review-')), (item) => item.id),
    expected,
  )
  render().overview.props.reviews.find((item) => item.id === 'balances').onClick()
  assert.ok(find(render().tree, (node) => node.props?.id === 'employee-balances'))
  for (const id of expected) {
    render().overview.props.reviews.find((item) => item.id === id).onClick()
    await new Promise((resolve) => setImmediate(resolve))
    assert.equal(find(render().tree, (node) => node.props?.id === 'employee-balances'), null)
    assert.deepEqual(Array.from(render().overview.props.reviews.filter((item) => item.open), (item) => item.id), [id])
  }
  render().overview.props.reviews.find((item) => item.id === 'balances').onClick()
  assert.deepEqual(Array.from(render().overview.props.reviews.filter((item) => item.open), (item) => item.id), ['balances'])
})

test('routing alert lookup is available to HR and employee request owners', () => {
  const permitted = dashboard('employee', ['employees.manage'])()
  const denied = dashboard('employee', [])()
  assert.ok(permitted.html.includes('data-component="UnresolvedAttendanceApprovals"'))
  assert.ok(denied.html.includes('data-component="UnresolvedAttendanceApprovals"'))
})

test('Recent Attendance preserves its collapsed default and supports immediate dashboard expansion', () => {
  const Table = load(join('components', 'dashboard', 'RecentAttendanceTable.tsx')).default
  const entries = [{ date: '2026-10-12', status: 'present', timeIn: null, timeOut: null }]
  const collapsed = renderToStaticMarkup(React.createElement(Table, { entries }))
  assert.ok(!collapsed.includes('<table'))
  const expanded = renderToStaticMarkup(React.createElement(Table, { entries, initiallyExpanded: true }))
  assert.ok(expanded.includes('<table'))
  assert.ok(expanded.includes('aria-expanded="true"'))
})

test('overview distinguishes unloaded counts, navigation buttons, and pending review emphasis', () => {
  const employee = TeamOverview({
    role: 'employee', metrics: [],
    reviews: [
      { id: 'apply-leave', label: 'Apply for Leave', open: false, onClick() {} },
      { id: 'leave', label: 'My leave requests', value: '—', open: false, controls: 'employee-leave', onClick() {} },
    ],
  })
  const action = find(employee, (node) => node.type === 'button' && node.props['aria-controls'] === undefined)
  assert.equal(action.props['aria-expanded'], undefined)
  const html = renderToStaticMarkup(employee)
  assert.ok(html.includes('Not loaded'))
  assert.ok(html.includes('Arrow buttons open a module'))
  const review = TeamOverview({
    role: 'supervisor', metrics: [],
    reviews: [{ id: 'leave', label: 'Leave', value: 3, open: false, onClick() {} }],
  })
  assert.ok(renderToStaticMarkup(review).includes('bg-white ring-1 ring-current'))
  const loading = TeamOverview({
    role: 'supervisor', metrics: [],
    reviews: [{ id: 'leave', label: 'Leave', value: '…', open: false, onClick() {} }],
  })
  assert.ok(renderToStaticMarkup(loading).includes('Loading...'))
})

test('approval panels do not present a failed load as zero pending or an empty success state', () => {
  const deadlines = { __esModule: true, default: () => null }
  const Overtime = load(join('components', 'dashboard', 'OvertimeApprovalsPanel.tsx'), {
    '../common/AttendanceDeadlines': deadlines,
  }).default
  const overtimeHtml = renderToStaticMarkup(React.createElement(Overtime, {
    requests: [], isLoading: false, error: 'Request failed', savingId: null, onDecision() {},
  }))
  assert.ok(overtimeHtml.includes('Unavailable'))
  assert.ok(overtimeHtml.includes('Request failed'))
  assert.ok(!overtimeHtml.includes('0 pending'))
  assert.ok(!overtimeHtml.includes('There are no pending'))
  let index = 0
  const values = [[], {}, false, null, 'Request failed', null]
  const OfficialBusiness = load(join('components', 'dashboard', 'OfficialBusinessApprovalsPanel.tsx'), {
    react: { ...React, useEffect() {}, useState: () => [values[index++], () => {}] },
    '../common/AttendanceDeadlines': deadlines,
    '../../lib/officialBusinessApi': {},
  }).default
  const obHtml = renderToStaticMarkup(OfficialBusiness({}))
  assert.ok(obHtml.includes('Unavailable'))
  assert.ok(!obHtml.includes('0 pending'))
  assert.ok(!obHtml.includes('There are no pending'))
})

test('leave balance and offline review failures do not show misleading empty messages', () => {
  const Balances = load(join('components', 'dashboard', 'LeaveBalanceGrid.tsx'), {
    '../../lib/leaveApi': {},
  }).default
  const balancesHtml = renderToStaticMarkup(React.createElement(Balances, {
    balances: [], error: 'Request failed',
  }))
  assert.ok(balancesHtml.includes('Request failed'))
  assert.ok(!balancesHtml.includes('No leave entitlements'))
  let index = 0
  const values = [[], true, false, 'Request failed', {}]
  const Offline = load(join('features', 'attendance', 'OfflineAttendanceReviewPanel.tsx'), {
    react: { ...React, useState: () => [values[index++], () => {}] },
    '../../lib/offlineAttendanceApi': {},
    '../../lib/apiClient': {},
  }).default
  const offlineHtml = renderToStaticMarkup(Offline())
  assert.ok(offlineHtml.includes('Request failed'))
  assert.ok(!offlineHtml.includes('No pending offline review events'))
})
