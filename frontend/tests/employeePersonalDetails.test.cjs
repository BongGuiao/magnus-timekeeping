const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

function loadModule(name) {
  const compiled = ts.transpileModule(readFileSync(join(__dirname, '..', 'src', 'lib', `${name}.ts`), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  runInNewContext(compiled, { exports, require: (path) => path === './employeeCsv' ? loadModule('employeeCsv') : require(path) })
  return exports
}

const { parsePersonalDetailsCsv, personalDetailsCsvTemplate, personalDetailsFormValues, personalDetailsPayload } = loadModule('employeePersonalDetails')

test('employee CSV export is visible only with the HR_ADMIN role, selected mode, and management permission', () => {
  const compiled = ts.transpileModule(readFileSync(join(__dirname, '..', 'src', 'pages', 'Employees.tsx'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  for (const [roles, selected, manage, expected] of [
    [['HR_ADMIN'], 'HR_ADMIN', true, true],
    [['SYSTEM_ADMIN'], 'SYSTEM_ADMIN', true, false],
    [['SYSTEM_ADMIN'], 'HR_ADMIN', true, false],
    [['HR_ADMIN', 'SUPERVISOR'], 'SUPERVISOR', true, false],
    [['HR_ADMIN'], 'HR_ADMIN', false, false],
  ]) {
    const exports = {}
    runInNewContext(compiled, {
      exports,
      localStorage: { getItem: () => 'admin' },
      require(name) {
        if (name === 'react') return { ...React, useSyncExternalStore: (_subscribe, getSnapshot) => getSnapshot() }
        if (name === '../types/role') return {
          hasPermission: (permission) => manage && permission === 'employees.manage',
          getAvailableRoleCodes: () => roles,
          getSelectedDashboardRoleCode: () => selected,
        }
        if (name === '../lib/employeePersonalDetails') return loadModule('employeePersonalDetails')
        if (name === '../hooks/useLogout') return { useLogout: () => ({ logout() {} }) }
        if (name === '../components/dashboard/WorkspaceTabsContext') return { useWorkspaceTabs: () => null }
        if (name.startsWith('../components/') || name === '../features/employees/EmployeePersonalDetailsImport') {
          return { __esModule: true, default: () => null }
        }
        if (name.startsWith('../') || name === './ScheduleUploads') return {}
        return require(name)
      },
    })
    const html = renderToStaticMarkup(React.createElement(exports.default, { employeeName: 'Test Admin' }))
    assert.equal(html.includes('Export CSV'), expected, `${roles}/${selected}/${manage}`)
  }
})

test('employee export transport sends HR mode and rejects non-CSV responses', async () => {
  let contentType = 'text/csv; charset=utf-8'
  const blob = new Blob(['employee_no\r\nEMP001\r\n'], { type: 'text/csv' })
  const compiled = ts.transpileModule(readFileSync(join(__dirname, '..', 'src', 'lib', 'employeeApi.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  runInNewContext(compiled, {
    exports, Blob,
    require(name) {
      if (name === './apiClient') return { apiClient: {
        async get(path, options) {
          assert.equal(path, '/employees/export')
          assert.equal(options.params.dashboard_role_code, 'HR_ADMIN')
          assert.equal(options.responseType, 'blob')
          return { data: blob, headers: { 'content-type': contentType } }
        },
      } }
      return require(name)
    },
  })
  assert.equal(await exports.exportEmployeesCsv(), blob)
  contentType = 'text/html'
  await assert.rejects(exports.exportEmployeesCsv(), /did not return a CSV file/)
})

test('downloaded template includes a complete example and rejects unchanged placeholders', () => {
  const template = personalDetailsCsvTemplate()
  const [header, sample] = template.trim().split('\r\n').map((line) => line.split(','))
  assert.equal(header.length, sample.length)
  assert.ok(sample.every(Boolean))
  assert.equal(sample[header.indexOf('civil_status')], 'SINGLE')
  assert.throws(() => parsePersonalDetailsCsv(template), /replace or remove every EXAMPLE_ value/)
  const partial = template.replace('EXAMPLE_EMP001', 'EMP-001')
  assert.throws(() => parsePersonalDetailsCsv(partial), /replace or remove every EXAMPLE_ value/)
  const completed = template.replaceAll('EXAMPLE_', '')
  const [row] = parsePersonalDetailsCsv(completed)
  assert.equal(row.employee_no, 'EMP001')
  assert.equal(row.bank_account_no, '000123456789')
  assert.equal(row.region, 'Region')
  assert.equal(row.city_municipality, 'City')
})

test('saved employee example is correctly escaped and can be parsed without changing values', () => {
  const example = {
    employee_no: 'EMP-001', bank_account_no: '000123456', sss_no: null, pagibig_no: null,
    philhealth_no: null, tin_no: null, address_line_1: 'Unit 1, "Sample" Street',
    address_line_2: 'Floor 2\nBuilding A', region: null, province: null,
    city_municipality: null, barangay: null, postal_code: '0100', civil_status: 'SINGLE',
  }
  const [row] = parsePersonalDetailsCsv(personalDetailsCsvTemplate(example))
  assert.equal(row.employee_no, example.employee_no)
  assert.equal(row.bank_account_no, '000123456')
  assert.equal(row.address_line_1, example.address_line_1)
  assert.equal(row.address_line_2, example.address_line_2)
  assert.equal(row.postal_code, '0100')
  assert.equal(row.sss_no, null)
})

test('spreadsheet formula-like values prevent exporting a template', () => {
  for (const value of ['=1+1', ' +command', '-1', '@SUM(1,1)']) {
    assert.throws(
      () => personalDetailsCsvTemplate({ employee_no: 'EMP-001', address_line_1: value }),
      /address_line_1.*spreadsheet formula/,
    )
  }
})

test('CSV preserves leading zeroes, quoted addresses, and partial uploads', () => {
  const rows = parsePersonalDetailsCsv('\uFEFFemployee_no,bank_account_no,address_line_1,civil_status\r\nE001,000123,"Unit 1, Test Street",single\r\n')
  assert.equal(rows[0].bank_account_no, '000123')
  assert.equal(rows[0].address_line_1, 'Unit 1, Test Street')
  assert.equal(rows[0].civil_status, 'SINGLE')
  assert.equal(rows[0].sss_no, null)
})

test('CSV rejects malformed files, duplicate employees/headers, invalid status and excessive lengths', () => {
  for (const csv of [
    'employee_no,sss_no\nE1,"123',
    'employee_no,sss_no\nE1,1\nE1,2',
    'employee_no,sss_no,sss_no\nE1,1,2',
    'employee_no,civil_status\nE1,INVALID',
    'employee_no,sss_no\n,123',
    `employee_no,sss_no\nE1,${'1'.repeat(31)}`,
    'employee_no,unknown\nE1,value',
    'employee_no\n',
    `employee_no\n${Array.from({ length: 501 }, (_, index) => `E${index}`).join('\n')}`,
  ]) assert.throws(() => parsePersonalDetailsCsv(csv))
})

test('loaded details round-trip without dropping identifiers and blank fields become null', () => {
  const values = personalDetailsFormValues({ bank_account_no: '000123', sss_no: '000456', civil_status: 'MARRIED' })
  const payload = personalDetailsPayload(values)
  assert.equal(payload.bank_account_no, '000123')
  assert.equal(payload.sss_no, '000456')
  assert.equal(payload.civil_status, 'MARRIED')
  assert.equal(payload.address_line_1, null)
})

test('PSGC selections round-trip while legacy address text remains unchanged', () => {
  const legacy = personalDetailsPayload(personalDetailsFormValues({
    province: 'Saved province', city_municipality: 'Saved city', barangay: 'Saved barangay',
  }))
  assert.equal(legacy.province, 'Saved province')
  assert.equal(legacy.city_municipality, 'Saved city')
  assert.equal(legacy.barangay, 'Saved barangay')
  assert.equal(legacy.psgc_region_code, null)
  const selected = personalDetailsPayload(personalDetailsFormValues({
    region: 'Region', province: 'Province', city_municipality: 'City', barangay: 'Barangay',
    psgc_region_code: '010000000', psgc_province_code: '010010000',
    psgc_city_code: '010010100', psgc_barangay_code: '010010101',
  }))
  assert.equal(selected.psgc_region_code, '010000000')
  assert.equal(selected.psgc_barangay_code, '010010101')
})

test('CSV uploads address text only and never sends PSGC codes', () => {
  const [row] = parsePersonalDetailsCsv('employee_no,region,province,city_municipality,barangay\nE1,Region,Province,City,Barangay')
  assert.equal(row.region, 'Region')
  assert.equal(row.city_municipality, 'City')
  assert.equal('psgc_region_code' in row, false)
  assert.throws(() => parsePersonalDetailsCsv('employee_no,psgc_city_code\nE1,010010100'))
})
