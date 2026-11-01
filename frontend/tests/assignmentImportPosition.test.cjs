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
    isLoading: false,
    assignmentLookups: { loaded: true, error: '', locations: [], payrollGroups: [] },
    ...overrides,
  }
  let index = 0
  const calls = []
  const FormModal = () => null
  const AssignmentPanel = () => null
  const ScheduleUploadPanel = () => null
  const ScheduleAssignmentsPanel = () => null
  const DataTable = () => null
  const hooks = {
    useId: () => 'employee-form',
    useEffect: () => {},
    useState: (initial) => {
      const name = stateNames[index++]
      if (!(name in states)) states[name] = initial
      return [states[name], (value) => { states[name] = typeof value === 'function' ? value(states[name]) : value }]
    },
  }
  const components = loadComponent(join('pages', 'Employees.tsx'), {
    react: hooks,
    '../hooks/useLogout': { useLogout: () => ({ logout() {} }) },
    '../types/role': { hasPermission: (permission) => (permission === 'employees.manage' && canManage) || (permission === 'schedule.upload_team' && canUploadSchedules) },
    '../components/common/FormModal': { __esModule: true, default: FormModal },
    '../components/common/DataTable': { __esModule: true, default: DataTable },
    '../features/employees/EmployeeRelatedPanels': { EmploymentAssignmentsPanel: AssignmentPanel },
    '../features/employees/EmployeeScheduleAssignmentsPanel': { __esModule: true, default: ScheduleAssignmentsPanel },
    './ScheduleUploads': { ScheduleUploadPanel },
    '../lib/employeeApi': { fetchEmployee: async (id) => ({ id, employee_no: '0001' }) },
    '../lib/employeeRelatedApi': {
      createEmploymentAssignmentsBatch: async (rows) => { calls.push(rows); return [{ id: 'assignment' }] },
      EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT: 'assignment-changed',
    },
  }, {
    localStorage: { getItem: () => role },
    window: { dispatchEvent: (event) => calls.push(event.type) },
    Event: class { constructor(type) { this.type = type } },
  })
  return {
    calls, states, ScheduleUploadPanel, ScheduleAssignmentsPanel,
    render() {
      index = 0
      const page = components.default({ employeeName: 'User' })
      const modal = find(page, (node) => node.type === FormModal)
      const form = modal.props.children({ register: () => ({}), formState: { errors: {} } })
      const tab = find(form, (node) => node.props.id === 'employee-form-assignments-panel')
      const scheduleTab = find(form, (node) => node.props.id === 'employee-form-schedule-panel')
      const table = find(page, (node) => node.type === DataTable)
      return { page, tab, form, modal, table, scheduleTab, panel: find(tab, (node) => node.type === AssignmentPanel) }
    },
  }
}

test('assignment import and template controls live inside the Assignments tab, not the page toolbar', () => {
  const { page, tab, panel } = harness().render()
  const main = find(page, (node) => node.type === 'main')
  assert.equal(find(main, (node) => node.type === 'button' && node.props.children.includes?.('Import Assignments')), null)
  assert.equal(tab.props.role, 'tabpanel')
  const markup = renderToStaticMarkup(panel.props.importActions)
  assert.match(markup, /Import Assignments/)
  assert.match(markup, /Download template/)
  assert.equal(panel.props.importPanel, false)
})

test('the relocated button toggles the existing CSV panel and retains its permission gate', () => {
  const app = harness()
  const button = find(app.render().panel.props.importActions, (node) => node.type === 'button' && node.props['aria-controls'])
  assert.equal(button.props.type, 'button')
  button.props.onClick()
  const panel = app.render().panel
  assert.equal(panel.props.importPanel.props.id, button.props['aria-controls'])
  assert.equal(panel.props.importPanel.props['aria-label'], 'Import employment assignments from CSV')
  assert.ok(find(panel.props.importPanel, (node) => node.type === 'input' && node.props.type === 'file'))
  const restricted = harness(false, { isAssignmentCsvImportOpen: true }).render().panel
  assert.equal(restricted.props.importActions, false)
  assert.equal(restricted.props.importPanel, false)
})

test('the relocated apply button still calls the existing batch API and refreshes visible assignments', async () => {
  const payload = { employee_id: 'employee', company_id: 'company' }
  const app = harness(true, {
    isAssignmentCsvImportOpen: true,
    assignmentCsvPreviewRows: [{ rowNumber: 2, employeeNo: '0001', companyCode: 'COMPANY', errors: [], payload }],
  })
  const button = find(app.render().panel.props.importPanel, (node) => node.type === 'button')
  assert.equal(button.props.disabled, false)
  button.props.onClick()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(app.calls[0][0].assignment, payload)
  assert.equal(app.calls[0][0].row_number, 2)
  assert.equal(app.calls[1], 'assignment-changed')
  assert.equal(app.render().panel.props.refreshVersion, 1)
  assert.match(app.states.assignmentCsvMessage, /imported successfully/)
})

test('the real Assignments panel renders header controls and CSV preview before the assignment table', () => {
  const { EmploymentAssignmentsPanel } = loadComponent(join('features', 'employees', 'EmployeeRelatedPanels.tsx'), {
    '../../types/role': { hasPermission: () => false },
  })
  const markup = renderToStaticMarkup(React.createElement(EmploymentAssignmentsPanel, {
    employee: { id: 'employee' }, employees: [], companies: [], orgUnits: [],
    importActions: React.createElement('button', { type: 'button' }, 'Import Assignments'),
    importPanel: React.createElement('section', null, 'CSV preview'),
  }))
  assert.ok(markup.indexOf('Employment assignments') < markup.indexOf('Import Assignments'))
  assert.ok(markup.indexOf('Import Assignments') < markup.indexOf('CSV preview'))
  assert.ok(markup.indexOf('CSV preview') < markup.indexOf('<table'))
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
