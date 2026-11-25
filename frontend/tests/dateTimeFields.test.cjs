const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')

const source = readFileSync(join(__dirname, '..', 'src', 'components', 'common', 'DateTimeFields.tsx'), 'utf8')
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText
const exportsObject = {}
runInNewContext(code, { exports: exportsObject, require })
const DateTimeFields = exportsObject.default

function inputs(props) {
  const tree = DateTimeFields({ label: 'Start', className: '', onChange() {}, ...props })
  return React.Children.toArray(tree.props.children).map((label) =>
    React.Children.toArray(label.props.children).find((child) => child.type === 'input'))
}

test('separate fields preserve partial input and combine dates and times including seconds', () => {
  let value = ''
  let [date, time] = inputs({ value, step: 1, onChange: (next) => { value = next } })
  time.props.onChange({ target: { value: '23:30:45' } })
  assert.equal(value, 'T23:30:45')
  ;[date] = inputs({ value, step: 1, onChange: (next) => { value = next } })
  date.props.onChange({ target: { value: '2026-11-25' } })
  assert.equal(value, '2026-11-25T23:30:45')
  ;[, time] = inputs({ value, step: 1, onChange: (next) => { value = next } })
  time.props.onChange({ target: { value: '' } })
  assert.equal(value, '2026-11-25T')
})

test('time bounds apply only on their boundary dates, including overnight periods', () => {
  const min = '2026-11-25T22:15:30'
  const max = '2026-11-26T06:45:00'
  let [date, time] = inputs({ value: min, min, max, step: 1 })
  assert.equal(date.props.min, '2026-11-25')
  assert.equal(date.props.max, '2026-11-26')
  assert.equal(time.props.min, '22:15:30')
  assert.equal(time.props.max, undefined)
  ;[, time] = inputs({ value: '2026-11-26T01:00:00', min, max, step: 1 })
  assert.equal(time.props.min, undefined)
  assert.equal(time.props.max, '06:45:00')
})
