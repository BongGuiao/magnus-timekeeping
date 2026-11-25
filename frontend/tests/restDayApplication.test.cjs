const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const ts = require('typescript')

function find(node, predicate) {
  if (Array.isArray(node)) {
    for (const child of node) {
      const match = find(child, predicate)
      if (match) return match
    }
    return null
  }
  if (!React.isValidElement(node)) return null
  return predicate(node) ? node : find(node.props.children, predicate)
}

test('rest-day filing requests the complete interval and prevents a second request for the date', async () => {
  const cells = []
  let hook = 0
  let effectStarted = false
  const calls = []
  const records = [{
    attendance_id: 'a', date: '2026-11-22', time_in: '2026-11-22T07:35:00+08:00',
    time_out: '2026-11-22T19:32:00+08:00', rest_day_work_minutes: 717,
  }, {
    attendance_id: 'b', date: '2026-11-22', time_in: '2026-11-22T20:00:00+08:00',
    time_out: '2026-11-22T21:00:00+08:00', rest_day_work_minutes: 60,
  }]
  const api = {
    fetchRestDayAttendanceOptions: async () => records,
    fetchMyOvertimeApplications: async () => [],
    submitOvertimeApplication: async (id, payload) => {
      calls.push({ id, payload })
      return {
        id: 'request', application_no: 'RD-1', attendance_record_id: id,
        attendance_date: records[0].date, overtime_type: payload.overtime_type,
        requested_minutes: payload.requested_minutes, status: 'PENDING',
      }
    },
  }
  const hooks = {
    useState(initial) {
      const index = hook++
      if (!(index in cells)) cells[index] = initial
      return [cells[index], (next) => {
        cells[index] = typeof next === 'function' ? next(cells[index]) : next
      }]
    },
    useEffect(effect) {
      if (!effectStarted) { effectStarted = true; effect() }
    },
  }
  const source = readFileSync(join(__dirname, '..', 'src', 'pages', 'RestDayApplication.tsx'), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const exports = {}
  runInNewContext(code, {
    exports, Date, Error,
    require(name) {
      if (name === 'react') return hooks
      if (name === '../lib/attendanceApi') return api
      if (name === '../hooks/useLogout') return { useLogout: () => ({ logout() {} }) }
      if (name === '../components/dashboard/TopNav' || name === '../components/common/AttendanceDeadlines') return () => null
      return require(name)
    },
  })
  const render = () => { hook = 0; return exports.default({ employeeName: 'Test' }) }
  const settle = () => new Promise((resolve) => setImmediate(resolve))
  render()
  await settle()
  let tree = render()
  find(tree, (item) => item.type === 'select').props.onChange({ target: { value: 'a' } })
  tree = render()
  find(tree, (item) => item.type === 'textarea' && item.props.required).props.onChange({ target: { value: 'Completed work' } })
  tree = render()
  const html = renderToStaticMarkup(tree)
  assert.match(html, /Rest-day work: 8h 0m/)
  assert.match(html, /Excess: 3h 57m/)
  find(tree, (item) => item.type === 'form').props.onSubmit({ preventDefault() {} })
  await settle()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].id, 'a')
  assert.equal(calls[0].payload.overtime_type, 'REST_DAY_WORK')
  assert.equal(calls[0].payload.requested_minutes, 717)
  assert.match(renderToStaticMarkup(render()), /No eligible rest-day attendance/)
})
