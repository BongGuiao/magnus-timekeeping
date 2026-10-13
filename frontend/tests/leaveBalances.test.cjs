const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')

function load(relativePath, imports = require, globals = {}) {
  const source = readFileSync(join(__dirname, '..', 'src', ...relativePath.split('/')), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  runInNewContext(code, { exports, require: imports, ...globals })
  return exports
}

test('formatLeaveBalance formats days cleanly without raw minutes', () => {
  const api = load('lib/leaveApi.ts', (name) => {
    if (name === './apiClient') return { apiClient: {} }
    return require(name)
  })

  // 12 days (5760 min)
  assert.equal(api.formatLeaveBalance(5760, 'DAYS'), '12 days')
  // 1 day (480 min)
  assert.equal(api.formatLeaveBalance(480, 'DAYS'), '1 day')
  // 0 days
  assert.equal(api.formatLeaveBalance(0, 'DAYS'), '0 days')
  // Half day
  assert.equal(api.formatLeaveBalance(240, 'DAYS'), '0.5 days')
  // Hours
  assert.equal(api.formatLeaveBalance(60, 'HOURS'), '1 hour')
  assert.equal(api.formatLeaveBalance(120, 'HOURS'), '2 hours')
  // Minutes
  assert.equal(api.formatLeaveBalance(30, 'MINUTES'), '30 min')
})

test('minutesToLeaveUnits and leaveUnitsToMinutes convert accurately', () => {
  const api = load('lib/leaveApi.ts', (name) => {
    if (name === './apiClient') return { apiClient: {} }
    return require(name)
  })

  assert.equal(api.minutesToLeaveUnits(4800, 'DAYS'), 10)
  assert.equal(api.leaveUnitsToMinutes(10, 'DAYS'), 4800)
  assert.equal(api.minutesToLeaveUnits(5760, 'DAYS'), 12)
  assert.equal(api.leaveUnitsToMinutes(12, 'DAYS'), 5760)
})
