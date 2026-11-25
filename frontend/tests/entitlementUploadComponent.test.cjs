const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const ts = require('typescript')

const balances = {
  opening_minutes: 0,
  granted_minutes: 5760,
  accrued_minutes: 0,
  carryover_minutes: 0,
  adjustment_minutes: 0,
  used_minutes: 960,
  reserved_minutes: 0,
  expired_minutes: 0,
  converted_minutes: 0,
  available_minutes: 4800,
}

function validPreview() {
  return {
    is_valid: true,
    error_count: 0,
    file_errors: [],
    preview_token: 'a'.repeat(64),
    rows: [{
      row_no: 2,
      employee_no: '0001',
      employee_name: 'Ana Cruz',
      leave_code: 'VL',
      leave_name: 'Vacation',
      entitlement_year: 2026,
      unit_type: 'DAYS',
      action: 'UPDATE',
      errors: [],
      before: { ...balances, used_minutes: 480, available_minutes: 4320 },
      after: { ...balances },
    }],
  }
}

function createHarness(overrides = {}) {
  const cells = []
  let hook = 0
  const calls = []
  const stateHooks = {
    useId: () => { hook += 1; return 'upload-panel' },
    useRef: (initial) => {
      const index = hook++
      if (!(index in cells)) cells[index] = { current: initial }
      return cells[index]
    },
    useState: (initial) => {
      const index = hook++
      if (!(index in cells)) cells[index] = typeof initial === 'function' ? initial() : initial
      return [cells[index], (next) => {
        cells[index] = typeof next === 'function' ? next(cells[index]) : next
      }]
    },
  }
  const api = {
    downloadEntitlementUploadTemplate: async () => new Blob(['csv']),
    previewEntitlementUpload: async (file) => { calls.push(['preview', file]); return validPreview() },
    applyEntitlementUpload: async (file, token) => {
      calls.push(['apply', file, token])
      return { created: 0, updated: 1, employee_ids: ['employee'], entitlement_ids: ['entitlement'] }
    },
    ...overrides.api,
  }
  const onUploaded = overrides.onUploaded ?? (async (result) => { calls.push(['refresh', result]) })
  const source = readFileSync(join(__dirname, '..', 'src', 'features', 'employees', 'EntitlementUpload.tsx'), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText
  const exports = {}
  runInNewContext(code, {
    exports, Error,
    require: (name) => {
      if (name === 'react') return stateHooks
      if (name === 'lucide-react') return { Download: () => null, Upload: () => null }
      if (name === '../../lib/entitlementUploadApi') return api
      if (name === '../../lib/leaveApi') return { formatLeaveBalance: (value, unit) => `${value} ${unit}` }
      return require(name)
    },
  })
  return {
    calls,
    render() {
      hook = 0
      return exports.default({ children: 'Employee entitlements', onUploaded, navigationControlled: overrides.navigationControlled })
    },
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

function text(node) {
  if (Array.isArray(node)) return node.map(text).join('')
  if (typeof node === 'string') return node
  return React.isValidElement(node) ? text(node.props.children) : ''
}

function button(tree, label) {
  const result = find(tree, (element) => element.type === 'button' && text(element).includes(label))
  assert.ok(result, `Button not found: ${label}`)
  return result
}

function fileInput(tree) {
  const result = find(tree, (element) => element.type === 'input' && element.props.type === 'file')
  assert.ok(result, 'File input not found')
  return result
}

function settle() {
  return new Promise((resolve) => setImmediate(resolve))
}

test('upload controls review a multi-employee file and refresh after applying', async () => {
  const harness = createHarness()
  let tree = harness.render()
  assert.match(renderToStaticMarkup(tree), /Download template/)
  button(tree, 'Upload entitlements').props.onClick()
  tree = harness.render()
  const initial = renderToStaticMarkup(tree)
  assert.match(initial, /multiple employees/)
  assert.match(initial, /including used and reserved balances/)
  assert.equal(button(tree, 'Apply entitlements').props.disabled, true)

  const file = new File(['csv-data'], 'balances.csv')
  fileInput(tree).props.onChange({ target: { files: [file] } })
  tree = harness.render()
  button(tree, 'Check file').props.onClick()
  await settle()
  tree = harness.render()
  const preview = renderToStaticMarkup(tree)
  assert.match(preview, /Ana Cruz/)
  assert.match(preview, /Update/)
  assert.match(preview, /Review all balances/)
  assert.match(preview, /4320 DAYS/)
  assert.match(preview, /4800 DAYS/)
  assert.equal(button(tree, 'Apply entitlements').props.disabled, false)

  button(tree, 'Apply entitlements').props.onClick()
  await settle()
  tree = harness.render()
  assert.match(renderToStaticMarkup(tree), /0 created and 1 updated/)
  assert.equal(harness.calls[1][0], 'apply')
  assert.equal(harness.calls[1][1], file)
  assert.equal(harness.calls[1][2], 'a'.repeat(64))
  assert.equal(harness.calls[2][0], 'refresh')
  assert.equal(button(tree, 'Apply entitlements').props.disabled, true)
})

test('navigation-controlled entitlement upload opens directly and keeps its template and review flow', () => {
  const tree = createHarness({ navigationControlled: true }).render()
  assert.ok(find(tree, (element) => element.props['aria-label'] === 'Upload entitlements'))
  assert.ok(find(tree, (element) => element.type === 'button' && text(element).includes('Download template')))
  assert.equal(find(tree, (element) => element.type === 'button' && text(element).includes('Upload entitlements')), null)
})

test('changing the selected file invalidates the previous preview', async () => {
  const harness = createHarness()
  button(harness.render(), 'Upload entitlements').props.onClick()
  let tree = harness.render()
  fileInput(tree).props.onChange({ target: { files: [new File(['first'], 'first.csv')] } })
  tree = harness.render()
  button(tree, 'Check file').props.onClick()
  await settle()
  tree = harness.render()
  assert.equal(button(tree, 'Apply entitlements').props.disabled, false)
  fileInput(tree).props.onChange({ target: { files: [new File(['second'], 'second.csv')] } })
  tree = harness.render()
  assert.equal(button(tree, 'Apply entitlements').props.disabled, true)
  assert.doesNotMatch(renderToStaticMarkup(tree), /All 1 row/)
})

test('a stale upload requires checking again and does not report success', async () => {
  const harness = createHarness({
    api: { applyEntitlementUpload: async () => { throw new Error('Balances changed. Check the file again.') } },
  })
  button(harness.render(), 'Upload entitlements').props.onClick()
  let tree = harness.render()
  fileInput(tree).props.onChange({ target: { files: [new File(['csv'], 'balances.csv')] } })
  tree = harness.render()
  button(tree, 'Check file').props.onClick()
  await settle()
  tree = harness.render()
  button(tree, 'Apply entitlements').props.onClick()
  await settle()
  tree = harness.render()
  const html = renderToStaticMarkup(tree)
  assert.match(html, /Balances changed. Check the file again./)
  assert.doesNotMatch(html, /Upload completed/)
  assert.equal(button(tree, 'Apply entitlements').props.disabled, true)
})

test('a failed refresh reports that the upload was saved rather than reporting an upload failure', async () => {
  const harness = createHarness({ onUploaded: async () => { throw new Error('Network unavailable') } })
  button(harness.render(), 'Upload entitlements').props.onClick()
  let tree = harness.render()
  fileInput(tree).props.onChange({ target: { files: [new File(['csv'], 'balances.csv')] } })
  tree = harness.render()
  button(tree, 'Check file').props.onClick()
  await settle()
  tree = harness.render()
  button(tree, 'Apply entitlements').props.onClick()
  await settle()
  const html = renderToStaticMarkup(harness.render())
  assert.match(html, /Upload completed: 0 created and 1 updated/)
  assert.match(html, /displayed balances could not be refreshed: Network unavailable/)
})

function createEntitlementPanelHarness(deleteEntitlement = async () => {}) {
  const cells = []
  let hook = 0
  let confirmed = false
  let deferRefresh = false
  let resolveRefresh
  const listeners = {}
  const calls = []
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
    useEffect(effect) {
      const index = hook++
      if (!(index in cells)) {
        cells[index] = true
        effect()
      }
    },
  }
  const entitlement = {
    id: 'entitlement', employee_id: 'employee', leave_type_id: 'leave',
    entitlement_year: 2026, ...balances, last_calculated_at: null,
  }
  const leaveType = {
    id: 'leave', leave_name: 'Vacation', leave_code: 'VL', unit_type: 'DAYS',
    is_active: true, status: 'ACTIVE', effective_from: '2020-01-01', effective_to: null,
    minimum_service_months: 0,
  }
  const api = {
    fetchEmployeeEntitlements: async () => {
      if (deferRefresh) {
        deferRefresh = false
        return new Promise((resolve) => { resolveRefresh = resolve })
      }
      return [entitlement]
    },
    fetchLeaveTypes: async () => [leaveType],
    deleteEmployeeEntitlement: async (id) => {
      calls.push(id)
      return deleteEntitlement(id)
    },
    formatLeaveBalance: (value) => String(value),
    calculateAvailableMinutes: () => 0,
    minutesToLeaveUnits: (value) => value,
    leaveUnitsToMinutes: (value) => value,
  }
  const related = {
    fetchEmploymentAssignments: async () => [{ company_id: 'company', hire_date: '2020-01-01' }],
    isCurrentEmploymentAssignment: () => true,
    getCompletedServiceMonths: () => 12,
    getManilaDate: () => '2026-11-25',
  }
  const source = readFileSync(join(__dirname, '..', 'src', 'features', 'employees', 'EmployeeEntitlementsPanel.tsx'), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const exports = {}
  runInNewContext(code, {
    exports, Error,
    window: {
      confirm: () => confirmed,
      setInterval: () => 1,
      addEventListener: (name, callback) => { listeners[name] = callback },
      removeEventListener: () => {},
    },
    require(name) {
      if (name === 'react') return hooks
      if (name === 'lucide-react') return { Pencil: () => null, Plus: () => null, Trash2: () => null, X: () => null }
      if (name === '../../components/common/SearchableSelect') return { __esModule: true, default: () => null }
      if (name === '../../lib/employeeRelatedApi') return related
      if (name === '../../lib/leaveApi') return api
      return require(name)
    },
  })
  return {
    calls,
    confirm(value) { confirmed = value },
    startStaleRefresh() {
      deferRefresh = true
      listeners.focus()
    },
    finishStaleRefresh() { resolveRefresh([entitlement]) },
    render() {
      hook = 0
      return exports.default({ employee: { id: 'employee', employee_no: '0001' }, isActive: true })
    },
  }
}

test('entitlement deletion requires confirmation and removes the deleted row', async () => {
  const harness = createEntitlementPanelHarness()
  harness.render()
  await settle()
  let tree = harness.render()
  find(tree, (element) => element.props['aria-label'] === 'Delete entitlement').props.onClick()
  assert.deepEqual(harness.calls, [])
  harness.confirm(true)
  tree = harness.render()
  find(tree, (element) => element.props['aria-label'] === 'Delete entitlement').props.onClick()
  await settle()
  tree = harness.render()
  assert.deepEqual(harness.calls, ['entitlement'])
  assert.equal(find(tree, (element) => element.props['aria-label'] === 'Delete entitlement'), null)
  assert.match(text(tree), /Entitlement deleted/)
})

test('a protected entitlement remains visible and shows the server error', async () => {
  const harness = createEntitlementPanelHarness(async () => { throw new Error('This entitlement has leave activity.') })
  harness.render()
  await settle()
  harness.confirm(true)
  find(harness.render(), (element) => element.props['aria-label'] === 'Delete entitlement').props.onClick()
  await settle()
  const tree = harness.render()
  assert.ok(find(tree, (element) => element.props['aria-label'] === 'Delete entitlement'))
  assert.match(text(tree), /This entitlement has leave activity/)
})

test('a refresh started before deletion cannot restore the removed entitlement', async () => {
  const harness = createEntitlementPanelHarness()
  harness.render()
  await settle()
  harness.startStaleRefresh()
  harness.confirm(true)
  find(harness.render(), (element) => element.props['aria-label'] === 'Delete entitlement').props.onClick()
  await settle()
  harness.finishStaleRefresh()
  await settle()
  assert.equal(find(harness.render(), (element) => element.props['aria-label'] === 'Delete entitlement'), null)
})
