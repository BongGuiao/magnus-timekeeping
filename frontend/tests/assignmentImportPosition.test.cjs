const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const ts = require('typescript')

function loadComponent(file, mocks, globals = {}) {
  const source = readFileSync(join(__dirname, '..', 'src', file), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const exports = {}
  runInNewContext(code, {
    exports, ...globals,
    require: (name) => {
      if (name in mocks) return mocks[name]
      if (name.startsWith('.')) return { __esModule: true, default: () => null }
      return require(name)
    },
  })
  return exports
}

function find(node, predicate) {
  if (Array.isArray(node)) {
    for (const child of node) {
      const result = find(child, predicate)
      if (result) return result
    }
    return null
  }
  if (!React.isValidElement(node)) return null
  return predicate(node) ? node : find(node.props.children, predicate)
}

function harness(canManage = true, overrides = {}, canUploadSchedules = false, role = 'admin') {
  const source = readFileSync(join(__dirname, '..', 'src', 'pages', 'Employees.tsx'), 'utf8')
  const stateNames = [...source.slice(source.indexOf('export default function Employees')).matchAll(/const \[(\w+),.*?= useState/g)]
    .map((match) => match[1])
  const states = {
    editingEmployee: { id: 'employee', employee_no: '0001', first_name: 'Ana', last_name: 'Cruz' },
    isFormOpen: true,
    activeTab: 'assignments',
    visitedEmployeeTabs: new Set(['details', 'assignments', 'schedule']),
    isLoading: false,
    assignmentLookups: { loaded: true, error: '', locations: [], payrollGroups: [] },
    ...overrides,
  }
  let index = 0
  const calls = []
  const FormModal = () => null
  const AssignmentPanel = () => null
  const TopNav = () => null
  const EntitlementUpload = () => null
  const ScheduleUploadPanel = () => null
  const ScheduleAssignmentsPanel = () => null
  const DataTable = () => null
  const hooks = {
    useId: () => 'employee-form',
    useEffect: () => {},
    useSyncExternalStore: (_subscribe, getSnapshot) => getSnapshot(),
    useState: (initial) => {
      const name = stateNames[index++]
      if (!(name in states)) states[name] = typeof initial === 'function' ? initial() : initial
      return [states[name], (value) => { states[name] = typeof value === 'function' ? value(states[name]) : value }]
    },
  }
  const components = loadComponent(join('pages', 'Employees.tsx'), {
    react: hooks,
    '../hooks/useLogout': { useLogout: () => ({ logout() {} }) },
    '../types/role': {
      hasPermission: (permission) => (permission === 'employees.manage' && canManage)
        || (permission === 'schedule.upload_team' && canUploadSchedules)
        || (permission === 'leave.manage' && overrides.leaveManage === true),
      getAvailableRoleCodes: () => role === 'admin' ? ['HR_ADMIN'] : ['SUPERVISOR'],
      getSelectedDashboardRoleCode: () => role === 'admin' ? 'HR_ADMIN' : 'SUPERVISOR',
    },
    '../components/dashboard/WorkspaceTabsContext': { useWorkspaceTabs: () => null },
    '../components/dashboard/TopNav': { __esModule: true, default: TopNav },
    '../lib/employeePersonalDetails': {
      CIVIL_STATUSES: [], PERSONAL_DETAILS_FIELDS: [], EMPTY_PERSONAL_DETAILS: {},
      personalDetailsSchema: require('zod').z.object({}),
      personalDetailsFormValues: () => ({}), personalDetailsPayload: (value) => value,
    },
    '../components/common/FormModal': { __esModule: true, default: FormModal },
    '../components/common/DataTable': { __esModule: true, default: DataTable },
    '../features/employees/EmployeeRelatedPanels': { EmploymentAssignmentsPanel: AssignmentPanel },
    '../features/employees/EmployeeEntitlementsPanel': {
      __esModule: true, default: () => null, EMPLOYEE_ENTITLEMENTS_UPLOADED_EVENT: 'entitlements-uploaded',
    },
    '../features/employees/EntitlementUpload': { __esModule: true, default: EntitlementUpload },
    '../features/employees/EmployeeScheduleAssignmentsPanel': { __esModule: true, default: ScheduleAssignmentsPanel },
    './ScheduleUploads': { ScheduleUploadPanel },
    '../lib/employeeApi': {
      fetchEmployee: async (id) => ({ id, employee_no: '0001' }),
      fetchEmployeePersonalDetails: async () => null,
    },
    '../lib/employeeRelatedApi': {
      createEmploymentAssignmentsBatch: async (rows) => { calls.push(rows); return [{ id: 'assignment' }] },
      EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT: 'assignment-changed',
    },
  }, {
    localStorage: { getItem: () => role },
    window: { dispatchEvent: (event) => calls.push(event.type) },
    Event: class { constructor(type) { this.type = type } },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail } },
  })
  return {
    calls, states, ScheduleUploadPanel, ScheduleAssignmentsPanel, EntitlementUpload,
    render() {
      index = 0
      const page = components.default({ employeeName: 'User' })
      const modal = find(page, (node) => node.type === FormModal)
      const form = modal.props.children({ register: () => ({}), watch: () => '', formState: { errors: {} } })
      const tab = find(form, (node) => node.props.id === 'employee-form-assignments-panel')
      const scheduleTab = find(form, (node) => node.props.id === 'employee-form-schedule-panel')
      const table = find(page, (node) => node.type === DataTable)
      return { page, tab, form, modal, table, scheduleTab, nav: find(page, (node) => node.type === TopNav), panel: find(tab, (node) => node.type === AssignmentPanel) }
    },
  }
}

