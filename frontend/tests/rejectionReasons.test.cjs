const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const source = readFileSync(join(__dirname, '..', 'src', 'components', 'dashboard', 'SideCards.tsx'), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText
const exportsObject = {}
runInNewContext(compiled, {
  exports: exportsObject,
  require(name) {
    return name === '../../lib/leaveApi' ? { formatLeaveBalance: () => '' } : require(name)
  },
})

test('leave history displays a reviewer reason and tolerates historical records', () => {
  const html = renderToStaticMarkup(React.createElement(exportsObject.LeaveRequestsCard, {
    requests: [
      { id: '1', type: 'Vacation', startDate: '2026-12-01', endDate: '2026-12-01', status: 'REJECTED', rejectionReason: 'Missing <details>' },
      { id: '2', type: 'Sick', startDate: '2026-12-02', endDate: '2026-12-02', status: 'REJECTED' },
    ],
  }))
  assert.ok(html.includes('Rejection reason: Missing &lt;details&gt;'))
  assert.ok(html.includes('Sick'))
})
