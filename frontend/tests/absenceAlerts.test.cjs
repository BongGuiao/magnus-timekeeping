const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')

function createPanel({ failFirst = false } = {}) {
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
        async get() {
          if (failFirst) { failFirst = false; throw new Error('Load failed') }
          return { data: { data: alerts } }
        },
        async post(path) { posts.push(path); alerts = [] },
      } }
      if (name === '../../lib/attendanceApi') return { getAttendanceErrorMessage: (error) => error.message }
      throw new Error(`Unexpected dependency: ${name}`)
    },
  })
  const render = (props = {}) => {
    stateIndex = 0
    refIndex = 0
    const state = exports.useAbsenceAlerts()
    return exports.default({ state, onClose() {}, ...props })
  }
  const text = (node) => typeof node === 'string' ? node : !node?.props ? '' : [node.props.children].flat(Infinity).map(text).join(' ')
  return { render, text, posts, mount() { render(); return effect() } }
}

test('review panel displays alerts and remains visible when all are dismissed', async () => {
  const panel = createPanel()
  const cleanup = panel.mount()
  await new Promise((resolve) => setImmediate(resolve))
  const view = panel.render({ onClose() {} })
  assert.equal(view.props.id, 'absence-alerts-panel')
  assert.match(panel.text(view), /Test Employee/)
  assert.match(panel.text(view), /2026-11-27/)
  const buttons = (node) => !node?.props ? [] : [
    ...(node.type === 'button' ? [node] : []),
    ...[node.props.children].flat(Infinity).flatMap(buttons),
  ]
  buttons(view).find((button) => panel.text(button) === 'Dismiss').props.onClick()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(panel.posts[0], '/attendance/absence-alerts/one/dismiss')
  assert.match(panel.text(panel.render({ onClose() {} })), /No consecutive absence alerts/)
  cleanup()
})

test('review panel shows loading and allows retry after an error', async () => {
  const panel = createPanel({ failFirst: true })
  const cleanup = panel.mount()
  assert.match(panel.text(panel.render({ onClose() {} })), /Loading absence alerts/)
  await new Promise((resolve) => setImmediate(resolve))
  const view = panel.render({ onClose() {} })
  assert.match(panel.text(view), /Load failed/)
  const retry = (node) => {
    if (!node?.props) return undefined
    if (node.type === 'button' && panel.text(node) === 'Retry') return node
    return [node.props.children].flat(Infinity).map(retry).find(Boolean)
  }
  retry(view).props.onClick()
  await new Promise((resolve) => setImmediate(resolve))
  assert.match(panel.text(panel.render({ onClose() {} })), /Test Employee/)
  cleanup()
})