test('assignment import is offered in HR navigation rather than the Assignments tab', () => {
  const { tab, panel, nav } = harness().render()
  assert.equal(tab.props.role, 'tabpanel')
  assert.ok(nav.props.employeeCsvActions.some((action) => action.label === 'Import employment assignments'))
  assert.equal(panel.props.importActions, undefined)
  assert.equal(panel.props.importPanel, undefined)
})

test('the navigation action toggles the CSV panel and requires HR Admin access', () => {
  const app = harness()
  const action = app.render().nav.props.employeeCsvActions.find((item) => item.label === 'Import employment assignments')
  action.onSelect()
  const panel = find(app.render().page, (node) => node.props['aria-label'] === 'Import employment assignments from CSV')
  assert.ok(panel)
  assert.ok(find(panel, (node) => node.type === 'input' && node.props.type === 'file'))
  assert.match(renderToStaticMarkup(panel), /Download template/)
  const restricted = harness(false, { isAssignmentCsvImportOpen: true }).render()
  assert.equal(restricted.nav.props.employeeCsvActions, undefined)
  assert.equal(find(restricted.page, (node) => node.props['aria-label'] === 'Import employment assignments from CSV'), null)
})

test('employee navigation opens profile, personal-information and entitlement imports with their existing permissions', async () => {
  const app = harness(true, { leaveManage: true })
  const action = (label) => app.render().nav.props.employeeCsvActions.find((item) => item.label === label)
  action('Import employee profiles').onSelect()
  assert.ok(find(app.render().page, (node) => node.props['aria-label'] === 'Import employees from CSV'))
  action('Import personal information').onSelect()
  assert.equal(app.states.isPersonalDetailsImportOpen, true)
  action('Import leave entitlements').onSelect()
  assert.equal(app.states.isEntitlementImportOpen, true)
  const upload = find(app.render().page, (node) => node.type === app.EntitlementUpload)
  assert.equal(upload.props.navigationControlled, true)
  await upload.props.onUploaded({ entitlement_ids: ['entitlement'] })
  assert.ok(app.calls.includes('entitlements-uploaded'))
  assert.equal(harness().render().nav.props.employeeCsvActions.some((item) => item.label === 'Import leave entitlements'), false)
  assert.equal(harness(true, {}, false, 'supervisor').render().nav.props.employeeCsvActions, undefined)
})

test('the relocated apply button still calls the existing batch API and refreshes visible assignments', async () => {
  const payload = { employee_id: 'employee', company_id: 'company' }
  const app = harness(true, {
    isAssignmentCsvImportOpen: true,
    assignmentCsvPreviewRows: [{ rowNumber: 2, employeeNo: '0001', companyCode: 'COMPANY', errors: [], payload }],
  })
  const panel = find(app.render().page, (node) => node.props['aria-label'] === 'Import employment assignments from CSV')
  const button = find(panel, (node) => node.type === 'button' && node.props.children?.some?.((child) => typeof child === 'string' && child.includes('Import all')))
  assert.equal(button.props.disabled, false)
  button.props.onClick()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(app.calls[0][0].assignment, payload)
  assert.equal(app.calls[0][0].row_number, 2)
  assert.equal(app.calls[1], 'assignment-changed')
  assert.equal(app.render().panel.props.refreshVersion, 1)
  assert.match(app.states.assignmentCsvMessage, /imported successfully/)
})

