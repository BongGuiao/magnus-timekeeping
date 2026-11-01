const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const compiled = ts.transpileModule(
  readFileSync(join(__dirname, '..', 'src', 'components', 'dashboard', 'AttendanceCorrectionsPanel.tsx'), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } },
).outputText
const request = {
  id: 'correction', employee_code: 'EMP-1', employee_name: 'Test Employee', work_date: '2026-10-12',
  original_clock_in_at: '2026-10-12T01:00:05Z', original_clock_out_at: null,
  requested_clock_in_at: '2026-10-12T01:00:05Z', requested_clock_out_at: '2026-10-12T10:00:00Z',
  reason: 'Forgot to punch out', supporting_reference: 'JO-123', status: 'PENDING', row_version: 1,
}
const day = {
  work_date: '2026-10-12', clock_in_at: request.original_clock_in_at, clock_out_at: null,
  expected_clock_in_at: '2026-10-12T01:00:00Z', expected_clock_out_at: request.requested_clock_out_at,
}

function component(scope, { requests = [request], loadedDay = null, reviewNotes = {}, api = {}, onPendingCountChange } = {}) {
  const exports = {}
  const states = [requests, false, '', '', null, '2026-10-12', loadedDay,
    '2026-10-12T09:00', '2026-10-12T18:00', 'Forgot to punch out', 'JO-123', reviewNotes]
  let index = 0
  const updates = []
  runInNewContext(compiled, {
    exports,
    require(name) {
      if (name === 'react') return {
        ...React,
        useState() {
          const stateIndex = index++
          return [states[stateIndex], (value) => updates.push([stateIndex, value])]
        },
        useEffect() {},
      }
      if (name === '../common/AttendanceDeadlines') return { __esModule: true, default: () => null }
      if (name === '../../lib/attendanceCorrectionApi') return api
      return require(name)
    },
  })
  const tree = exports.default({ scope, onPendingCountChange })
  return { tree, html: renderToStaticMarkup(tree), updates }
}

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return null
  if (predicate(tree)) return tree
  for (const child of React.Children.toArray(tree.props?.children)) {
    const found = find(child, predicate)
    if (found) return found
  }
  return null
}

test('supervisor dashboard shows original and requested punches, reason and decisions', () => {
  const { html } = component('team')
  for (const text of ['Attendance Correction Approvals', 'EMP-1 - Test Employee', 'Original:', 'Requested:', 'Missing', 'Forgot to punch out', 'JO-123', 'Approve', 'Reject']) {
    assert.ok(html.includes(text), text)
  }
  assert.ok(!html.includes('Submit correction'))
})

test('employee form locks existing punches and submits exact original timestamp', async () => {
  let submitted
  const result = component('own', { loadedDay: day, api: { submitAttendanceCorrection: async (payload) => {
    submitted = payload
    return request
  } } })
  assert.ok(result.html.includes('readOnly'))
  assert.ok(!result.html.includes('>Approve<'))
  find(result.tree, (node) => node.type === 'form').props.onSubmit({ preventDefault() {} })
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(submitted.requested_clock_in_at, request.original_clock_in_at)
  assert.equal(submitted.requested_clock_out_at, '2026-10-12T18:00:00+08:00')
  assert.equal(submitted.work_date, day.work_date)
  assert.equal(submitted.reason, 'Forgot to punch out')
})

test('supervisor needs notes and sends a versioned decision', async () => {
  let decision
  const api = { decideAttendanceCorrection: async (...args) => { decision = args } }
  const missing = component('team', { api })
  await find(missing.tree, (node) => node.type === 'button' && node.props.children === 'Approve').props.onClick()
  assert.equal(decision, undefined)
  assert.ok(missing.updates.some(([index, value]) => index === 2 && value.includes('review notes')))
  const valid = component('team', { reviewNotes: { correction: 'Confirmed actual work' }, api })
  find(valid.tree, (node) => node.type === 'button' && node.props.children === 'Approve').props.onClick()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(decision[0].row_version, 1)
  assert.equal(decision[1], 'APPROVED')
  assert.equal(decision[2], 'Confirmed actual work')
})

test('completed attendance cannot display a filing form', () => {
  const { html } = component('own', { loadedDay: { ...day, clock_out_at: day.expected_clock_out_at } })
  assert.ok(html.includes('Both punches exist'))
  assert.ok(!html.includes('<form'))
})

test('both missing punches cannot display a filing form', () => {
  const { html } = component('own', { loadedDay: { ...day, clock_in_at: null, clock_out_at: null } })
  assert.ok(html.includes('At least one existing clock-in or clock-out'))
  assert.ok(!html.includes('<form'))
})

test('supervisor decisions update the overview pending count', async () => {
  let count
  const result = component('team', {
    reviewNotes: { correction: 'Verified' },
    api: { decideAttendanceCorrection: async () => request },
    onPendingCountChange(value) { count = value },
  })
  find(result.tree, (node) => node.type === 'button' && node.props.children === 'Approve').props.onClick()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(count, 0)
})

test('refresh updates the overview count and failures clear it', async () => {
  for (const fails of [false, true]) {
    let count = 1
    const result = component('team', {
      api: { fetchAttendanceCorrections: async () => {
        if (fails) throw new Error('Could not refresh')
        return [request, { ...request, id: 'second' }]
      } },
      onPendingCountChange(value) { count = value },
    })
    await find(result.tree, (node) => node.type === 'button' && node.props.children === 'Refresh requests').props.onClick()
    assert.equal(count, fails ? null : 2)
  }
})
