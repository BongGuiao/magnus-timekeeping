const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const ts = require('typescript')

const source = readFileSync(join(__dirname, '..', 'src', 'features', 'employees', 'RegularizationDashboard.tsx'), 'utf8')
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText

const candidate = {
  assignment_id: 'assignment', employee_id: 'employee', employee_no: 'E1',
  employee_name: 'Example Employee', company_name: 'Company', org_unit_name: 'Unit',
  employment_type: 'PROBATIONARY', hire_date: '2026-01-01', six_month_date: '2026-07-01', days_remaining: -1,
}

function harness(initialReview) {
  const cells = []
  const effects = []
  let hook = 0
  let today = '2026-07-02'
  let timer
  let review = initialReview
  let loads = 0
  const dismissed = []
  const hooks = {
    useState(initial) {
      const index = hook++
      if (!(index in cells)) cells[index] = typeof initial === 'function' ? initial() : initial
      return [cells[index], (value) => { cells[index] = typeof value === 'function' ? value(cells[index]) : value }]
    },
    useRef(initial) {
      const index = hook++
      if (!(index in cells)) cells[index] = { current: initial }
      return cells[index]
    },
    useEffect(effect, dependencies) {
      const index = hook++
      const prior = cells[index]
      if (!prior || dependencies.some((value, i) => value !== prior.dependencies[i])) {
        prior?.cleanup?.()
        effects.push(() => { cells[index] = { dependencies, cleanup: effect() } })
      }
    },
  }
  const exports = {}
  runInNewContext(code, {
    exports, Error,
    window: {
      setInterval(callback) { timer = callback; return 1 },
      clearInterval() {},
      addEventListener() {},
      removeEventListener() {},
    },
    require(name) {
      if (name === 'react') return hooks
      if (name === '../../lib/employeeRelatedApi') return { EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT: 'employment-assignment-changed', getManilaDate: () => today }
      if (name === '../../lib/regularizationApi') return {
        async fetchRegularizationReview() { loads++; if (review instanceof Error) throw review; return review },
        async dismissRegularizationNotification(date) { dismissed.push(date); review = { ...review, notification_pending: false } },
      }
      return require(name)
    },
  })
  return {
    render() {
      hook = 0
      const tree = exports.default()
      while (effects.length) effects.shift()()
      return tree
    },
    setReview(value) { review = value },
    setToday(value) { today = value },
    tick() { timer() },
    loads: () => loads,
    dismissed,
  }
}

function find(node, predicate) {
  if (Array.isArray(node)) return node.map((item) => find(item, predicate)).find(Boolean)
  if (!React.isValidElement(node)) return null
  if (predicate(node)) return node
  return find(node.props.children, predicate)
}

function button(tree, text) {
  const result = find(tree, (node) => node.type === 'button'
    && React.Children.toArray(node.props.children).join('').includes(text))
  assert.ok(result, `Missing button: ${text}`)
  return result
}

const settle = () => new Promise((resolve) => setImmediate(resolve))

test('empty result stays invisible; refresh and day rollover load candidates', async () => {
  const view = harness({ as_of: '2026-07-02', candidates: [], notification_pending: false })
  assert.equal(view.render(), null)
  await settle()
  assert.equal(view.render(), null)
  view.tick()
  assert.equal(view.loads(), 1)
  view.setReview({ as_of: '2026-07-03', candidates: [candidate], notification_pending: true })
  view.setToday('2026-07-03')
  view.tick()
  await settle()
  assert.match(renderToStaticMarkup(view.render()), /Daily reminder/)
  assert.equal(view.loads(), 2)
})

test('daily reminder can be dismissed while candidate details remain available', async () => {
  const view = harness({ as_of: '2026-07-02', candidates: [candidate], notification_pending: true })
  view.render()
  await settle()
  let tree = view.render()
  assert.doesNotMatch(renderToStaticMarkup(tree), /Example Employee/)
  find(tree, (node) => node.type === 'button' && node.props['aria-controls'] === 'regularization-candidate-list').props.onClick()
  tree = view.render()
  assert.match(renderToStaticMarkup(tree), /Example Employee/)
  assert.match(renderToStaticMarkup(tree), /1 day overdue/)
  button(tree, 'Dismiss reminder').props.onClick()
  await settle()
  tree = view.render()
  assert.deepEqual(view.dismissed, ['2026-07-02'])
  assert.doesNotMatch(renderToStaticMarkup(tree), /Daily reminder/)
  assert.match(renderToStaticMarkup(tree), /Example Employee/)
})

test('loading failures are visible and do not look like an empty candidate list', async () => {
  const view = harness(new Error('Service unavailable'))
  view.render()
  await settle()
  assert.match(renderToStaticMarkup(view.render()), /Regularization monitoring unavailable/)
})
