const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const { AxiosError } = require('axios')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

function load(file, imports = {}, globals = {}) {
  const exports = {}
  const code = ts.transpileModule(readFileSync(join(__dirname, '..', 'src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  runInNewContext(code, { exports, require: (name) => imports[name] ?? require(name), ...globals })
  return exports
}

test('backup downloads an authenticated blob and releases the object URL', async () => {
  let request, filename, revoked, clicked = false, removed = false
  const link = { click() { clicked = true; filename = this.download }, remove() { removed = true } }
  const api = load(join('lib', 'databaseBackupApi.ts'), {
    './apiClient': { apiClient: { post: async (...args) => {
      request = args
      return { data: new Blob(['PGDMP']) }
    } } },
  }, {
    Blob, document: { createElement: () => link, body: { appendChild() {} } },
    URL: { createObjectURL: () => 'blob:backup', revokeObjectURL: (url) => { revoked = url } },
    setTimeout: (callback) => callback(),
  })
  await api.downloadDatabaseBackup()
  assert.equal(request[0], '/auth/database-backup')
  assert.equal(request[2].responseType, 'blob')
  assert.equal(request[2].timeout, 360000)
  assert.ok(filename.endsWith('.dump'))
  assert.ok(clicked && removed)
  assert.equal(revoked, 'blob:backup')
})

test('JSON error inside blob response is shown rather than saved as a backup', async () => {
  for (const body of ['{"detail":"Only system administrators can perform this action."}', '<html>Proxy failure</html>']) {
    const api = load(join('lib', 'databaseBackupApi.ts'), {
      './apiClient': { apiClient: { post: async () => {
        throw new AxiosError('Failed', undefined, undefined, undefined, { data: new Blob([body]) })
      } } },
    }, { Blob })
    await assert.rejects(api.downloadDatabaseBackup(), body.startsWith('{') ? /Only system administrators/ : /could not be downloaded/)
  }
})

test('backup screen explains scope, sensitive data and browser save location', () => {
  const Page = load(join('pages', 'DatabaseBackup.tsx'), {
    '../hooks/useLogout': { useLogout: () => ({ logout() {} }) },
    '../components/dashboard/TopNav': { __esModule: true, default: () => null },
    '../lib/databaseBackupApi': {},
  }).default
  const html = renderToStaticMarkup(React.createElement(Page, { employeeName: 'Admin' }))
  for (const text of ['Database Backup', 'Create &amp; download backup', 'not encrypted', 'Elasticsearch logs', 'five minutes']) {
    assert.ok(html.includes(text), text)
  }
})

test('backup navigation is gated for system administrators in both menus and App', () => {
  const topNav = readFileSync(join(__dirname, '..', 'src', 'components', 'dashboard', 'TopNav.tsx'), 'utf8')
  assert.equal((topNav.match(/canResetPasswords && \([\s\S]*?navigateTo\('database-backup'\)/g) ?? []).length, 2)
  const app = readFileSync(join(__dirname, '..', 'src', 'App.tsx'), 'utf8')
  assert.match(app, /view === 'database-backup'[\s\S]*?return isSystemAdmin\(\)/)
})
