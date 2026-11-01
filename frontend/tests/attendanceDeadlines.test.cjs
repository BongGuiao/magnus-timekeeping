const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const compiled = ts.transpileModule(
  readFileSync(join(__dirname, '..', 'src', 'components', 'common', 'AttendanceDeadlines.tsx'), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } },
).outputText

const now = Date.parse('2026-10-17T12:00:00Z')
const cutoff = {
  cutoff_id: 'cutoff', cutoff_code: 'OCT-1', period_start: '2026-10-01', period_end: '2026-10-15',
  employee_filing_deadline: '2026-10-16T12:00:00Z', attendance_deadline: '2026-10-18T12:00:00Z',
  attendance_finalized_at: null, locked_at: null, status: 'OPEN',
}

function render(deadlines, { error = '', loading = false, scope = 'own', get = async () => ({ data: { data: deadlines } }) } = {}) {
  const exports = {}
  const states = [deadlines, error, loading, now]
  const updates = []
  const effects = []
  let index = 0
  runInNewContext(compiled, {
    exports,
    require(name) {
      if (name === 'react') return {
        ...React,
        useState() {
          const stateIndex = index++
          return [states[stateIndex], (value) => updates.push([stateIndex, value])]
        },
        useEffect(callback) { effects.push(callback) },
      }
      if (name === '../../lib/apiClient') return { apiClient: { get } }
      if (name === '../../lib/attendanceApi') return { getAttendanceErrorMessage: (error) => error.message }
      return require(name)
    },
    window: { setInterval: () => 1, clearInterval() {} },
  })
  return {
    html: renderToStaticMarkup(React.createElement(exports.default, { scope })),
    updates, effects,
  }
}

test('filing closes while approval remains open, in Philippine time', () => {
  const { html } = render([cutoff])
  assert.ok(html.includes('Philippine time'))
  assert.ok(html.includes('OCT-1'))
  assert.equal((html.match(/\(closed\)/g) || []).length, 1)
  assert.ok(html.includes('8:00:00 PM'))
})

test('legacy cutoffs use the approval date for filing; locks close both', () => {
  assert.equal((render([{ ...cutoff, employee_filing_deadline: null }]).html.match(/\(closed\)/g) || []).length, 0)
  for (const values of [{ locked_at: cutoff.attendance_deadline }, { attendance_finalized_at: cutoff.attendance_deadline }, { status: 'LOCKED' }]) {
    assert.equal((render([{ ...cutoff, ...values }]).html.match(/\(closed\)/g) || []).length, 2)
  }
})

test('deadline equality stays open and errors are visible', () => {
  const { html } = render([{ ...cutoff, employee_filing_deadline: new Date(now).toISOString() }])
  assert.equal((html.match(/\(closed\)/g) || []).length, 0)
  assert.ok(render([], { error: 'Denied' }).html.includes('role="alert"'))
  assert.ok(render([], { loading: true }).html.includes('Loading attendance deadlines'))
})

test('team scope is sent to the server and malformed responses are surfaced', async () => {
  let request
  const result = render([], { scope: 'team', get: async (...args) => {
    request = args
    return { data: { data: {} } }
  } })
  const cleanup = result.effects[0]()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(request[0], '/attendance/reports/attendance-deadlines')
  assert.equal(request[1].params.scope, 'team')
  assert.ok(result.updates.some(([index, value]) => index === 1 && value === 'Invalid attendance deadlines response.'))
  cleanup()
})
