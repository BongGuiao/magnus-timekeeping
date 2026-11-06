const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const ts = require('typescript')

function harness(page, fetchBatches) {
  const cells = []
  const pendingEffects = []
  let hook = 0
  const hooks = {
    useState(initial) {
      const index = hook++
      if (!(index in cells)) cells[index] = initial
      return [cells[index], (next) => {
        cells[index] = typeof next === 'function' ? next(cells[index]) : next
      }]
    },
    useRef(initial) {
      const index = hook++
      if (!(index in cells)) cells[index] = { current: initial }
      return cells[index]
    },
    useSyncExternalStore(_subscribe, getSnapshot) { return getSnapshot() },
    useEffect(effect, dependencies) {
      const index = hook++
      const previous = cells[index]
      if (!previous || dependencies.some((value, i) => value !== previous.dependencies[i])) {
        if (previous?.cleanup) previous.cleanup()
        pendingEffects.push(() => { cells[index] = { dependencies, cleanup: effect() } })
      }
    },
  }
  const source = readFileSync(join(__dirname, '..', 'src', 'pages', `${page}.tsx`), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const exports = {}
  const mocks = {
    react: hooks,
    '../hooks/useLogout': { useLogout: () => ({ logout() {} }) },
    '../types/role': { getAvailableRoleCodes: () => [], getSelectedDashboardRoleCode: () => null },
    '../lib/scheduleUploadApi': {
      fetchMyScheduleUploads: fetchBatches,
      fetchScheduleUploadsForReview: fetchBatches,
      isHrScheduleUploadMode: () => false,
      SCHEDULE_UPLOAD_STATUS_LABELS: {
        PENDING_APPROVAL: 'Pending', APPROVED: 'Approved', REJECTED: 'Rejected', CANCELLED: 'Cancelled',
      },
    },
    '../lib/scheduleUploadFormat': { formatDateTime: (value) => value, formatPeriod: () => '' },
    '../components/scheduleUpload/ScheduleUploadParts': {
      ScheduleUploadBatchDetails: () => null, ScheduleUploadStatusBadge: () => null,
    },
  }
  runInNewContext(code, {
    exports, Error, window: {},
    require(name) {
      if (name in mocks) return mocks[name]
      if (name.startsWith('.')) return { __esModule: true, default: () => null }
      return require(name)
    },
  })
  return {
    render() {
      hook = 0
      let tree = page === 'ScheduleUploads'
        ? exports.ScheduleUploadPanel({})
        : exports.default({ employeeName: 'Synthetic' })
      if (page === 'ScheduleUploads') tree = tree.type(tree.props)
      while (pendingEffects.length) pendingEffects.shift()()
      return tree
    },
  }
}

function find(node, predicate) {
  if (Array.isArray(node)) {
    for (const child of node) {
      const match = find(child, predicate)
      if (match) return match
    }
    return null
  }
  if (!React.isValidElement(node)) return null
  return predicate(node) ? node : find(node.props.children, predicate)
}

function button(tree, label) {
  const result = find(tree, (element) => element.type === 'button' && element.props.children === label)
  assert.ok(result, `Button not found: ${label}`)
  return result
}

const settle = () => new Promise((resolve) => setImmediate(resolve))

for (const [page, emptyMessage, retryLabel] of [
  ['ScheduleUploads', 'You have not uploaded any schedules yet.', 'Retry loading uploads'],
  ['ScheduleUploadApprovals', 'No batches with this status.', 'Retry loading batches'],
]) {
  test(`${page} reports load failures without presenting an empty list and allows retry`, async () => {
    let loads = 0
    const view = harness(page, async () => {
      loads += 1
      if (loads === 1) throw new Error('Schedules unavailable.')
      return []
    })
    view.render()
    await settle()
    let tree = view.render()
    let html = renderToStaticMarkup(tree)
    assert.match(html, /Schedules unavailable/)
    assert.ok(!html.includes(emptyMessage))
    button(tree, retryLabel).props.onClick()
    tree = view.render()
    assert.match(renderToStaticMarkup(tree), /Loading/)
    await settle()
    html = renderToStaticMarkup(view.render())
    assert.ok(html.includes(emptyMessage))
    assert.doesNotMatch(html, /Schedules unavailable/)
    assert.equal(loads, 2)
  })
}

test('a failed approval status change does not show batches from the previous status', async () => {
  const batch = {
    id: 'batch', batch_no: 'OLD-BATCH', supervisor_name: 'Synthetic', file_name: 'file.csv',
    row_count: 1, submitted_at: '2026-11-04', status: 'PENDING_APPROVAL',
  }
  const view = harness('ScheduleUploadApprovals', async (status) => {
    if (status === 'APPROVED') throw new Error('Approved batches unavailable.')
    return [batch]
  })
  view.render()
  await settle()
  let tree = view.render()
  assert.match(renderToStaticMarkup(tree), /OLD-BATCH/)
  button(tree, 'Approved').props.onClick()
  view.render()
  await settle()
  tree = view.render()
  const html = renderToStaticMarkup(tree)
  assert.match(html, /Approved batches unavailable/)
  assert.doesNotMatch(html, /OLD-BATCH|No batches with this status/)
})
