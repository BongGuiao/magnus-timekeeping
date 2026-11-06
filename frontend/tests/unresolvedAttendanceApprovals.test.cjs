const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const axios = require('axios')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const ts = require('typescript')

const record = {
  id: 'attendance-1',
  employee_name: 'Synthetic Employee',
  employee_code: 'E001',
  work_date: '2026-11-04',
  routing_error: 'No manager configured.',
  resource_type: 'invalid_attendance', resource_id: 'attendance-1', created_at: '2026-11-04T00:00:00Z',
}

function harness({ fetchRecords, retry, canSetup = true, canManage = true, approvers = [], onNavigate } = {}) {
  const cells = []
  const pendingEffects = []
  let hook = 0
  let poll
  const hooks = {
    useState(initial) {
      const index = hook++
      if (!(index in cells)) cells[index] = typeof initial === 'function' ? initial() : initial
      return [cells[index], (next) => {
        cells[index] = typeof next === 'function' ? next(cells[index]) : next
      }]
    },
    useRef(initial) {
      const index = hook++
      if (!(index in cells)) cells[index] = { current: initial }
      return cells[index]
    },
    useEffect(effect, dependencies) {
      const index = hook++
      const previous = cells[index]
      if (!previous || dependencies.some((value, i) => value !== previous.dependencies[i])) {
        if (previous?.cleanup) previous.cleanup()
        pendingEffects.push(() => {
          cells[index] = { dependencies, cleanup: effect() }
        })
      }
    },
  }
  const source = readFileSync(join(__dirname, '..', 'src', 'features', 'attendance', 'UnresolvedAttendanceApprovals.tsx'), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const exports = {}
  runInNewContext(code, {
    exports, Error,
    window: {
      setInterval(callback) { poll = callback; return 1 },
      clearInterval() {},
    },
    require(name) {
      if (name === 'react') return hooks
      if (name === '../../lib/attendanceApi') return {
        fetchUnresolvedApprovals: async () => ({
          records: await (fetchRecords || (async () => [record]))(), can_manage: canManage, approvers,
        }),
        recoverUnresolvedApproval: retry || (async () => {}),
      }
      if (name === '../../types/role') return { hasPermission: () => canSetup }
      return require(name)
    },
  })
  return {
    render() {
      hook = 0
      const tree = exports.default({ onNavigate })
      while (pendingEffects.length) pendingEffects.shift()()
      return tree
    },
    poll() { return poll() },
  }
}

function find(node, predicate) {
  if (Array.isArray(node)) {
    for (const child of node) {
      const match = find(child, predicate)
      if (match) return match
    }
    return null
  }
  if (!React.isValidElement(node)) return null
  if (predicate(node)) return node
  return find(node.props.children, predicate)
}

function button(tree, label) {
  const result = find(tree, (element) => element.type === 'button'
    && React.Children.toArray(element.props.children).join('').includes(label))
  assert.ok(result, `Button not found: ${label}`)
  return result
}

const settle = () => new Promise((resolve) => setImmediate(resolve))

function loadApi(client) {
  const source = readFileSync(join(__dirname, '..', 'src', 'lib', 'attendanceApi.ts'), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  runInNewContext(code, {
    exports, Error,
    require(name) {
      if (name === './apiClient') return { apiClient: client }
      if (name === './attendanceDevice') return {}
      return require(name)
    },
  })
  return exports
}

test('missing backend endpoint reports a deployment mismatch instead of a missing approver', async () => {
  const requests = []
  const api = loadApi({
    async get(path) {
      requests.push(path)
      throw new axios.AxiosError('Not Found', 'ERR_BAD_REQUEST', {}, {}, {
        status: 404, data: { detail: 'Not Found' },
      })
    },
  })
  await assert.rejects(api.fetchUnresolvedAttendanceApprovals(), /database upgrade.*matching backend version/)
  assert.deepEqual(requests, ['/attendance/hr/unresolved-attendance-approvals'])
})

test('non-404 API failures retain the server error rather than suggesting deployment', async () => {
  const api = loadApi({
    async get() {
      throw new axios.AxiosError('Forbidden', 'ERR_BAD_REQUEST', {}, {}, {
        status: 403, data: { detail: 'Permission denied.' },
      })
    },
  })
  await assert.rejects(api.fetchUnresolvedAttendanceApprovals(), /Permission denied/)
})

test('alert displays the recorded punch, links setup, and removes it after successful retry', async () => {
  let finishRetry
  let routed = false
  const retried = []
  const navigated = []
  const view = harness({
    fetchRecords: async () => routed ? [] : [record],
    retry: (id) => {
      retried.push(id)
      return new Promise((resolve) => { finishRetry = () => { routed = true; resolve() } })
    },
    onNavigate: (target) => navigated.push(target),
  })
  assert.equal(view.render(), null)
  await settle()
  let tree = view.render()
  const html = renderToStaticMarkup(tree)
  assert.match(html, /Synthetic Employee/)
  assert.match(html, /No manager configured/)
  button(tree, 'Open org units').props.onClick()
  assert.deepEqual(navigated, ['org-units'])
  button(tree, 'Retry routing').props.onClick()
  tree = view.render()
  assert.equal(button(tree, 'Retrying').props.disabled, true)
  finishRetry()
  await settle()
  assert.deepEqual(retried, ['attendance-1'])
  assert.equal(view.render(), null)
  await settle()
  assert.equal(view.render(), null)
})

test('a stale poll cannot restore an alert after successful routing', async () => {
  let loads = 0
  let finishPoll
  const view = harness({
    fetchRecords: () => {
      loads += 1
      if (loads === 2) return new Promise((resolve) => { finishPoll = resolve })
      return Promise.resolve(loads === 1 ? [record] : [])
    },
  })
  view.render()
  await settle()
  view.poll()
  button(view.render(), 'Retry routing').props.onClick()
  await settle()
  assert.equal(view.render(), null)
  finishPoll([record])
  await settle()
  assert.equal(loads, 3)
  assert.equal(view.render(), null)
})

test('failed retry keeps the alert, reports the error, and reloads the routing message', async () => {
  let loads = 0
  const view = harness({
    canSetup: false,
    fetchRecords: async () => { loads += 1; return [record] },
    retry: async () => { throw new Error('Manager still lacks permission.') },
  })
  view.render()
  await settle()
  let tree = view.render()
  assert.doesNotMatch(renderToStaticMarkup(tree), /Open org units/)
  button(tree, 'Retry routing').props.onClick()
  await settle()
  view.render()
  await settle()
  tree = view.render()
  const html = renderToStaticMarkup(tree)
  assert.match(html, /Manager still lacks permission/)
  assert.match(html, /Synthetic Employee/)
  assert.equal(loads, 2)
})

test('failed alert load is visible and polling can recover', async () => {
  let loads = 0
  const view = harness({
    fetchRecords: async () => {
      loads += 1
      if (loads === 1) throw new Error('Alerts unavailable.')
      return [record]
    },
  })
  view.render()
  await settle()
  const failed = view.render()
  const failedHtml = renderToStaticMarkup(failed)
  assert.match(failedHtml, /Alerts unavailable/)
  assert.match(failedHtml, /Approval routing alerts unavailable/)
  assert.doesNotMatch(failedHtml, /Requests need an approver|These punches were recorded|Open org units/)
  view.poll()
  await settle()
  const html = renderToStaticMarkup(view.render())
  assert.match(html, /Synthetic Employee/)
  assert.doesNotMatch(html, /Alerts unavailable/)
})

test('failed lookup can be retried without treating it as missing approver configuration', async () => {
  let loads = 0
  const view = harness({
    onNavigate() {},
    fetchRecords: async () => {
      loads += 1
      if (loads === 1) throw new Error('Backend upgrade required.')
      return []
    },
  })
  view.render()
  await settle()
  const failed = view.render()
  assert.doesNotMatch(renderToStaticMarkup(failed), /Open org units|These punches were recorded/)
  button(failed, 'Retry loading alerts').props.onClick()
  view.render()
  await settle()
  assert.equal(view.render(), null)
  assert.equal(loads, 2)
})

test('a refresh failure preserves confirmed unresolved records and setup actions', async () => {
  let loads = 0
  const view = harness({
    onNavigate() {},
    fetchRecords: async () => {
      loads += 1
      if (loads > 1) throw new Error('Refresh failed.')
      return [record]
    },
  })
  view.render()
  await settle()
  view.poll()
  await settle()
  const html = renderToStaticMarkup(view.render())
  assert.match(html, /Requests need an approver/)
  assert.match(html, /Synthetic Employee/)
  assert.match(html, /Open org units/)
  assert.match(html, /Refresh failed/)
})

test('request owners see held requests but cannot retry or assign reviewers', async () => {
  const view = harness({ canManage: false, onNavigate() {} })
  view.render()
  await settle()
  const html = renderToStaticMarkup(view.render())
  assert.match(html, /Contact HR/)
  assert.match(html, /Invalid attendance/)
  assert.doesNotMatch(html, /Retry routing|Assign approver|Open org units|Select an independent manager/)
})

test('HR exceptional assignment requires a reason and sends the selected manager', async () => {
  const assignments = []
  const view = harness({
    approvers: [{ employee_id: 'manager-2', label: 'Independent Manager' }],
    retry: async (...args) => { assignments.push(args); throw new Error('Manager is not independent.') },
  })
  view.render()
  await settle()
  let tree = view.render()
  find(tree, (element) => element.type === 'select').props.onChange({ target: { value: 'manager-2' } })
  tree = view.render()
  assert.equal(button(tree, 'Assign approver').props.disabled, true)
  find(tree, (element) => element.type === 'input').props.onChange({ target: { value: 'Covering absence' } })
  tree = view.render()
  assert.equal(button(tree, 'Assign approver').props.disabled, false)
  button(tree, 'Assign approver').props.onClick()
  await settle()
  view.render()
  await settle()
  assert.deepEqual(assignments, [['attendance-1', 'manager-2', 'Covering absence']])
  assert.match(renderToStaticMarkup(view.render()), /Manager is not independent/)
})

test('all seven approval resource types have readable alert labels', async () => {
  const types = [
    'overtime_application', 'leave_application', 'official_business_request',
    'attendance_correction', 'invalid_attendance', 'emergency_schedule_request', 'schedule_upload_batch',
  ]
  const view = harness({
    fetchRecords: async () => types.map((resource_type, index) => ({ ...record, id: String(index), resource_type })),
  })
  view.render()
  await settle()
  const html = renderToStaticMarkup(view.render())
  for (const label of ['Overtime', 'Leave', 'Official business', 'Attendance correction', 'Invalid attendance', 'Emergency schedule', 'Schedule upload']) {
    assert.ok(html.includes(label), label)
  }
})

test('generic recovery treats an unresolved success envelope as failure', async () => {
  const requests = []
  const api = loadApi({
    async post(url, data) {
      requests.push({ url, data })
      return { data: { status: 'success', data: { routing_mode: 'UNRESOLVED', routing_error: 'Parent manager missing.' } } }
    },
  })
  await assert.rejects(api.recoverUnresolvedApproval('route-1'), /Parent manager missing/)
  assert.deepEqual(JSON.parse(JSON.stringify(requests)), [{
    url: '/attendance/approval-routing/route-1/recover', data: { approver_employee_id: null, reason: null },
  }])
})

test('generic routing API returns records and manager options and sends audited overrides', async () => {
  const payload = { records: [record], approvers: [], can_manage: true }
  const api = loadApi({
    async get(url) {
      assert.equal(url, '/attendance/approval-routing/unresolved')
      return { data: { status: 'success', data: payload } }
    },
    async post(url, data) {
      assert.equal(url, '/attendance/approval-routing/route-2/recover')
      assert.deepEqual(JSON.parse(JSON.stringify(data)), { approver_employee_id: 'manager-2', reason: 'Cover manager' })
      return { data: { status: 'success', data: { routing_mode: 'ORG_UNIT', routing_error: null } } }
    },
  })
  assert.deepEqual(await api.fetchUnresolvedApprovals(), payload)
  await api.recoverUnresolvedApproval('route-2', 'manager-2', 'Cover manager')
})
