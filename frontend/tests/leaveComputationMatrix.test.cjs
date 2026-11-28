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

function createPage({ companies = [{ id: 'company-one', company_code: 'C1', legal_name: 'Company One' }], companyError = null, companyRequest = null } = {}) {
  const states = [], refs = [], exports = {}
  let stateIndex = 0, refIndex = 0, effect
  const saves = [], loads = []
  const source = readFileSync(join(__dirname, '..', 'src', 'pages', 'LeaveComputationMatrix.tsx'), 'utf8')
  runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, {
    exports, window: { confirm: () => true },
    require(name) {
      if (name === 'react') return {
        ...React,
        useState(initial) {
          const index = stateIndex++
          if (!(index in states)) states[index] = typeof initial === 'function' ? initial() : initial
          return [states[index], (value) => { states[index] = typeof value === 'function' ? value(states[index]) : value }]
        },
        useRef(initial) { return refs[refIndex++] ??= { current: initial } },
        useEffect(callback) { effect = callback },
      }
      if (name === '../components/dashboard/TopNav') return { __esModule: true, default: () => null }
      if (name === '../hooks/useLogout') return { useLogout: () => ({ logout() {} }) }
      if (name === '../lib/leaveMatrixApi') return {
        fetchMatrixCompanies: async () => { if (companyError) throw new Error(companyError); return companyRequest ? companyRequest : companies },
        fetchLeaveMatrix: async (id) => { loads.push(id); return { company_id: id, row_version: 0, ranges: [] } },
        saveLeaveMatrix: async (id, payload) => {
          saves.push({ id, payload })
          return { company_id: id, row_version: 1, ranges: payload.ranges }
        },
      }
      return require(name)
    },
  })
  return {
    render() { stateIndex = 0; refIndex = 0; return exports.default({ employeeName: 'Test' }) },
    mount() { return effect() },
    setCompanyError(value) { companyError = value },
    saves, loads,
  }
}

test('company matrix saves fixed decimal ranges without activating computation', async () => {
  const page = createPage()
  page.render()
  page.mount()
  await new Promise((resolve) => setImmediate(resolve))
  let tree = page.render()
  assert.deepEqual(page.loads, ['company-one'])
  assert.ok(find(tree, (node) => node.props?.children && React.Children.toArray(node.props.children).includes('Company: ')))
  assert.ok(find(tree, (node) => typeof node.props?.children === 'string' && node.props.children.includes('do not affect leave calculations')))
  find(tree, (node) => node.type === 'button' && React.Children.toArray(node.props.children).includes(' Add range')).props.onClick()
  for (const [label, value] of [['worked from row 1', '0.00'], ['worked to row 1', '3.99'], ['leave hours row 1', '4.50']]) {
    tree = page.render()
    find(tree, (node) => node.props?.['aria-label'] === label).props.onChange({ target: { value } })
  }
  tree = page.render()
  find(tree, (node) => node.type === 'form').props.onSubmit({ preventDefault() {} })
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(page.saves[0].id, 'company-one')
  assert.equal(page.saves[0].payload.ranges[0].leave_hours, '4.50')
  assert.equal(page.saves[0].payload.row_version, 0)
  assert.ok(find(page.render(), (node) => node.props?.role === 'status'))
})

test('missing assignment or invalid company response blocks matrix loading', async () => {
  for (const options of [{ companies: [] }, { companyError: 'No active employee company assignment was found. Contact HR.' }, { companyError: 'You do not have leave management access for your assigned company.' }]) {
    const page = createPage(options)
    page.render()
    page.mount()
    await new Promise((resolve) => setImmediate(resolve))
    const tree = page.render()
    assert.ok(find(tree, (node) => node.props?.role === 'alert'))
    assert.equal(find(tree, (node) => node.type === 'form'), null)
    assert.equal(page.loads.length, 0)
  }
})

test('retry resolves assignment before loading the matrix', async () => {
  const page = createPage({ companyError: 'No active employee company assignment was found. Contact HR.' })
  page.render()
  const cleanup = page.mount()
  await new Promise((resolve) => setImmediate(resolve))
  const retry = find(page.render(), (node) => node.type === 'button' && node.props.children === 'Retry loading')
  assert.equal(page.loads.length, 0)
  page.setCompanyError(null)
  retry.props.onClick()
  cleanup()
  page.render()
  page.mount()
  await new Promise((resolve) => setImmediate(resolve))
  assert.deepEqual(page.loads, ['company-one'])
  assert.ok(find(page.render(), (node) => node.type === 'form'))
})

test('does not fetch a matrix if assignment resolution completes after unmount', async () => {
  let resolveCompany
  const companyRequest = new Promise((resolve) => { resolveCompany = resolve })
  const page = createPage({ companyRequest })
  page.render()
  const cleanup = page.mount()
  assert.equal(page.loads.length, 0)
  cleanup()
  resolveCompany([{ id: 'company-one', company_code: 'C1', legal_name: 'Company One' }])
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(page.loads.length, 0)
})
test('matrix endpoints are proxied to the backend in development and production', () => {
  for (const parts of [['nginx', 'dev.conf'], ['nginx', 'default.conf'], ['frontend', 'vite.config.ts']]) {
    const source = readFileSync(join(__dirname, '..', '..', ...parts), 'utf8')
    const match = parts[0] === 'nginx'
      ? source.match(/location ~ (\^\/\(api\|[^\s]+)\s*\{/)
      : source.match(/'(\^\/\(api\|[^']+)'/)
    assert.ok(match, parts.join('\\'))
    const route = new RegExp(match[1].replaceAll('\\\\', '\\'))
    assert.ok(route.test('/leave-computation-matrices/companies'), parts.join('\\'))
    assert.ok(route.test('/leave-computation-matrices/12345678-1234-1234-1234-123456789012'), parts.join('\\'))
    assert.equal(route.test('/leave-computation-matrix'), false, parts.join('\\'))
  }
})

test('HTML or malformed API responses produce actionable errors instead of undefined values', async () => {
  const exports = {}
  let response = { data: '<html>frontend</html>' }
  const source = readFileSync(join(__dirname, '..', 'src', 'lib', 'leaveMatrixApi.ts'), 'utf8')
  runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText, {
    exports,
    require(name) {
      if (name === './apiClient') return { apiClient: { get: async () => response, put: async () => response } }
      return require(name)
    },
  })
  await assert.rejects(exports.fetchMatrixCompanies(), /Invalid company list response.*backend and web proxy/)
  response = { data: { status: 'success', data: [{ id: 'company' }] } }
  await assert.rejects(exports.fetchMatrixCompanies(), /Invalid company list response/)
  response = { data: '<html>frontend</html>' }
  await assert.rejects(exports.fetchLeaveMatrix('company'), /Invalid leave matrix response/)
  await assert.rejects(exports.saveLeaveMatrix('company', { row_version: 0, ranges: [] }), /Invalid leave matrix response/)
  response = { data: { status: 'success', data: [] } }
  assert.equal((await exports.fetchMatrixCompanies()).length, 0)
  response = { data: { status: 'success', data: { company_id: 'company', row_version: 0, ranges: [] } } }
  assert.equal((await exports.fetchLeaveMatrix('company')).row_version, 0)
  response = { data: { status: 'success', data: { company_id: 'wrong', row_version: 0, ranges: [] } } }
  await assert.rejects(exports.fetchLeaveMatrix('company'), /Invalid leave matrix response/)
})
