const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const React = require('react')
const ts = require('typescript')

function load(file, mocks, globals = {}) {
  const code = ts.transpileModule(readFileSync(join(__dirname, '..', 'src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const exports = {}
  runInNewContext(code, {
    exports, ...globals,
    require: (name) => name in mocks ? mocks[name] : name.startsWith('.') ? {} : require(name),
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

function count(node, predicate) {
  if (Array.isArray(node)) return node.reduce((total, child) => total + count(child, predicate), 0)
  if (!React.isValidElement(node)) return 0
  return Number(predicate(node)) + count(node.props.children, predicate)
}

function harness(overrides = {}) {
  const cells = []
  let index = 0
  const changes = []
  const effects = []
  const listeners = new Map()
  const props = {
    label: 'Company', value: 'a',
    options: [{ value: '', label: 'None' }, { value: 'a', label: 'ACME — Acme Company' }, { value: 'b', label: 'BETA — Beta Corporation' }],
    onChange: (value) => { changes.push(value); props.value = value },
    ...overrides,
  }
  const hooks = {
    useId: () => 'lookup',
    useRef: (initial) => {
      const slot = index++
      if (!(slot in cells)) cells[slot] = { current: initial }
      return cells[slot]
    },
    useState: (initial) => {
      const slot = index++
      if (!(slot in cells)) cells[slot] = initial
      return [cells[slot], (value) => { cells[slot] = typeof value === 'function' ? value(cells[slot]) : value }]
    },
    useLayoutEffect: (callback) => effects.push(callback),
  }
  const { default: Select } = load(join('components', 'common', 'SearchableSelect.tsx'), {
    react: hooks, 'react-dom': { createPortal: (node) => node },
  }, {
    document: { body: {} },
    window: {
      innerHeight: 600,
      addEventListener: (name, callback) => listeners.set(name, callback),
      removeEventListener: (name) => listeners.delete(name),
    },
  })
  function render() {
    index = 0
    effects.length = 0
    return Select(props)
  }
  function input() { return find(render(), (node) => node.type === 'input') }
  function key(key) {
    const event = { key, prevented: false, stopped: false, preventDefault() { this.prevented = true }, stopPropagation() { this.stopped = true } }
    input().props.onKeyDown(event)
    return event
  }
  return { render, input, key, changes, props, effects, listeners }
}

test('search filters codes and names case-insensitively without clearing the existing selection', () => {
  const app = harness()
  assert.equal(app.input().props.value, 'ACME — Acme Company')
  app.input().props.onFocus()
  app.input().props.onChange({ target: { value: ' CoRp ' } })
  assert.ok(find(app.render(), (node) => node.props.role === 'option' && node.props.children === 'BETA — Beta Corporation'))
  assert.equal(find(app.render(), (node) => node.props.role === 'option' && node.props.children === 'ACME — Acme Company'), null)
  assert.deepEqual(app.changes, [])
  app.input().props.onBlur()
  assert.equal(app.input().props.value, 'ACME — Acme Company')
  assert.equal(app.input().props['aria-expanded'], false)
})

test('keyboard selection commits the option ID and never submits the employee form', () => {
  const app = harness()
  app.input().props.onFocus()
  app.input().props.onChange({ target: { value: 'beta' } })
  app.key('ArrowDown')
  const event = app.key('Enter')
  assert.equal(event.prevented, true)
  assert.equal(event.stopped, true)
  assert.deepEqual(app.changes, ['b'])
  assert.equal(app.input().props.value, 'BETA — Beta Corporation')
})

test('Escape closes only the options, preserving the value and stopping the dialog Escape handler', () => {
  const app = harness()
  app.input().props.onFocus()
  const event = app.key('Escape')
  assert.equal(event.prevented, true)
  assert.equal(event.stopped, true)
  assert.equal(app.input().props['aria-expanded'], false)
  assert.deepEqual(app.changes, [])
})

test('mouse selection and explicit None work without moving focus away from the combobox', () => {
  const app = harness()
  app.input().props.onFocus()
  const list = find(app.render(), (node) => node.props.role === 'listbox')
  let prevented = false
  list.props.onMouseDown({ preventDefault() { prevented = true } })
  assert.equal(prevented, true)
  find(app.render(), (node) => node.props.role === 'option' && node.props.children === 'None').props.onClick()
  assert.deepEqual(app.changes, [''])
  app.props.value = 'b'
  assert.equal(app.input().props.value, 'BETA — Beta Corporation')
})

test('disabled controls and disabled parent fieldsets cannot change selection', () => {
  const app = harness({ disabled: true })
  assert.equal(app.input().props.disabled, true)
  assert.equal(find(app.render(), (node) => node.props.role === 'listbox'), null)
  app.props.disabled = false
  app.input().props.ref({ matches: () => true })
  app.input().props.onFocus()
  find(app.render(), (node) => node.props.role === 'option' && node.props.children === 'None').props.onClick()
  assert.deepEqual(app.changes, [])
})

test('large lists render a bounded set while later entries remain searchable', () => {
  const options = Array.from({ length: 1000 }, (_, index) => ({ value: String(index), label: `Employee ${index}` }))
  const app = harness({ options, value: 'missing' })
  assert.equal(app.input().props.value, 'Previously selected option unavailable')
  app.input().props.onFocus()
  const list = find(app.render(), (node) => node.props.role === 'listbox')
  assert.equal(count(list, (node) => node.props.role === 'option'), 100)
  assert.ok(find(app.render(), (node) => node.props.role === 'status' && String(node.props.children).includes('Refine your search')))
  app.input().props.onChange({ target: { value: 'Employee 999' } })
  assert.ok(find(app.render(), (node) => node.props.role === 'option' && node.props.children === 'Employee 999'))
  app.input().props.onChange({ target: { value: 'no such employee' } })
  assert.ok(find(app.render(), (node) => node.props.role === 'status'))
  app.key('Enter')
  assert.deepEqual(app.changes, [])
})

test('popup stays within the viewport and tracks resize and ancestor scroll', () => {
  const app = harness()
  app.input().props.ref({
    getBoundingClientRect: () => ({ left: 20, width: 300, bottom: 560, top: 530 }),
  })
  app.input().props.onFocus()
  app.render()
  const cleanup = app.effects[0]()
  const list = find(app.render(), (node) => node.props.role === 'listbox')
  assert.equal(list.props.style.top, 286)
  assert.equal(list.props.style.width, 300)
  assert.ok(app.listeners.has('scroll'))
  assert.ok(app.listeners.has('resize'))
  cleanup()
  assert.equal(app.listeners.size, 0)
})

test('assignment company selection preserves dependent resets and React Hook Form wiring', () => {
  const values = {}
  const mutations = []
  const Controller = () => null
  const SearchableSelect = () => null
  const { EmploymentAssignmentsPanel } = load(join('features', 'employees', 'EmployeeRelatedPanels.tsx'), {
    react: { useEffect: () => {}, useRef: (value) => ({ current: value }), useState: (value) => [value, () => {}] },
    'react-hook-form': {
      Controller,
      useForm: ({ defaultValues }) => {
        Object.assign(values, defaultValues)
        return {
          control: {}, register: () => ({}), reset() {}, handleSubmit: (callback) => callback,
          watch: (name) => values[name], setValue: (name, value) => mutations.push([name, value]),
          formState: { errors: {}, isSubmitting: false },
        }
      },
    },
    '../../components/common/SearchableSelect': { __esModule: true, default: SearchableSelect },
    '../../types/role': { hasPermission: () => true },
  })
  const panel = EmploymentAssignmentsPanel({ employee: { id: 'employee' }, employees: [], companies: [{ id: 'company', company_code: 'ACME', legal_name: 'Acme' }], orgUnits: [] })
  const company = find(panel, (node) => node.type === Controller && node.props.name === 'company_id')
  let selected
  const ref = () => {}
  const blur = () => {}
  const control = company.props.render({ field: { name: 'company_id', value: '', onChange: (value) => { selected = value }, ref, onBlur: blur } })
  assert.equal(control.props.inputRef, ref)
  assert.equal(control.props.onBlur, blur)
  control.props.onChange('company')
  assert.equal(selected, 'company')
  assert.deepEqual(mutations.map(([name]) => name), ['org_unit_id', 'operational_group', 'primary_location_id', 'location_ids', 'authorized_geofence_ids', 'payroll_group_id'])
  assert.equal(control.props.options[1].value, 'company')
})
