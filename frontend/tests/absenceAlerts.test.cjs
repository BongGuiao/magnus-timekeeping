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
      if (name === 'lucide-react') return { AlertTriangle: 'alert-icon' }
      if (name === '../../lib/apiClient') return { apiClient: {
        async get() { return { data: { data: alerts } } },
        async post(path) { posts.push(path); alerts = [] },
      } }
      if (name === '../../lib/attendanceApi') return { getAttendanceErrorMessage: (error) => error.message }
      throw new Error(`Unexpected dependency: ${name}`)
    },
  })
  const render = (props) => { stateIndex = 0; refIndex = 0; return exports.default(props) }
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

test('compact alert opens its details from an aligned summary box', async () => {
  const panel = createPanel()
  const cleanup = panel.mount()
  await new Promise((resolve) => setImmediate(resolve))
  const box = panel.render({ compact: true })
  const button = panel.button(box)
  assert.equal(button.props['aria-expanded'], false)
  assert.equal(button.props['aria-controls'], 'team-absence-alerts')
  assert.match(panel.text(button), /Consecutive absence alerts/)
  button.props.onClick()
  const expanded = panel.render({ compact: true })
  assert.equal(panel.button(expanded).props['aria-expanded'], true)
  assert.match(panel.text(expanded), /Test Employee/)
  cleanup()
})

test('team overview places the alert box after the existing summary metrics', () => {
  const React = require('react')
  const { renderToStaticMarkup } = require('react-dom/server')
  const source = readFileSync(join(__dirname, '..', 'src', 'components', 'dashboard', 'TeamOverview.tsx'), 'utf8')
  const exports = {}
  runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, { exports, require, Intl, Date })
  const html = renderToStaticMarkup(React.createElement(exports.default, {
    role: 'supervisor',
    metrics: [
      { id: 'punched-today', label: 'Punched', open: false },
      { id: 'missing-in', label: 'Recorded absences', open: false },
      { id: 'missing-out', label: 'Missing clock-out', open: false },
      { id: 'hours', label: 'Hours this week', open: false },
    ],
    reviews: [{ id: 'leave', label: 'Leave review', open: false }],
    extraMetric: React.createElement('span', null, 'Consecutive absence alerts'),
  }))
  assert.ok(html.indexOf('Hours this week') < html.indexOf('Consecutive absence alerts'))
  assert.ok(html.indexOf('Consecutive absence alerts') < html.indexOf('Review queue'))
})
