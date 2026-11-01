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
    if (name === '../../lib/leaveApi') return { formatLeaveBalance: () => '' }
    return require(name)
  },
})

test('attendance correction action appears after Apply for Leave and invokes its own handler', () => {
  let clicked = false
  const tree = exportsObject.LeaveRequestsCard({
    requests: [], onApply() {}, onCorrection() { clicked = true },
  })
  const html = renderToStaticMarkup(tree)
  assert.ok(html.indexOf('+ Apply for Attendance Correction') > html.indexOf('+ Apply for Leave'))
  assert.ok(html.includes('aria-expanded="false"'))
  assert.ok(html.includes('from-indigo-600 to-violet-600'))
  assert.ok(html.includes('bg-teal-50 text-teal-800'))
  assert.equal((html.match(/sm:w-auto/g) ?? []).length, 2)
  const button = React.Children.toArray(tree.props.children).find((child) =>
    child.props?.children === '+ Apply for Attendance Correction')
  button.props.onClick()
  assert.equal(clicked, true)
})

test('correction action is permission-gated and reflects open state', () => {
  const hidden = renderToStaticMarkup(React.createElement(exportsObject.LeaveRequestsCard, { requests: [], onApply() {} }))
  assert.ok(!hidden.includes('Attendance Correction'))
  const open = renderToStaticMarkup(React.createElement(exportsObject.LeaveRequestsCard, {
    requests: [], onCorrection() {}, correctionOpen: true,
  }))
  assert.ok(open.includes('Hide Attendance Correction'))
  assert.ok(open.includes('aria-expanded="true"'))
  assert.ok(open.includes('bg-teal-600 text-white'))
})
