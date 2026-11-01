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
      return exports.default({ children: 'Employee entitlements', onUploaded })
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
