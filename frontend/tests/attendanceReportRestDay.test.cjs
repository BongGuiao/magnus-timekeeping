const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')

test('attendance report counts only approved rest-day excess as overtime', () => {
  const source = readFileSync(join(__dirname, '..', 'src', 'pages', 'AttendanceDetailReport.tsx'), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const exports = {}
  runInNewContext(`${code}\nexports.approvedOvertimeMinutes = approvedOvertimeMinutes`, {
    exports, require: () => ({}),
  })
  const restDay = (minutes, status = 'APPROVED') => ({
    overtime_type: 'REST_DAY_WORK', status, payable_minutes: minutes,
  })
  assert.equal(exports.approvedOvertimeMinutes({ overtime_applications: [restDay(480)] }), 0)
  assert.equal(exports.approvedOvertimeMinutes({ overtime_applications: [restDay(600)] }), 120)
  assert.equal(exports.approvedOvertimeMinutes({ overtime_applications: [restDay(600, 'PENDING')] }), 0)
  assert.equal(exports.approvedOvertimeMinutes({
    overtime_applications: [{ overtime_type: 'REGULAR', status: 'APPROVED', payable_minutes: 60 }],
  }), 60)
})
