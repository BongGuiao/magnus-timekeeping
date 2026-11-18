const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')

const source = readFileSync(join(__dirname, '..', 'src', 'lib', 'payrollCutoffCsv.ts'), 'utf8')
const moduleExports = {}
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
runInNewContext(code, { exports: moduleExports })

const cutoff = {
  cutoff_code: 'GROUP-20261101-20261115',
  period_start: '2026-11-01',
  period_end: '2026-11-15',
}
const result = {
  employee_id: 'employee-1',
  employee_name: 'Warren, Philip',
  scheduled_days: 10,
  paid_days: 9,
  regular_minutes: 540,
  late_minutes: 15,
  undertime_minutes: 0,
  absence_minutes: 60,
  paid_leave_minutes: 30,
  unpaid_leave_minutes: 0,
  ordinary_ot_minutes: 90,
  rest_day_minutes: 0,
  rest_day_ot_minutes: 0,
  special_day_minutes: 0,
  special_day_ot_minutes: 0,
  holiday_minutes: 0,
  holiday_ot_minutes: 0,
  night_regular_minutes: 120,
  night_ot_minutes: 0,
  official_business_minutes: 60,
  exception_count: 2,
  payroll_status: 'READY',
}

test('payroll cutoff results CSV includes cutoff metadata and the displayed time totals', () => {
  const csv = moduleExports.payrollCutoffResultsCsv(cutoff, '01 ADMIN — Admin Group', [result])
  assert.ok(csv.startsWith('\uFEFF'))
  assert.ok(csv.includes('Cutoff code,Payroll group,Period start,Period end,Employee ID,Employee'))
  assert.ok(csv.includes('01 ADMIN — Admin Group'))
  assert.ok(csv.includes('"Warren, Philip"'))
  assert.ok(csv.includes(',10,9,9.00,0.25,0.00,1.00,0.50,0.00,1.50'))
  assert.ok(csv.includes('2,READY'))
  assert.match(csv, /\r\n$/)
})

test('formula-like values block a spreadsheet-dangerous payroll export', () => {
  assert.throws(
    () => moduleExports.payrollCutoffResultsCsv(cutoff, 'Admin Group', [{ ...result, employee_name: '=HYPERLINK("https://example.invalid")' }]),
    /Employee.*spreadsheet formula/,
  )
})

test('CSV filename sanitizes cutoff codes and includes the period', () => {
  assert.equal(
    moduleExports.payrollCutoffResultsFilename('../GROUP / 01', cutoff.period_start, cutoff.period_end),
    'GROUP-01-time-results-2026-11-01-2026-11-15.csv',
  )
})
