const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const ts = require('typescript')

const source = readFileSync(join(__dirname, '..', 'src', 'features', 'employees', 'LeaveApprovalReversal.tsx'), 'utf8')
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText
const headerExports = {}
runInNewContext(ts.transpileModule(readFileSync(join(__dirname, '..', 'src', 'components', 'common', 'SortHeader.tsx'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText, { exports: headerExports, require })
const SortHeader = headerExports.default

function harness(returnLeave, fetchLeave = async () => ({ items: [{
  id: 'leave-1', application_no: 'LV-1', employee_no: 'E1', employee_name: 'Employee',
  leave_type: 'Vacation', start_at: '2026-12-01T09:00:00+08:00',
  end_at: '2026-12-01T18:00:00+08:00', paid_minutes: 480,
}], next_offset: null }), overtime = {}) {
  const cells = []
  let hook = 0
  const dependencies = {
    react: {
      useState(initial) {
        const index = hook++
        if (!(index in cells)) cells[index] = typeof initial === 'function' ? initial() : initial
        return [cells[index], (value) => { cells[index] = typeof value === 'function' ? value(cells[index]) : value }]
      },
    },
    '../../lib/employeeRelatedApi': { getManilaDate: () => '2026-12-01' },
    '../../lib/attendanceApi': overtime,
    '../../components/common/SortHeader': { __esModule: true, default: SortHeader },
    '../../lib/leaveApi': {
      fetchApprovedLeaveForReversal: fetchLeave,
      returnLeaveForApproval: returnLeave,
    },
  }
  const exports = {}
  runInNewContext(code, {
    exports, Error, window: { confirm: () => true },
    require: (name) => name in dependencies ? dependencies[name] : require(name),
  })
  return (props) => { hook = 0; return exports.default(props) }
}

function find(node, predicate) {
  if (Array.isArray(node)) return node.map((item) => find(item, predicate)).find(Boolean)
  if (!React.isValidElement(node)) return null
  if (predicate(node)) return node
  if (node.type === SortHeader) return find(node.type(node.props), predicate)
  return find(node.props.children, predicate)
}

const settle = () => new Promise((resolve) => setImmediate(resolve))

test('requires a reason and returns the selected approved leave', async () => {
  const calls = []
  const render = harness(async (...args) => { calls.push(args) })
  let tree = render()
  find(tree, (node) => node.type === 'form').props.onSubmit({ preventDefault() {} })
  await settle()
  tree = render()
  find(tree, (node) => node.type === 'button' && node.props.children === 'Select').props.onClick()
  tree = render()
  let button = find(tree, (node) => node.type === 'button' && node.props.children === 'Return for approval')
  assert.equal(button.props.disabled, true)
  find(tree, (node) => node.type === 'textarea').props.onChange({ target: { value: '  Wrong dates  ' } })
  tree = render()
  button = find(tree, (node) => node.type === 'button' && node.props.children === 'Return for approval')
  button.props.onClick()
  await settle()
  tree = render()
  assert.deepEqual(calls, [['leave-1', 'Wrong dates']])
  assert.match(renderToStaticMarkup(tree), /was returned for approval/)
})

test('shows a reversal failure without claiming success', async () => {
  const render = harness(async () => { throw new Error('Cutoff is closed') })
  let tree = render()
  find(tree, (node) => node.type === 'form').props.onSubmit({ preventDefault() {} })
  await settle()
  tree = render()
  find(tree, (node) => node.type === 'button' && node.props.children === 'Select').props.onClick()
  tree = render()
  find(tree, (node) => node.type === 'textarea').props.onChange({ target: { value: 'Correction' } })
  tree = render()
  find(tree, (node) => node.type === 'button' && node.props.children === 'Return for approval').props.onClick()
  await settle()
  const html = renderToStaticMarkup(render())
  assert.match(html, /Cutoff is closed/)
  assert.doesNotMatch(html, /was returned for approval/)
})

test('sorting reloads from page one and keeps the selected order across pages', async () => {
  const calls = []
  const render = harness(async () => {}, async (...args) => {
    calls.push(args)
    return { items: [{
      id: 'leave-1', application_no: 'LV-1', employee_no: 'E1', employee_name: 'Employee',
      leave_type: 'Vacation', start_at: '2026-12-01T09:00:00+08:00',
      end_at: '2026-12-01T18:00:00+08:00', paid_minutes: 480,
    }], next_offset: args[2] === 0 ? 25 : null }
  })

  let tree = render()
  find(tree, (node) => node.type === 'form').props.onSubmit({ preventDefault() {} })
  await settle()
  tree = render()
  find(tree, (node) => node.type === 'button' && node.props.children === 'Next').props.onClick()
  await settle()
  tree = render()
  find(tree, (node) => node.type === 'button' && node.props['aria-label']?.startsWith('Sort by Employee')).props.onClick()
  await settle()
  tree = render()
  assert.match(renderToStaticMarkup(tree), /Page 1/)
  find(tree, (node) => node.type === 'button' && node.props.children === 'Next').props.onClick()
  await settle()
  tree = render()
  find(tree, (node) => node.type === 'button' && node.props['aria-label']?.startsWith('Sort by Employee')).props.onClick()
  await settle()
  assert.deepEqual(calls.map((args) => args.slice(2)), [
    [0, 'coverage', 'desc'], [25, 'coverage', 'desc'], [0, 'employee', 'asc'], [25, 'employee', 'asc'], [0, 'employee', 'desc'],
  ])
})

test('overtime includes rest-day work, sorts across pages and returns with a reason', async () => {
  const calls = []
  const returned = []
  const render = harness(async () => {}, undefined, {
    fetchApprovedOvertimeForReturn: async (...args) => {
      calls.push(args)
      return { items: [{
        id: 'ot-1', application_no: 'OT-1', employee_no: 'E1', employee_name: 'Employee',
        overtime_type: 'REST_DAY_WORK', attendance_date: '2026-12-01', payable_minutes: 480,
      }], next_offset: args[2] === 0 ? 25 : null }
    },
    returnOvertimeForApproval: async (...args) => returned.push(args),
  })
  const view = () => render({ mode: 'overtime' })
  let tree = view()
  find(tree, (node) => node.type === 'form').props.onSubmit({ preventDefault() {} })
  await settle()
  tree = view()
  assert.match(renderToStaticMarkup(tree), /REST DAY WORK/)
  find(tree, (node) => node.type === 'button' && node.props['aria-label']?.startsWith('Sort by Type')).props.onClick()
  await settle()
  tree = view()
  find(tree, (node) => node.type === 'button' && node.props.children === 'Next').props.onClick()
  await settle()
  tree = view()
  find(tree, (node) => node.type === 'button' && node.props.children === 'Select').props.onClick()
  tree = view()
  find(tree, (node) => node.type === 'textarea').props.onChange({ target: { value: '  Recheck  ' } })
  find(view(), (node) => node.type === 'button' && node.props.children === 'Return for approval').props.onClick()
  await settle()
  assert.deepEqual(calls.map((args) => args.slice(2)), [[0, 'date', 'desc'], [0, 'type', 'asc'], [25, 'type', 'asc']])
  assert.deepEqual(returned, [['ot-1', 'Recheck']])
  assert.match(renderToStaticMarkup(view()), /was returned for approval/)
})
