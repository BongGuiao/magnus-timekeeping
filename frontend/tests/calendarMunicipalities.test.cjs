const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return null
  if (predicate(tree)) return tree
  for (const child of React.Children.toArray(tree.props?.children)) {
    const result = find(child, predicate)
    if (result) return result
  }
  return null
}

test('LOCAL holiday submits multiple included and excluded municipalities', async () => {
  let index = 0
  const states = []
  let submitted
  const dependencies = {
    react: {
      ...React,
      useEffect() {},
      useState(initial) {
        const slot = index++
        if (!(slot in states)) states[slot] = typeof initial === 'function' ? initial() : initial
        return [states[slot], (value) => {
          states[slot] = typeof value === 'function' ? value(states[slot]) : value
        }]
      },
    },
    '../components/dashboard/TopNav': { __esModule: true, default: () => null },
    '../components/common/PsgcAddressFields': { __esModule: true, default: () => null },
    '../hooks/useLogout': { useLogout: () => ({ logout() {} }) },
    '../hooks/useCompanySetupSelection': { useCompanySetupSelection: () => ({ companyId: 'company' }) },
    '../lib/companyApi': { fetchCompanies: async () => [] },
    '../lib/psgcApi': {},
    '../lib/holidayCalendarApi': {
      createHoliday: async (payload) => { submitted = payload; return payload },
      fetchHolidays: async () => [],
    },
  }
  const exports = {}
  const source = readFileSync(join(__dirname, '..', 'src', 'pages', 'Calendar.tsx'), 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  runInNewContext(compiled, {
    exports,
    require: (name) => name in dependencies ? dependencies[name] : require(name),
  })
  const render = () => { index = 0; return exports.default({ employeeName: 'Test' }) }
  const labeled = (tree, label, type) => find(find(tree, (node) => node.type === 'label' && React.Children.toArray(node.props.children).includes(label)), (node) => node.type === type)
  let tree = render()
  states[3] = 'calendar'
  tree = render()
  find(tree, (node) => node.type === 'button' && React.Children.toArray(node.props.children).includes('Add date')).props.onClick()
  tree = render()
  labeled(tree, 'Date', 'input').props.onChange({ target: { value: '2026-11-20' } })
  labeled(tree, 'Name', 'input').props.onChange({ target: { value: 'Fiesta' } })
  tree = render()
  labeled(tree, 'Type', 'select').props.onChange({ target: { value: 'LOCAL' } })
  tree = render()
  const address = find(tree, (node) => node.type === dependencies['../components/common/PsgcAddressFields'].default)
  address.props.onChange('region', 'Region VII')
  address.props.onChange('psgc_region_code', '070000000')
  address.props.onChange('province', 'Cebu')
  address.props.onChange('psgc_province_code', '072200000')
  states[14] = [
    { code: '111111111', name: 'First' },
    { code: '222222222', name: 'Second' },
    { code: '333333333', name: 'Third' },
  ]
  tree = render()
  const toggle = (group, city) => {
    const fieldset = find(tree, (node) => node.type === 'fieldset' && find(node, (child) => child.type === 'legend' && child.props.children === group))
    const label = find(fieldset, (node) => node.type === 'label' && React.Children.toArray(node.props.children).includes(city))
    find(label, (node) => node.type === 'input').props.onChange()
    tree = render()
  }
  toggle('Include municipalities', 'First')
  toggle('Include municipalities', 'Second')
  toggle('Exclude municipalities', 'Second')
  toggle('Exclude municipalities', 'Third')
  find(tree, (node) => node.type === 'button' && node.props.children === 'Use this area').props.onClick()
  tree = render()
  find(tree, (node) => node.type === 'button' && node.props.children === 'Change area').props.onClick()
  tree = render()
  const changedAddress = find(tree, (node) => node.type === dependencies['../components/common/PsgcAddressFields'].default)
  changedAddress.props.onChange('province', 'Bohol')
  changedAddress.props.onChange('psgc_province_code', '071200000')
  tree = render()
  const include = find(tree, (node) => node.type === 'fieldset' && find(node, (child) => child.type === 'legend' && child.props.children === 'Include municipalities'))
  assert.equal(find(include, (node) => node.type === 'input').props.checked, false)
  find(tree, (node) => node.type === 'button' && node.props.children === 'Cancel').props.onClick()
  tree = render()
  await find(tree, (node) => node.type === 'form' && find(node, (child) => child.type === 'input' && child.props.type === 'date')).props.onSubmit({ preventDefault() {} })
  assert.deepEqual(Array.from(submitted.included_municipalities, (item) => item.code), ['111111111', '222222222'])
  assert.deepEqual(Array.from(submitted.excluded_municipalities, (item) => item.code), ['222222222', '333333333'])
  assert.equal(submitted.province, 'Cebu')
  assert.equal(submitted.holiday_type, 'LOCAL')
})
