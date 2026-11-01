const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const axios = require('axios')

function load(relativePath, imports = require) {
  const source = readFileSync(join(__dirname, '..', 'src', ...relativePath.split('/')), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  runInNewContext(code, { exports, require: imports })
  return exports
}

test('password change rules mirror the server and report the first problem', () => {
  const { validatePasswordChange, MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH } = load('lib/passwordPolicy.ts')
  const valid = { current: 'old-password', next: 'brand-new-password', confirm: 'brand-new-password' }
  assert.equal(validatePasswordChange(valid), null)

  assert.match(validatePasswordChange({ ...valid, current: '' }), /current password/)
  assert.match(validatePasswordChange({ ...valid, next: 'short', confirm: 'short' }), /at least 8/)
  assert.match(validatePasswordChange({ ...valid, next: 'x'.repeat(MAX_PASSWORD_LENGTH + 1), confirm: 'x'.repeat(MAX_PASSWORD_LENGTH + 1) }), /at most 128/)
  assert.match(validatePasswordChange({ ...valid, next: 'old-password', confirm: 'old-password' }), /different from the current/)
  assert.match(validatePasswordChange({ ...valid, confirm: 'brand-new-passwore' }), /do not match/)

  const atMinimum = 'x'.repeat(MIN_PASSWORD_LENGTH)
  const atMaximum = 'y'.repeat(MAX_PASSWORD_LENGTH)
  assert.equal(validatePasswordChange({ current: 'old', next: atMinimum, confirm: atMinimum }), null)
  assert.equal(validatePasswordChange({ current: 'old', next: atMaximum, confirm: atMaximum }), null)
})

function loadAuthApi(post) {
  return load('lib/authApi.ts', (name) => (name === './apiClient' ? { apiClient: { post } } : require(name)))
}

function axiosFailure(status, data) {
  return new axios.AxiosError('failed', 'ERR_BAD_REQUEST', {}, {}, { status, data })
}

test('changePassword posts both passwords and returns the confirmation', async () => {
  let request
  const api = loadAuthApi(async (...args) => {
    request = args
    return { data: { data: { message: 'Your password has been changed.', password_changed_at: '2026-10-13T04:00:00Z' } } }
  })
  const result = await api.changePassword({ current_password: 'old-password', new_password: 'brand-new-password' })
  assert.deepEqual(request, ['/auth/change-password', { current_password: 'old-password', new_password: 'brand-new-password' }])
  assert.equal(result.message, 'Your password has been changed.')
})

test('changePassword surfaces the server message for rule failures and validation lists', async () => {
  const cases = [
    [{ detail: 'The current password is incorrect.' }, 'The current password is incorrect.'],
    [{ detail: [{ msg: 'String should have at least 8 characters' }, { msg: 'Another problem' }] }, 'String should have at least 8 characters Another problem'],
    [{ detail: 'Too many failed attempts. Please try again later.' }, 'Too many failed attempts. Please try again later.'],
    [{}, 'Your password could not be changed. Please try again.'],
    [undefined, 'Your password could not be changed. Please try again.'],
  ]
  for (const [data, expected] of cases) {
    const api = loadAuthApi(async () => { throw axiosFailure(400, data) })
    await assert.rejects(
      api.changePassword({ current_password: 'a', new_password: 'b' }),
      (error) => error.message === expected,
    )
  }
})

test('changePassword does not disguise unexpected errors', async () => {
  const api = loadAuthApi(async () => { throw new TypeError('boom') })
  await assert.rejects(api.changePassword({ current_password: 'a', new_password: 'b' }), TypeError)
})

test('resetPasswordToDefault posts the employee code and surfaces server errors', async () => {
  let request
  const api = loadAuthApi(async (...args) => {
    request = args
    return { data: { data: { message: 'Password for EMP-1 was reset to the default password.', employee_code: 'EMP-1', password_reset_at: '2026-10-31T07:00:00Z' } } }
  })
  const result = await api.resetPasswordToDefault('EMP-1')
  assert.deepEqual(JSON.parse(JSON.stringify(request)), ['/auth/password-reset', { employee_code: 'EMP-1' }])
  assert.equal(result.employee_code, 'EMP-1')

  const denied = loadAuthApi(async () => { throw axiosFailure(403, { detail: 'Only system administrators can reset passwords.' }) })
  await assert.rejects(denied.resetPasswordToDefault('EMP-1'), (error) => error.message === 'Only system administrators can reset passwords.')
})

test('lookupPasswordResetTarget queries by employee code and reports unknown codes', async () => {
  let request
  const get = async (...args) => {
    request = args
    return { data: { data: { employee_code: 'EMP-1', employee_name: 'Ana Cruz', account_status: 'ACTIVE', is_active: true } } }
  }
  const api = load('lib/authApi.ts', (name) => (name === './apiClient' ? { apiClient: { get } } : require(name)))
  const target = await api.lookupPasswordResetTarget('EMP-1')
  assert.deepEqual(JSON.parse(JSON.stringify(request)), ['/auth/password-reset/lookup', { params: { employee_code: 'EMP-1' } }])
  assert.equal(target.employee_name, 'Ana Cruz')

  const missing = load('lib/authApi.ts', (name) => (
    name === './apiClient'
      ? { apiClient: { get: async () => { throw axiosFailure(404, { detail: 'No user found for the given employee code' }) } } }
      : require(name)
  ))
  await assert.rejects(missing.lookupPasswordResetTarget('NOPE'), (error) => error.message === 'No user found for the given employee code')
})
