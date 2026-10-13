const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

function load(relativePath, imports = require, globals = {}) {
  const source = readFileSync(join(__dirname, '..', 'src', ...relativePath.split('/')), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const exports = {}
  runInNewContext(code, { exports, require: imports, ...globals })
  return exports
}

test('recent attendance displays server net minutes, not gross elapsed hours', () => {
  const Table = load('components/dashboard/RecentAttendanceTable.tsx').default
  const html = renderToStaticMarkup(React.createElement(Table, {
    entries: [{
      date: '2026-10-12', status: 'present',
      timeIn: '2026-10-12T08:00:00+08:00', timeOut: '2026-10-12T17:00:00+08:00',
      minutesWorked: 480,
    }],
  }))
  assert.ok(html.includes('8h 0m'))
  assert.ok(!html.includes('9h 0m'))
})

test('employee snapshot maps exact net minutes and requests a live refresh', async () => {
  let requested
  const api = load('lib/attendanceApi.ts', (name) => {
    if (name === './apiClient') return {
      apiClient: { get: async (...args) => {
        requested = args
        return { data: { data: {
          records: [{ date: '2026-10-12', time_in: 'in', time_out: 'out', minutes_worked: 481, status: 'present' }],
          weekly_minutes_worked: 481, weekly_hours_worked: 8.02,
          missed_clock_ins_this_month: 0, refreshed_at: '2026-10-12T17:00:00+08:00',
        } } }
      } },
    }
    if (name === './attendanceDevice') return {}
    return require(name)
  })
  const snapshot = await api.fetchRecentAttendanceSnapshot()
  assert.equal(requested[0], '/attendance/recent')
  assert.equal(requested[1].params.force_refresh, true)
  assert.equal(snapshot.weeklyHoursWorked, 481 / 60)
  assert.equal(snapshot.entries[0].minutesWorked, 481)
})

test('administrator total exactly tallies employee minutes despite rounded decimal hours', () => {
  // Five one-minute totals round to 0.10 decimal hours (six minutes), not five.
  const weekly_hours = Array.from({ length: 5 }, (_, i) => ({
    employee_id: String(i), employee_code: `EMP${i}`, employee_name: `Employee ${i}`,
    minutes_worked: 1, hours_worked: 0.02,
  }))
  let index = 0
  const mockData = load('data/mockDashboard.ts')
  const StatCard = load('components/dashboard/StatCard.tsx')
  const Dashboard = load('pages/Dashboard.tsx', (name) => {
    if (name === 'react') return {
      ...React, useEffect() {},
      useState(initial) {
        const current = index++
        const values = {
          0: 'administrator', 9: { weekly_hours, no_login: [], no_logout: [], pending_leaves: [] },
          10: false, 12: 'weekly-hours',
        }
        return [current in values ? values[current] : typeof initial === 'function' ? initial() : initial, () => {}]
      },
    }
    if (name === '../data/mockDashboard') return mockData
    if (name === '../types/role') return {
      getSelectedDashboardRole: () => 'administrator', normalizeDashboardRole: () => 'administrator',
    }
    if (name === '../hooks/useLogout') return { useLogout: () => ({ logout() {} }) }
    if (name === '../components/dashboard/StatCard') return StatCard
    if (name.startsWith('../components/')) return {
      __esModule: true, default: () => null,
      AnnouncementsCard: () => null, HolidaysCard: () => null,
      LeaveRequestsCard: () => null, SupervisorPendingLeavesCard: () => null,
    }
    if (name.startsWith('../lib/')) return {}
    return require(name)
  }, { localStorage: { getItem: () => 'administrator' } }).default
  const html = renderToStaticMarkup(React.createElement(Dashboard, { employeeName: 'Admin' }))
  assert.ok(html.includes('0h 5m'))
  assert.equal((html.match(/0h 1m/g) ?? []).length, 5)
  assert.ok(!html.includes('0h 6m'))
})
