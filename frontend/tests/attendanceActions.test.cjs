const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const source = readFileSync(join(__dirname, '..', 'src', 'pages', 'Attendance.tsx'), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText

function renderAttendance(lastAttendance, cameraActive = false) {
  const componentExports = {}
  runInNewContext(compiled, {
    exports: componentExports,
    require(name) {
      if (name === 'react') return { ...React, useEffectEvent: (callback) => callback }
      if (name === '../hooks/useAttendanceClock') return {
        useAttendanceClock: () => ({
          employeeCode: 'EMP001',
          verifiedUser: { id: 'user', employee_name: 'Test Employee', employee_code: 'EMP001' },
          lastAttendance,
        }),
      }
      if (name === '../hooks/useWebcamCapture') return {
        useWebcamCapture: () => ({ isActive: cameraActive, isCameraApiAvailable: true }),
      }
      if (name === '../hooks/useLogout') return { useLogout: () => ({ logout() {} }) }
      if (name === '../components/dashboard/TopNav' || name === '../components/common/Stepper') {
        return { __esModule: true, default: () => null }
      }
      if (name === '../lib/apiClient' || name === '../lib/attendanceApi') return {}
      return require(name)
    },
  })
  return renderToStaticMarkup(React.createElement(componentExports.default, { employeeName: 'Test Employee' }))
}

const afterMeal = {
  clock_in_at: '2026-10-12T08:00:00+08:00',
  clock_out_at: null,
  first_break_out_at: '2026-10-12T10:00:00+08:00',
  first_break_in_at: '2026-10-12T10:15:00+08:00',
  meal_break_out_at: '2026-10-12T12:00:00+08:00',
  meal_break_in_at: '2026-10-12T13:00:00+08:00',
  break_rules: [{
    break_slot: 'SECOND_BREAK',
    segment_type: 'PAID_BREAK',
    start_at: '2000-01-01T00:00:00+08:00',
    end_at: '2100-01-01T00:00:00+08:00',
  }],
}

test('after ending the meal break, only second-break and clock-out actions remain', () => {
  for (const cameraActive of [false, true]) {
    const html = renderAttendance(afterMeal, cameraActive)
    assert.ok(html.includes('START SECOND BREAK'))
    assert.ok(html.includes('Clock Out'))
    for (const label of ['BREAKS TAKEN', 'START FIRST BREAK', 'END FIRST BREAK', 'START MEAL BREAK', 'END MEAL BREAK', 'Match enrolled face']) {
      assert.ok(!html.includes(label), `Unexpected label: ${label}`)
    }
  }
})

test('an active second break offers its end action, and a completed one is hidden', () => {
  const started = { ...afterMeal, second_break_out_at: '2026-10-12T15:00:00+08:00' }
  const active = renderAttendance(started)
  assert.ok(active.includes('END SECOND BREAK'))
  assert.ok(!active.includes('START SECOND BREAK'))
  const completed = renderAttendance({ ...started, second_break_in_at: '2026-10-12T15:15:00+08:00' })
  assert.ok(completed.includes('Clock Out'))
  assert.ok(!completed.includes('END SECOND BREAK'))
  assert.ok(!completed.includes('START SECOND BREAK'))
})

test('if meal break ends before first break was taken, first break is offered and second break follows once filled', () => {
  const break_rules = ['FIRST_BREAK', 'SECOND_BREAK'].map((break_slot) => ({
    break_slot,
    segment_type: 'PAID_BREAK',
    start_at: '2000-01-01T00:00:00+08:00',
    end_at: '2100-01-01T00:00:00+08:00',
  }))
  const attendance = { ...afterMeal, first_break_out_at: null, first_break_in_at: null, break_rules }
  for (const cameraActive of [false, true]) {
    const html = renderAttendance(attendance, cameraActive)
    assert.ok(html.includes('START FIRST BREAK'))
    assert.ok(!html.includes('START SECOND BREAK'))
    assert.ok(html.includes('Clock Out'))
  }

  // Once first break is filled (completed), START SECOND BREAK appears
  const filledAttendance = {
    ...attendance,
    first_break_out_at: '2026-10-12T14:00:00+08:00',
    first_break_in_at: '2026-10-12T14:15:00+08:00',
  }
  const filledHtml = renderAttendance(filledAttendance)
  assert.ok(filledHtml.includes('START SECOND BREAK'))
  assert.ok(!filledHtml.includes('START FIRST BREAK'))
  assert.ok(filledHtml.includes('Clock Out'))

  const outsideWindow = renderAttendance({
    ...attendance,
    break_rules: break_rules.map((rule) => ({ ...rule, end_at: '2001-01-01T00:00:00+08:00' })),
  })
  assert.ok(!outsideWindow.includes('START SECOND BREAK'))
  assert.ok(!outsideWindow.includes('START FIRST BREAK'))
  assert.ok(outsideWindow.includes('Clock Out'))
})

test('before meal break occurs, only the two initial buttons (first and meal break) are visible', () => {
  const allRules = ['FIRST_BREAK', 'MEAL_BREAK', 'SECOND_BREAK'].map((break_slot) => ({
    break_slot,
    segment_type: break_slot === 'MEAL_BREAK' ? 'UNPAID_BREAK' : 'PAID_BREAK',
    start_at: '2000-01-01T00:00:00+08:00',
    end_at: '2100-01-01T00:00:00+08:00',
  }))
  const freshAttendance = {
    ...afterMeal,
    first_break_out_at: null,
    first_break_in_at: null,
    meal_break_out_at: null,
    meal_break_in_at: null,
    second_break_out_at: null,
    second_break_in_at: null,
    break_rules: allRules,
  }
  const freshHtml = renderAttendance(freshAttendance)
  assert.ok(freshHtml.includes('START FIRST BREAK'))
  assert.ok(freshHtml.includes('START MEAL BREAK'))
  assert.ok(!freshHtml.includes('START SECOND BREAK'))

  const firstBreakDoneHtml = renderAttendance({
    ...freshAttendance,
    first_break_out_at: '2026-10-12T10:00:00+08:00',
    first_break_in_at: '2026-10-12T10:15:00+08:00',
  })
  assert.ok(!firstBreakDoneHtml.includes('START FIRST BREAK'))
  assert.ok(firstBreakDoneHtml.includes('START MEAL BREAK'))
  assert.ok(!firstBreakDoneHtml.includes('START SECOND BREAK'))
})

test('a configured first break remains available before the meal break ends', () => {
  const html = renderAttendance({
    ...afterMeal,
    first_break_out_at: null,
    first_break_in_at: null,
    meal_break_out_at: null,
    meal_break_in_at: null,
    break_rules: [{
      break_slot: 'FIRST_BREAK',
      segment_type: 'PAID_BREAK',
      start_at: '2000-01-01T00:00:00+08:00',
      end_at: '2100-01-01T00:00:00+08:00',
    }],
  })

  assert.ok(html.includes('START FIRST BREAK'))
})

test('no paid/unpaid schedule segments hides all break controls but preserves Clock Out', () => {
  for (const cameraActive of [false, true]) {
    for (const break_rules of [undefined, [], [{ segment_type: 'WORK' }]]) {
      for (const expected_clock_out_at of ['2000-01-01T00:00:00+08:00', '2100-01-01T00:00:00+08:00']) {
        for (const activeBreak of [{}, { meal_break_in_at: null }, { ot_break_out_at: '2026-10-12T14:00:00+08:00' }]) {
          const html = renderAttendance({
            ...afterMeal, break_rules, expected_clock_out_at, ...activeBreak,
          }, cameraActive)
          assert.ok(html.includes('Clock Out'))
          for (const label of [
            'START FIRST BREAK', 'END FIRST BREAK', 'START MEAL BREAK', 'END MEAL BREAK',
            'START SECOND BREAK', 'END SECOND BREAK', 'START OT BREAK', 'END OT BREAK',
          ]) assert.ok(!html.includes(label), `Unexpected label: ${label}`)
        }
      }
    }
  }
})

test('only defined paid/unpaid slots are shown and configured overtime remains available', () => {
  for (const segment_type of ['PAID_BREAK', 'UNPAID_BREAK']) {
    const last = {
      ...afterMeal, meal_break_out_at: null, meal_break_in_at: null,
      break_rules: [{ ...afterMeal.break_rules[0], break_slot: 'MEAL_BREAK', segment_type }],
    }
    const html = renderAttendance(last)
    assert.ok(html.includes('START MEAL BREAK'))
    assert.ok(!html.includes('START FIRST BREAK'))
    assert.ok(!html.includes('START SECOND BREAK'))
    const overtime = renderAttendance({ ...last, expected_clock_out_at: '2000-01-01T00:00:00+08:00' })
    assert.ok(overtime.includes('START OT BREAK'))
    assert.ok(!overtime.includes('START MEAL BREAK'))
  }
})

test('before clock-in and after clock-out, both camera states offer Clock In', () => {
  for (const cameraActive of [false, true]) {
    for (const attendance of [null, { ...afterMeal, clock_out_at: '2026-10-12T17:00:00+08:00' }]) {
      const html = renderAttendance(attendance, cameraActive)
      assert.ok(html.includes('Clock In'))
      assert.ok(!html.includes('Clock Out'))
      assert.ok(!html.includes('START SECOND BREAK'))
      assert.ok(!html.includes('Match enrolled face'))
    }
  }
})
