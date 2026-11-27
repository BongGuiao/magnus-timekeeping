const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')

function createPanel() {
  const states = [], refs = [], exports = {}
  let stateIndex = 0, refIndex = 0, effect
  let alerts = [{ id: 'one', employee_name: 'Test Employee', employee_no: 'E1', absence_dates: ['2026-11-25', '2026-11-26', '2026-11-27'], resolved_at: null }]
  const posts = []
  const source = readFileSync(join(__dirname, '..', 'src', 'components', 'dashboard', 'AbsenceAlerts.tsx'), 'utf8')
  runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, {
    exports,
    window: { setInterval: () => 1, clearInterval() {}, addEventListener() {}, removeEventListener() {} },
    require(name) {
      if (name === 'react') return {
        useState(initial) {
          const index = stateIndex++
          if (!(index in states)) states[index] = initial
          return [states[index], (value) => { states[index] = typeof value === 'function' ? value(states[index]) : value }]
        },
        useRef(initial) { return refs[refIndex++] ??= { current: initial } },
        useEffect(callback) { if (!effect) effect = callback },
      }
      if (name === 'react/jsx-runtime') return {
        jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }),
      }
      if (name === '../../lib/apiClient') return { apiClient: {
        async get() { return { data: { data: alerts } } },
        async post(path) { posts.push(path); alerts = [] },
      } }
      if (name === '../../lib/attendanceApi') return { getAttendanceErrorMessage: (error) => error.message }
      throw new Error(`Unexpected dependency: ${name}`)
    },
  })
  const render = () => { stateIndex = 0; refIndex = 0; return exports.default() }
  const text = (node) => typeof node === 'string' ? node : !node?.props ? '' : [node.props.children].flat(Infinity).map(text).join(' ')
  const button = (node) => {
    if (!node?.props) return undefined
    if (node.type === 'button') return node
    return [node.props.children].flat(Infinity).map(button).find(Boolean)
  }
  return { render, text, button, posts, mount() { render(); return effect() } }
}

test('displays and dismisses a recipient-specific absence alert', async () => {
  const panel = createPanel()
  const cleanup = panel.mount()
  await new Promise((resolve) => setImmediate(resolve))
  const view = panel.render()
  assert.match(panel.text(view), /Test Employee/)
  assert.match(panel.text(view), /2026-11-27/)
  panel.button(view).props.onClick()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(panel.posts[0], '/attendance/absence-alerts/one/dismiss')
  assert.equal(panel.render(), null)
  cleanup()
})