test('the real Assignments panel retains its assignment table', () => {
  const { EmploymentAssignmentsPanel } = loadComponent(join('features', 'employees', 'EmployeeRelatedPanels.tsx'), {
    '../../types/role': { hasPermission: () => false },
  })
  const markup = renderToStaticMarkup(React.createElement(EmploymentAssignmentsPanel, {
    employee: { id: 'employee' }, employees: [], companies: [], orgUnits: [],
  }))
  assert.ok(markup.indexOf('Employment assignments') < markup.indexOf('<table'))
  assert.doesNotMatch(markup, /Import Assignments/)
})

  test('Team Schedule Upload toggles inside the Schedule tab and refreshes manual schedules after submission', () => {
    const app = harness(true, { activeTab: 'schedule' }, true)
    const button = find(app.render().scheduleTab, (node) => node.type === 'button')
    assert.equal(button.props.type, 'button')
    assert.equal(button.props['aria-expanded'], false)
    button.props.onClick()
    const tab = app.render().scheduleTab
    const section = find(tab, (node) => node.props.id === button.props['aria-controls'])
    const upload = find(section, (node) => node.type === app.ScheduleUploadPanel)
    assert.ok(upload)
    upload.props.onSubmitted()
    const manual = find(app.render().scheduleTab, (node) => node.type === app.ScheduleAssignmentsPanel)
    assert.equal(manual.props.refreshVersion, 1)
  })

  test('supervisors can reach the relocated upload without gaining employee-edit or manual-schedule controls', async () => {
    const app = harness(false, {}, true, 'supervisor')
    const { table } = app.render()
    const action = table.props.columns.find((column) => column.key === 'actions').render({ id: 'employee', employee_no: '0001' })
    assert.equal(action.props['aria-label'], 'View schedules for 0001')
    await action.props.onClick()
    const { modal, form, scheduleTab } = app.render()
    assert.equal(app.states.activeTab, 'schedule')
    assert.equal(modal.props.showSubmit, false)
    assert.equal(find(form, (node) => node.type === 'fieldset').props.disabled, true)
    assert.ok(find(scheduleTab, (node) => node.type === 'button'))
    assert.equal(find(scheduleTab, (node) => node.type === app.ScheduleAssignmentsPanel), null)
    assert.equal(find(form, (node) => node.props.id === 'employee-form-assignments-panel'), null)
  })

  test('schedule upload remains permission-gated and is removed from the navigation menu', () => {
    const app = harness(true, { activeTab: 'schedule', isScheduleUploadOpen: true })
    assert.equal(find(app.render().scheduleTab, (node) => node.type === app.ScheduleUploadPanel), null)
    assert.equal(find(app.render().scheduleTab, (node) => node.type === 'button'), null)
    const source = readFileSync(join(__dirname, '..', 'src', 'components', 'dashboard', 'TopNav.tsx'), 'utf8')
    assert.doesNotMatch(source, /label: 'Team Schedule Upload'/)
  })

  for (const hrAdmin of [false, true]) {
    test(`embedded schedule upload preserves ${hrAdmin ? 'HR_ADMIN' : 'Supervisor'} preview, submission, and history`, async () => {
      const cells = []
      let index = 0
      const calls = []
      let submitted = 0
      const batch = { id: 'batch', batch_no: 'B1', supervisor_name: 'Supervisor', status: 'APPROVED' }
      const hooks = {
        useSyncExternalStore: (_subscribe, getSnapshot) => getSnapshot(),
        useEffect: () => {},
        useRef: () => ({ current: null }),
        useState: (initial) => {
          const slot = index++
          if (!(slot in cells)) cells[slot] = initial
          return [cells[slot], (value) => { cells[slot] = typeof value === 'function' ? value(cells[slot]) : value }]
        },
      }
      const { ScheduleUploadPanel } = loadComponent(join('pages', 'ScheduleUploads.tsx'), {
        react: hooks,
        '../types/role': {
          getAvailableRoleCodes: () => ['HR_ADMIN', 'SUPERVISOR'],
          getSelectedDashboardRoleCode: () => hrAdmin ? 'HR_ADMIN' : 'SUPERVISOR',
        },
        '../lib/scheduleUploadApi': {
          isHrScheduleUploadMode: (_roles, selected) => selected === 'HR_ADMIN',
          previewScheduleUpload: async (file, mode) => {
            calls.push(['preview', file, mode])
            return { is_valid: true, rows: [], file_errors: [] }
          },
          submitScheduleUpload: async (file) => { calls.push(['team', file]); return batch },
          submitHrScheduleUpload: async (file) => { calls.push(['hr', file]); return [batch] },
          SCHEDULE_UPLOAD_STATUS_LABELS: { APPROVED: 'Approved' },
        },
        '../components/scheduleUpload/ScheduleUploadParts': {
          ScheduleUploadBatchDetails: () => null, ScheduleUploadStatusBadge: () => null,
        },
      })
      function render() {
        index = 0
        const node = ScheduleUploadPanel({ onSubmitted: () => { submitted += 1 } })
        return node.type(node.props)
      }
      const file = { name: 'team.csv' }
      const tree = render()
      assert.equal(find(tree, (node) => node.type === 'main'), null)
      find(tree, (node) => node.type === 'input').props.onChange({ target: { files: [file] } })
      let button = find(render(), (node) => node.type === 'button' && node.props.children === 'Check file')
      button.props.onClick()
      await new Promise((resolve) => setImmediate(resolve))
      button = find(render(), (node) => node.type === 'button' && node.props.children === 'Submit schedules')
      assert.equal(button.props.disabled, false)
      button.props.onClick()
      await new Promise((resolve) => setImmediate(resolve))
      assert.deepEqual(calls, [['preview', file, hrAdmin], [hrAdmin ? 'hr' : 'team', file]])
      assert.equal(submitted, 1)
      assert.ok(find(render(), (node) => node.props.role === 'status' && typeof node.props.children === 'string' && node.props.children.includes('and applied')))
      assert.match(renderToStaticMarkup(render()), /My uploads/)
    })
  }
