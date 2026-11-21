const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

function compile(path, jsx = false) {
  return ts.transpileModule(readFileSync(join(__dirname, '..', path), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: jsx ? ts.JsxEmit.ReactJSX : undefined },
  }).outputText
}

const pageCode = compile('src/pages/TardinessReview.tsx', true)
const apiCode = compile('src/lib/tardinessReviewApi.ts')

function renderPage({ review = null, loading = false, error = '' } = {}) {
  const states = [review, loading, error, 0]
  const updates = []
  let index = 0
  const exports = {}
  runInNewContext(pageCode, {
    exports,
    require(name) {
      if (name === 'react') return {
        ...React,
        useState() {
          const current = index++
          return [states[current], (value) => updates.push([current, value])]
        },
        useEffect() {},
      }
      if (name === '../components/dashboard/TopNav') return { __esModule: true, default: () => null }
      if (name === '../hooks/useLogout') return { useLogout: () => ({ logout() {} }) }
      if (name === '../lib/tardinessReviewApi') return { fetchTardinessReview() {} }
      if (name === '../lib/officialBusinessApi') return { formatManilaDateTime: (value) => `PH ${value}` }
      if (name === '../components/attendance/NoticeTemplates') return { __esModule: true, default: () => null }
      return require(name)
    },
  })
  const tree = exports.default({ employeeName: 'HR' })
  return { tree, html: renderToStaticMarkup(tree), updates }
}

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return null
  if (predicate(tree)) return tree
  for (const child of React.Children.toArray(tree.props?.children)) {
    const result = find(child, predicate)
    if (result) return result
  }
  return null
}

test('review shows attendance evidence and both unresolved issue warnings', () => {
  const review = {
    period_start: '2026-11-01', period_end: '2026-11-30',
    candidates: [{
      employee_id: 'employee', employee_no: 'EMP-01', employee_name: 'Test Employee',
      late_dates: ['2026-11-01', '2026-11-02', '2026-11-03', '2026-11-04'],
      duplicate_dates: ['2026-11-01'], pending_correction_dates: ['2026-11-02'],
      records: [{
        attendance_id: 'record', work_date: '2026-11-01',
        expected_clock_in_at: '2026-11-01T01:00:00Z', clock_in_at: '2026-11-01T01:15:00Z',
        late_minutes: 15, attendance_mode: 'PUNCH_REQUIRED',
      }],
    }],
  }
  const { html } = renderPage({ review })
  for (const value of [
    'EMP-01', 'Test Employee', '4 late work dates', 'Duplicate records: 11/01/2026',
    'Pending corrections: 11/02/2026', 'Resolve these attendance issues before issuing a notice',
    'PH 2026-11-01T01:15:00Z', '15', 'No notice or notification is created',
  ]) assert.ok(html.includes(value), value)
})

test('empty, loading and error states are distinct and refresh retries', () => {
  const empty = renderPage({ review: { period_start: '2026-11-01', period_end: '2026-11-30', candidates: [] } })
  assert.ok(empty.html.includes('No employees meet the threshold'))
  assert.ok(renderPage({ loading: true }).html.includes('Loading tardiness review'))
  const failed = renderPage({ error: 'Access denied' })
  assert.ok(failed.html.includes('Access denied'))
  find(failed.tree, (node) => node.type === 'button' && node.props['aria-label'] === 'Refresh review').props.onClick()
  assert.ok(failed.updates.some(([index, value]) => index === 1 && value === true))
  assert.ok(failed.updates.some(([index, value]) => index === 2 && value === ''))
  assert.equal(failed.updates.find(([index]) => index === 3)[1](0), 1)
})

test('flag summary counts affected employees, not individual warnings', () => {
  const candidate = {
    employee_id: 'one', employee_no: 'E1', employee_name: 'Employee One',
    late_dates: ['2026-11-01', '2026-11-02', '2026-11-03', '2026-11-04'],
    duplicate_dates: ['2026-11-01'], pending_correction_dates: ['2026-11-02'], records: [],
  }
  const { html } = renderPage({
    review: {
      period_start: '2026-11-01', period_end: '2026-11-30',
      candidates: [candidate, { ...candidate, employee_id: 'two', employee_no: 'E2', duplicate_dates: [], pending_correction_dates: [] }],
    },
  })
  assert.match(html, /Employees to review<\/p><p[^>]*>2<\/p>/)
  assert.match(html, /Employees with flags<\/p><p[^>]*>1<\/p>/)
})

test('preview API returns response data and exposes server errors', async () => {
  const exports = {}
  const expected = { period_start: '2026-11-01', period_end: '2026-11-30', candidates: [] }
  let path
  let fail = false
  runInNewContext(apiCode, {
    exports,
    require(name) {
      if (name === './apiClient') return { apiClient: { get: async (value) => {
        path = value
        if (fail) throw new Error('Forbidden')
        return { data: { data: expected } }
      } } }
      if (name === './attendanceApi') return { getAttendanceErrorMessage: (error) => error.message }
      return require(name)
    },
  })
  assert.equal(await exports.fetchTardinessReview(), expected)
  assert.equal(path, '/attendance/tardiness-review')
  fail = true
  await assert.rejects(exports.fetchTardinessReview(), /Forbidden/)
})
