const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const axios = require('axios')

function load(client = {}) {
  const source = readFileSync(join(__dirname, '..', 'src', 'lib', 'scheduleUploadApi.ts'), 'utf8')
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

test('HR upload mode requires both the assigned role and the exact selected role code', () => {
  const { isHrScheduleUploadMode } = load()
  assert.equal(isHrScheduleUploadMode(['HR_ADMIN', 'SUPERVISOR'], 'HR_ADMIN'), true)
  assert.equal(isHrScheduleUploadMode(['HR_ADMIN', 'SUPERVISOR'], 'SUPERVISOR'), false)
  assert.equal(isHrScheduleUploadMode(['SYSTEM_ADMIN'], 'HR_ADMIN'), false)
  assert.equal(isHrScheduleUploadMode(['HR_ADMIN'], 'administrator'), false)
  assert.equal(isHrScheduleUploadMode(['HR_ADMIN'], 'hr_admin'), false)
})

test('template downloads use separate HR endpoint with explicit mode and preserve standard requests', async () => {
  let request
  const blob = new Blob(['supervisor_employee_code,employee_code'])
  const api = load({ get: async (...args) => { request = args; return { data: blob } } })
  assert.equal(await api.downloadScheduleUploadTemplate(), blob)
  assert.equal(request[0], '/schedule-uploads/template')
  assert.equal(request[1].responseType, 'blob')
  assert.equal(request[1].params, undefined)
  assert.equal(await api.downloadScheduleUploadTemplate(true), blob)
  assert.equal(request[0], '/schedule-uploads/hr-admin/template')
  assert.equal(request[1].params.dashboard_role_code, 'HR_ADMIN')
})

test('preview uploads file as multipart to the correct mode endpoint', async () => {
  let request
  const preview = { is_valid: true, rows: [{ supervisor_employee_code: 'S001' }] }
  const api = load({ post: async (...args) => { request = args; return { data: { data: preview } } } })
  const file = new File(['csv-data'], 'team.csv', { type: 'text/csv' })
  assert.equal(await api.previewScheduleUpload(file, true), preview)
  assert.equal(request[0], '/schedule-uploads/hr-admin/preview')
  assert.equal(request[1].get('file').name, 'team.csv')
  assert.equal(request[2].headers['Content-Type'], 'multipart/form-data')
  assert.equal(request[2].params.dashboard_role_code, 'HR_ADMIN')
  await api.previewScheduleUpload(file)
  assert.equal(request[0], '/schedule-uploads/preview')
  assert.equal(request[2].params, undefined)
})

test('HR submission returns every split batch while standard submission keeps its single-batch shape', async () => {
  let request
  const batches = [{ id: 'one', status: 'PENDING_APPROVAL' }, { id: 'two', status: 'APPROVED' }]
  const api = load({ post: async (...args) => {
    request = args
    return { data: { data: args[0].endsWith('/hr-admin') ? batches : batches[0] } }
  } })
  const file = new File(['csv-data'], 'team.csv')
  assert.equal(await api.submitHrScheduleUpload(file), batches)
  assert.equal(request[0], '/schedule-uploads/hr-admin')
  assert.equal(request[2].params.dashboard_role_code, 'HR_ADMIN')
  assert.equal(request[2].headers['Content-Type'], 'multipart/form-data')
  assert.equal(await api.submitScheduleUpload(file), batches[0])
  assert.equal(request[0], '/schedule-uploads')
  assert.equal(request[2].params, undefined)
})

test('HR errors are surfaced and do not silently fall back to ordinary team uploads', async () => {
  const requests = []
  const api = load({ post: async (...args) => {
    requests.push(args[0])
    throw new axios.AxiosError('Forbidden', 'ERR_BAD_REQUEST', {}, {}, {
      status: 403, data: { detail: 'HR_ADMIN role required.' },
    })
  } })
  const file = new File(['csv-data'], 'team.csv')
  await assert.rejects(api.submitHrScheduleUpload(file), /HR_ADMIN role required/)
  await assert.rejects(api.previewScheduleUpload(file, true), /HR_ADMIN role required/)
  assert.deepEqual(requests, ['/schedule-uploads/hr-admin', '/schedule-uploads/hr-admin/preview'])
})

test('HR submission uses readable fallback for non-string validation details', async () => {
  const api = load({ post: async () => {
    throw new axios.AxiosError('Invalid', 'ERR_BAD_REQUEST', {}, {}, { status: 422, data: { detail: [{ msg: 'Invalid mode' }] } })
  } })
  await assert.rejects(api.submitHrScheduleUpload(new File(['csv'], 'team.csv')), /Could not submit the HR schedule file/)
})
