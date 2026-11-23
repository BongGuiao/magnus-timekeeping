const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')

function load(file, imports, globals = {}) {
  const exports = {}
  const code = ts.transpileModule(readFileSync(join(__dirname, '..', 'src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  runInNewContext(code, { exports, require: (name) => imports[name] ?? require(name), ...globals })
  return exports
}

function parseCsv(text) {
  const rows = []
  let row = [], value = '', quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { value += '"'; i++ }
      else if (c === '"') quoted = false
      else value += c
    } else if (c === '"') quoted = true
    else if (c === ',') { row.push(value); value = '' }
    else if (c === '\r' && text[i + 1] === '\n') { row.push(value); rows.push(row); row = []; value = ''; i++ }
    else value += c
  }
  rows[0][0] = rows[0][0].replace(/^\uFEFF/, '')
  return rows
}

function fixtures(overrides = {}, globals = {}) {
  const calls = []
  const records = {
    org: [{ id: 'ou', org_unit_name: 'HR, "People"', excluded_approval_org_unit_ids: ['child'] }],
    location: [{ id: 'loc', location_name: 'North\nOffice', latitude: '-12.5', longitude: '123.25' }],
    geofence: [{ id: 'geo', geofence_code: 'G1', radius_meters: '125.5' }],
    schedule: [{ id: 'schedule', schedule_code: 'S1' }],
    segments: [{ id: 'segment', start_time: '08:00' }],
    pattern: [{ id: 'pattern', pattern_name: 'Weekly', days: [{ cycle_day_no: 1, is_workday: false }] }],
    leave: [{ id: 'leave', leave_name: 'Annual' }],
    benefits: [{ id: 'benefit', category: 'ALLOWANCE' }, { id: 'deduction', category: 'EMPLOYEE_DEDUCTION' }],
    ...overrides,
  }
  const fetch = (key) => async (arg) => { calls.push([key, arg]); return records[key] }
  const api = load(join('lib', 'settingsCsv.ts'), {
    './orgUnitApi': { fetchOrgUnits: fetch('org') },
    './locationApi': { fetchLocations: fetch('location') },
    './geofenceApi': { fetchGeofences: fetch('geofence') },
    './scheduleTemplateApi': { fetchScheduleTemplates: fetch('schedule'), fetchScheduleSegments: fetch('segments') },
    './restDayPatternApi': { fetchRestDayPatterns: fetch('pattern') },
    './leaveApi': { fetchLeaveTypes: fetch('leave') },
  }, globals)
  return { api, calls, context: { companyId: 'company', payrollGroupId: 'group', loadBenefitTypes: fetch('benefits') } }
}

function rowObject(rows, index = 1) {
  return Object.fromEntries(rows[0].map((header, i) => [header, rows[index][i]]))
}

test('each settings tab exports its scoped records and essential related data', async () => {
  const { api, calls, context } = fixtures()
  const views = [
    ['org-units', 'ou', 'org'],
    ['locations', 'loc', 'location'],
    ['geofences', 'geo', 'geofence'],
    ['schedule-templates', 'schedule', 'schedule'],
    ['rest-day-patterns', 'pattern', 'pattern'],
    ['leave-management', 'leave', 'leave'],
    ['company-benefit-types', 'benefit', 'benefits'],
    ['company-deduction-types', 'deduction', 'benefits'],
  ]
  for (const [view, id, key] of views) {
    const rows = parseCsv(await api.buildSettingsCsv(view, context))
    assert.equal(rows.length, 2, view)
    assert.equal(rowObject(rows).id, id, view)
    const call = calls.filter(([name]) => name === key).at(-1)
    if (['org', 'location', 'geofence'].includes(key)) assert.equal(call[1], 'company')
    if (['schedule', 'leave'].includes(key)) assert.equal(call[1].companyId, 'company')
    if (key === 'benefits') assert.equal(call[1], 'group')
    if (key === 'pattern') assert.equal(call[1], null)
  }
  const org = rowObject(parseCsv(await api.buildSettingsCsv('org-units', context)))
  assert.equal(org.org_unit_name, 'HR, "People"')
  assert.deepEqual(JSON.parse(org.excluded_approval_org_unit_ids), ['child'])
  const location = rowObject(parseCsv(await api.buildSettingsCsv('locations', context)))
  assert.equal(location.location_name, 'North\nOffice')
  assert.equal(location.latitude, '-12.5')
  const schedule = rowObject(parseCsv(await api.buildSettingsCsv('schedule-templates', context)))
  assert.equal(JSON.parse(schedule.segments)[0].start_time, '08:00')
  const pattern = rowObject(parseCsv(await api.buildSettingsCsv('rest-day-patterns', context)))
  assert.equal(JSON.parse(pattern.days)[0].is_workday, false)
  assert.ok(calls.some(([key, id]) => key === 'segments' && id === 'schedule'))
})

test('empty lists retain headers and company and payroll group are required', async () => {
  const { api, context } = fixtures({ org: [], benefits: [] })
  assert.deepEqual(parseCsv(await api.buildSettingsCsv('org-units', context)).length, 1)
  assert.match(await api.buildSettingsCsv('company-deduction-types', context), /payrollGroupId/)
  await assert.rejects(api.buildSettingsCsv('locations', { companyId: '' }), /Select a company/)
  await assert.rejects(api.buildSettingsCsv('company-benefit-types', { companyId: 'company' }), /Select a payroll group/)
  await api.buildSettingsCsv('rest-day-patterns', { companyId: '' })
})

test('formula-like text, invalid data, API errors and possibly truncated lists fail explicitly', async () => {
  for (const name of ['=1+1', '  @SUM(1)', '\ttext']) {
    const { api, context } = fixtures({ org: [{ org_unit_name: name }] })
    await assert.rejects(api.buildSettingsCsv('org-units', context), /spreadsheet formula/)
  }
  const invalid = fixtures({ location: [{ latitude: 'not a number', longitude: null }] })
  await assert.rejects(invalid.api.buildSettingsCsv('locations', invalid.context), /number is invalid/)
  for (const [view, key] of [['org-units', 'org'], ['locations', 'location'], ['geofences', 'geofence'], ['schedule-templates', 'schedule'], ['leave-management', 'leave']]) {
    const { api, context } = fixtures({ [key]: Array(1000).fill({}) })
    await assert.rejects(api.buildSettingsCsv(view, context), /API limit of 1000/, view)
  }
  const segments = fixtures({ segments: Array(100).fill({}) })
  await assert.rejects(segments.api.buildSettingsCsv('schedule-templates', segments.context), /API limit of 100/)
  const failed = fixtures()
  failed.context.loadBenefitTypes = async () => { throw new Error('Permission denied') }
  await assert.rejects(failed.api.buildSettingsCsv('company-benefit-types', failed.context), /Permission denied/)
  const missingDays = fixtures({ pattern: [{ id: 'pattern' }] })
  await assert.rejects(missingDays.api.buildSettingsCsv('rest-day-patterns', missingDays.context), /invalid cycle days/)
})

test('download creates and releases the CSV object URL', async () => {
  let saved, revoked, removed = false, blob
  const link = { click() { saved = this.download }, remove() { removed = true } }
  const { api, context } = fixtures({}, {
    Blob,
    URL: { createObjectURL(value) { blob = value; return 'blob:csv' }, revokeObjectURL(value) { revoked = value } },
    document: { createElement: () => link, body: { appendChild() {} } },
    window: { setTimeout(callback) { callback() } },
  })
  await api.downloadSettingsCsv('org-units', context)
  assert.equal(saved, 'org-units.csv')
  assert.equal(revoked, 'blob:csv')
  assert.ok(removed)
  assert.match(await blob.text(), /org_unit_name/)
})

test('settings menu is present in both menus only for assigned, selected HR Admin with module permission', () => {
  const csv = fixtures().api
  function render(view, assigned, selected, permission) {
    let index = 0
    const TopNav = load(join('components', 'dashboard', 'TopNav.tsx'), {
      react: {
        useEffect() {}, useLayoutEffect() {}, useRef: () => ({ current: null }),
        useState(initial) { return [index++ < 2 ? true : typeof initial === 'function' ? initial() : initial, () => {}] },
      },
      './WorkspaceTabsContext': { useWorkspaceTabs: () => null },
      '../../lib/companyApi': {},
      '../../lib/settingsCsv': csv,
      '../../hooks/useCompanySetupSelection': { useCompanySetupSelection: () => ({ companyId: 'company', selectCompany() {} }) },
      '../../types/role': {
        getAvailableRoleCodes: () => assigned,
        getSelectedDashboardRoleCode: () => selected,
        canPreviewDashboardRoles: () => false,
        hasPermission: (name) => name === permission,
        hasAnyPermission: () => false,
        isSystemAdmin: () => false,
        normalizeDashboardRole: () => 'administrator',
      },
    }, { localStorage: { getItem: () => 'admin' } }).default
    const tree = TopNav({ employeeName: 'HR', activeView: view })
    const found = []
    function collect(node) {
      if (Array.isArray(node)) return node.forEach(collect)
      if (!React.isValidElement(node)) return
      if (typeof node.type === 'function' && node.type.name === 'SettingsCsvMenuItem') found.push(node)
      collect(node.props.children)
    }
    collect(tree)
    return found
  }
  for (const [view, permission] of Object.entries(csv.SETTINGS_CSV_PERMISSIONS)) {
    assert.equal(render(view, ['HR_ADMIN'], 'HR_ADMIN', permission).length, 2, view)
    assert.equal(render(view, ['HR_ADMIN'], 'HR_ADMIN', 'other').length, 0, view)
  }
  assert.equal(render('org-units', ['HR_ADMIN'], 'SYSTEM_ADMIN', 'company.setup').length, 0)
  assert.equal(render('org-units', ['SYSTEM_ADMIN'], 'HR_ADMIN', 'company.setup').length, 0)
  assert.equal(render('companies', ['HR_ADMIN'], 'HR_ADMIN', 'company.setup').length, 0)
})

test('menu action passes the current payroll group and reports download errors', async () => {
  const csv = fixtures().api
  for (const contextCompany of ['company', 'previous-company']) {
    let index = 0, request
    const messages = []
    const TopNav = load(join('components', 'dashboard', 'TopNav.tsx'), {
      react: {
        useEffect() {}, useLayoutEffect() {}, useRef: () => ({ current: null }),
        useState(initial) {
          const current = index++
          return [current < 2 ? true : typeof initial === 'function' ? initial() : initial,
            (value) => { if (current === 6) messages.push(value) }]
        },
      },
      './WorkspaceTabsContext': { useWorkspaceTabs: () => null },
      '../../lib/companyApi': {},
      '../../lib/settingsCsv': {
        ...csv,
        downloadSettingsCsv: async (...args) => { request = args; throw new Error('Download denied') },
      },
      '../../hooks/useCompanySetupSelection': { useCompanySetupSelection: () => ({ companyId: 'company', selectCompany() {} }) },
      '../../types/role': {
        getAvailableRoleCodes: () => ['HR_ADMIN'], getSelectedDashboardRoleCode: () => 'HR_ADMIN',
        canPreviewDashboardRoles: () => false, hasPermission: () => true, hasAnyPermission: () => true,
        isSystemAdmin: () => false, normalizeDashboardRole: () => 'administrator',
      },
    }, { Error, localStorage: { getItem: () => 'admin' } }).default
    const tree = TopNav({
      employeeName: 'HR', activeView: 'company-benefit-types',
      settingsPayrollContext: { companyId: contextCompany, payrollGroupId: 'group', loadBenefitTypes() {} },
    })
    let menu
    function collect(node) {
      if (Array.isArray(node)) return node.forEach(collect)
      if (!React.isValidElement(node)) return
      if (typeof node.type === 'function' && node.type.name === 'SettingsCsvMenuItem') menu = node
      collect(node.props.children)
    }
    collect(tree)
    menu.props.onSelect()
    await new Promise((resolve) => setImmediate(resolve))
    assert.equal(request[0], 'company-benefit-types')
    assert.equal(request[1].companyId, 'company')
    assert.equal(request[1].payrollGroupId, contextCompany === 'company' ? 'group' : undefined)
    assert.equal(messages.at(-1).text, 'Download denied')
    assert.equal(messages.at(-1).error, true)
  }
})
