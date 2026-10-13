const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')

const source = readFileSync(join(__dirname, '..', 'src', 'lib', 'overtimePeriod.ts'), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const exportsObject = {}
runInNewContext(compiled, { exports: exportsObject })
const { philippineDateTime, overtimeTimestamp, defaultOvertimePeriod, overtimePeriodMinutes, overtimePeriodError } = exportsObject

const entry = {
  timeIn: '2026-10-12T01:00:00Z', timeOut: '2026-10-12T11:00:00Z',
  expectedTimeIn: '2026-10-12T01:00:00Z', expectedTimeOut: '2026-10-12T09:00:00Z',
}

test('Philippine dates and payload offsets do not depend on browser timezone', () => {
  assert.equal(philippineDateTime('2026-10-12T16:30:00Z'), '2026-10-13T00:30:00')
  assert.equal(overtimeTimestamp('2026-10-13T00:30:00'), '2026-10-13T00:30:00+08:00')
  assert.equal(philippineDateTime('2026-10-12T01:00:00.123Z', true), '2026-10-12T09:00:01')
})

test('defaults select post-shift, pre-shift and night differential attendance periods', () => {
  assert.equal(defaultOvertimePeriod(entry, 'REGULAR_OVERTIME').requested_start_at, '2026-10-12T17:00:00')
  const early = { ...entry, timeIn: '2026-10-12T00:00:00Z', timeOut: entry.expectedTimeOut }
  assert.equal(defaultOvertimePeriod(early, 'REGULAR_OVERTIME').requested_end_at, '2026-10-12T09:00:00')
  assert.equal(defaultOvertimePeriod(entry, 'NIGHT_DIFFERENTIAL').requested_start_at, '2026-10-12T09:00:00')
})

test('defaults never place scheduled boundaries outside actual punches', () => {
  const late = { ...entry, timeIn: '2026-10-12T10:00:00Z' }
  assert.equal(defaultOvertimePeriod(late, 'REGULAR_OVERTIME').requested_start_at, '2026-10-12T18:00:00')
})

test('overnight duration and limits are validated against attendance', () => {
  const overnight = { timeIn: '2026-10-12T14:00:00Z', timeOut: '2026-10-12T18:00:00Z' }
  const period = { requested_start_at: '2026-10-12T23:30:00', requested_end_at: '2026-10-13T00:30:00' }
  assert.equal(overtimePeriodMinutes(period), 60)
  assert.equal(overtimePeriodError(overnight, period, 60, 120), null)
  assert.ok(overtimePeriodError(overnight, period, 61, 120))
  assert.ok(overtimePeriodError(overnight, period, 60, 30))
  assert.ok(overtimePeriodError(overnight, { ...period, requested_end_at: '2026-10-13T03:00:00' }, 60, 120))
  assert.ok(overtimePeriodError(overnight, { ...period, requested_start_at: '2026-10-12T21:00:00' }, 60, 120))
  assert.ok(overtimePeriodError(overnight, { ...period, requested_end_at: period.requested_start_at }, 1, 120))
  assert.ok(overtimePeriodError(overnight, { ...period, requested_start_at: '' }, 1, 120))
})

test('requested minutes follow each selected period in whole minutes', () => {
  const period = { requested_start_at: '2026-10-12T18:00:00', requested_end_at: '2026-10-12T19:00:00' }
  assert.equal(overtimePeriodMinutes(period), 60)
  assert.equal(overtimePeriodMinutes({ ...period, requested_end_at: '2026-10-12T18:30:59' }), 30)
  assert.equal(overtimePeriodMinutes({ ...period, requested_start_at: '2026-10-12T18:15:00' }), 45)
})

test('recent attendance retains approval details without overtime submission controls', () => {
  const componentSource = readFileSync(join(__dirname, '..', 'src', 'components', 'dashboard', 'RecentAttendanceTable.tsx'), 'utf8')
  const componentCode = ts.transpileModule(componentSource, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const componentExports = {}
  runInNewContext(componentCode, { exports: componentExports, require })
  const React = require('react')
  const { renderToStaticMarkup } = require('react-dom/server')
  const html = renderToStaticMarkup(React.createElement(componentExports.default, {
    entries: [{
      ...entry, date: '2026-10-12', status: 'present',
      overtimeApplications: [{
        id: 'test', overtimeType: 'REGULAR_OVERTIME', requestedMinutes: 60,
        status: 'APPROVED', finalPayableMinutes: 60,
      }],
    }],
  }))
  assert.ok(html.includes('OT Approval'))
  assert.ok(html.includes('APPROVED'))
  assert.ok(html.includes('payable'))
  assert.ok(!html.includes('<form'))
  assert.ok(!html.includes('<button'))
  assert.ok(!html.includes('Apply for overtime'))
})
