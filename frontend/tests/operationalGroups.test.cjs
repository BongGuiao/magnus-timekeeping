const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const axios = require('axios')

function loadApi(client) {
  const source = readFileSync(join(__dirname, '..', 'src', 'lib', 'operationalGroupApi.ts'), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  const events = []
  runInNewContext(code, {
    exports,
    require: (name) => name === './apiClient' ? { apiClient: client } : require(name),
    Event: class { constructor(type) { this.type = type } },
    window: { dispatchEvent: (event) => events.push(event.type) },
  })
  return { api: exports, events }
}

test('lookup requests active groups for the selected company and accepts custom codes', async () => {
  let request
  const groups = [{ company_id: 'company-a', operational_group: 'NEW_GROUP', display_name: 'New group', sort_order: 0, is_active: true }]
  const { api } = loadApi({ get: async (...args) => { request = args; return { data: { data: groups } } } })
  assert.equal(await api.fetchOperationalGroups('company-a'), groups)
  assert.equal(request[0], '/operational-groups/list')
  assert.equal(request[1].params.company_id, 'company-a')
  assert.equal(request[1].params.include_inactive, false)
  await api.fetchOperationalGroups('company-b', true)
  assert.equal(request[1].params.company_id, 'company-b')
  assert.equal(request[1].params.include_inactive, true)
})

test('creation returns the saved group and refreshes open assignment lookups', async () => {
  let request
  const group = { company_id: 'company-a', operational_group: 'NEW_GROUP', display_name: 'New group', sort_order: 0, is_active: true }
  const { api, events } = loadApi({ post: async (...args) => { request = args; return { data: { data: group } } } })
  assert.equal(await api.createOperationalGroup(group), group)
  assert.equal(request[0], '/operational-groups/create')
  assert.equal(request[1], group)
  assert.deepEqual(events, [api.OPERATIONAL_GROUPS_CHANGED_EVENT])
})

test('update sends company and immutable code separately from editable metadata', async () => {
  let request
  const payload = { display_name: 'Updated', sort_order: 4, is_active: false }
  const { api, events } = loadApi({ put: async (...args) => { request = args; return { data: { data: payload } } } })
  assert.equal(await api.updateOperationalGroup('company-a', 'NEW_GROUP', payload), payload)
  assert.equal(request[0], '/operational-groups/NEW_GROUP')
  assert.equal(request[1], payload)
  assert.equal(request[2].params.company_id, 'company-a')
  assert.deepEqual(events, [api.OPERATIONAL_GROUPS_CHANGED_EVENT])
})

test('failures surface server detail or fallback without a success event or fixed-list fallback', async () => {
  for (const detail of ['Group already exists.', undefined]) {
    const failure = new axios.AxiosError('failed', 'ERR_BAD_REQUEST', {}, {}, { status: 409, data: { detail } })
    const reject = async () => { throw failure }
    const { api, events } = loadApi({ get: reject, post: reject, put: reject })
    await assert.rejects(api.fetchOperationalGroups('company-a'), (error) => error.message === (detail ?? 'Could not load operational groups.'))
    await assert.rejects(api.createOperationalGroup({}), (error) => error.message === (detail ?? 'Could not create the operational group.'))
    await assert.rejects(api.updateOperationalGroup('company-a', 'NEW', {}), (error) => error.message === (detail ?? 'Could not update the operational group.'))
    assert.deepEqual(events, [])
  }
})

test('unexpected errors are not disguised as empty lookup lists', async () => {
  const failure = new TypeError('unexpected')
  const { api } = loadApi({ get: async () => { throw failure } })
  await assert.rejects(api.fetchOperationalGroups('company-a'), (error) => error === failure)
})

test('invalid API responses surface a routing error instead of crashing the table', async () => {
  for (const body of [
    '<!doctype html><html></html>',
    {},
    { data: null },
    { data: {} },
  ]) {
    const { api } = loadApi({ get: async () => ({ data: body }) })
    await assert.rejects(
      api.fetchOperationalGroups('company-a'),
      /Invalid operational groups response.*JSON list.*API routing/,
    )
  }
})

test('an empty operational groups list is a valid response', async () => {
  const groups = []
  const { api } = loadApi({ get: async () => ({ data: { data: groups } }) })
  assert.equal(await api.fetchOperationalGroups('company-a'), groups)
})

test('both nginx environments and Vite proxy the new API prefix', () => {
  for (const parts of [['nginx', 'dev.conf'], ['nginx', 'default.conf'], ['frontend', 'vite.config.ts']]) {
    const source = readFileSync(join(__dirname, '..', '..', ...parts), 'utf8')
    assert.match(source, /org-units\|operational-groups\|locations/)
  }
})
