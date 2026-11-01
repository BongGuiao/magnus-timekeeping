const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const axios = require('axios')

function load(client = {}) {
  const source = readFileSync(join(__dirname, '..', 'src', 'lib', 'entitlementUploadApi.ts'), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  runInNewContext(code, {
    exports, FormData,
    require: (name) => name === './apiClient' ? { apiClient: client } : require(name),
  })
  return exports
}

test('downloads the entitlement CSV template as a blob', async () => {
  let request
  const blob = new Blob(['employee_no,leave_code'])
  const api = load({ get: async (...args) => { request = args; return { data: blob } } })
  assert.equal(await api.downloadEntitlementUploadTemplate(), blob)
  assert.equal(request[0], '/employee-entitlements/upload/template')
  assert.equal(request[1].responseType, 'blob')
})

test('preview and apply send the CSV and required preview token as multipart', async () => {
  const requests = []
  const preview = { is_valid: true, rows: [], preview_token: 'a'.repeat(64) }
  const result = { created: 1, updated: 2, employee_ids: ['one'], entitlement_ids: ['two'] }
  const api = load({ post: async (...args) => {
    requests.push(args)
    return { data: { data: args[0].endsWith('/preview') ? preview : result } }
  } })
  const file = new File(['csv-data'], 'balances.csv', { type: 'text/csv' })
  assert.equal(await api.previewEntitlementUpload(file), preview)
  assert.equal(await api.applyEntitlementUpload(file, preview.preview_token), result)
  assert.equal(requests[0][0], '/employee-entitlements/upload/preview')
  assert.equal(requests[0][1].get('file').name, 'balances.csv')
  assert.equal(requests[0][1].get('preview_token'), null)
  assert.equal(requests[1][0], '/employee-entitlements/upload')
  assert.equal(requests[1][1].get('preview_token'), preview.preview_token)
  assert.equal(requests[1][1].get('file').name, 'balances.csv')
  assert.equal(requests[0][2].headers['Content-Type'], 'multipart/form-data')
  assert.equal(requests[1][2].headers['Content-Type'], 'multipart/form-data')
})

test('stale preview and permission errors are surfaced without retrying', async () => {
  const requests = []
  const api = load({ post: async (...args) => {
    requests.push(args[0])
    throw new axios.AxiosError('Conflict', 'ERR_BAD_REQUEST', {}, {}, {
      status: 409, data: { detail: 'Existing balances changed. Check the file again.' },
    })
  } })
  const file = new File(['csv'], 'balances.csv')
  await assert.rejects(api.applyEntitlementUpload(file, 'a'.repeat(64)), /Existing balances changed/)
  assert.deepEqual(requests, ['/employee-entitlements/upload'])
})

test('unreadable validation errors give an explicit retry message', async () => {
  const api = load({ post: async () => {
    throw new axios.AxiosError('Invalid', 'ERR_BAD_REQUEST', {}, {}, {
      status: 422, data: { detail: [{ msg: 'Invalid token' }] },
    })
  } })
  await assert.rejects(
    api.applyEntitlementUpload(new File(['csv'], 'balances.csv'), 'invalid'),
    /Could not confirm the entitlement upload/,
  )
})
