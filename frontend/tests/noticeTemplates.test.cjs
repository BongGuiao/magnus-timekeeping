const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

function compile(path, jsx = false) {
  return ts.transpileModule(readFileSync(join(__dirname, '..', path), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: jsx ? ts.JsxEmit.ReactJSX : undefined },
  }).outputText
}

const pageCode = compile('src/components/attendance/NoticeTemplates.tsx', true)
const apiCode = compile('src/lib/noticeTemplateApi.ts')
const template = {
  id: 'template-id', name: 'Test template', module: 'TARDINESS', is_active: false,
  created_by: 'hr', created_at: '2026-11-01T00:00:00Z',
  sanitized_html: '<p>Hello {{employee_name}}</p>{{signature}}',
}

function renderPanel({ selected = template, confirm = true, module = 'TARDINESS' } = {}) {
  const states = [true, [selected], selected, '', null, false, false, false, '', '', '', 0, module]
  const updates = []
  const activations = []
  let index = 0
  const exports = {}
  runInNewContext(pageCode, {
    exports,
    window: { confirm: () => confirm },
    require(name) {
      if (name === 'react') return {
        ...React,
        useState() {
          const current = index++
          return [states[current], (value) => updates.push([current, value])]
        },
        useEffect() {},
        useRef(value) { return { current: value } },
      }
      if (name === '../../lib/noticeTemplateApi') return {
        activateNoticeTemplate: async (id) => { activations.push(id); return { ...template, is_active: true } },
        getNoticeTemplate() {},
        listNoticeTemplates() {},
        uploadNoticeTemplate() {},
      }
      if (name === '../../lib/officialBusinessApi') return { formatManilaDateTime: () => 'Manila time' }
      return require(name)
    },
  })
  const tree = exports.default()
  return { tree, html: renderToStaticMarkup(tree), updates, activations }
}

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return null
  if (predicate(tree)) return tree
  for (const child of React.Children.toArray(tree.props?.children)) {
    const result = find(child, predicate)
    if (result) return result
  }
  return null
}

test('preview is sandboxed and explains required fields and sanitization', () => {
  const { tree, html } = renderPanel()
  const frame = find(tree, (node) => node.type === 'iframe')
  assert.equal(frame.props.sandbox, '')
  assert.match(frame.props.srcDoc, /default-src 'none'/)
  assert.ok(frame.props.srcDoc.includes(template.sanitized_html))
  assert.ok(html.includes('scripts, styles, links and images are removed'))
  assert.ok(html.includes('{{attendance_records}}'))
  assert.ok(html.includes('{{signature}}'))
  assert.ok(html.includes('Version template-id'))
})

test('activation requires confirmation and only sends the selected version', async () => {
  const cancelled = renderPanel({ confirm: false })
  find(cancelled.tree, (node) => node.type === 'button' && node.props.children === 'Activate version').props.onClick()
  assert.equal(cancelled.activations.length, 0)
  const accepted = renderPanel()
  find(accepted.tree, (node) => node.type === 'button' && node.props.children === 'Activate version').props.onClick()
  await new Promise((resolve) => setImmediate(resolve))
  assert.deepEqual(accepted.activations, [template.id])
  assert.ok(accepted.updates.some(([index, value]) => index === 10 && value.includes('No notice has been issued')))
})

test('return-to-work module shows its fields and activates independently', async () => {
  const selected = { ...template, module: 'RETURN_TO_WORK' }
  const panel = renderPanel({ selected, module: 'RETURN_TO_WORK' })
  assert.ok(panel.html.includes('Return to Work'))
  assert.ok(panel.html.includes('{{last_attendance_date}}'))
  assert.ok(panel.html.includes('{{consecutive_absence_days}}'))
  assert.ok(panel.html.includes('{{expected_return_date}}'))
  assert.ok(panel.html.includes('automatic absence detection are not implemented'))
  assert.ok(!panel.html.includes('{{late_dates}}'))
  find(panel.tree, (node) => node.type === 'button' && node.props.children === 'Activate version').props.onClick()
  await new Promise((resolve) => setImmediate(resolve))
  assert.ok(panel.updates.some(([index, value]) => index === 10 && value.includes('Return to Work')))
})

test('upload API uses multipart form and propagates errors', async () => {
  const requests = []
  const exports = {}
  class TestFormData {
    fields = []
    append(...field) { this.fields.push(field) }
  }
  runInNewContext(apiCode, {
    exports, FormData: TestFormData,
    require(name) {
      if (name === './apiClient') return { apiClient: { post: async (...args) => {
        requests.push(args)
        if (requests.length > 1) throw new Error('Forbidden')
        return { data: { data: template } }
      } } }
      if (name === './attendanceApi') return { getAttendanceErrorMessage: (error) => error.message }
      return require(name)
    },
  })
  const file = { name: 'notice.html' }
  assert.equal(await exports.uploadNoticeTemplate('Test', 'RETURN_TO_WORK', file), template)
  assert.equal(requests[0][0], '/attendance/notice-templates')
  assert.deepEqual(requests[0][1].fields, [['name', 'Test'], ['module', 'RETURN_TO_WORK'], ['file', file]])
  assert.equal(requests[0][2].headers['Content-Type'], 'multipart/form-data')
  await assert.rejects(exports.activateNoticeTemplate('a/b'), /Forbidden/)
  assert.equal(requests[1][0], '/attendance/notice-templates/a%2Fb/activate')
})
