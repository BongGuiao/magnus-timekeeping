const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const React = require('react')
const ts = require('typescript')
const { AxiosError } = require('axios')

const settle = () => new Promise(setImmediate)
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const employee = (id = 'employee-a') => ({
  id, employee_no: id === 'employee-a' ? 'SYN-A' : 'SYN-B', first_name: 'Synthetic', last_name: id,
  is_active: true, record_status: 'ACTIVE', photo_reference: null,
})
const sample = (id = 'sample-a') => ({
  id, status: 'enrolled', created_at: '2026-11-13T00:00:00Z', enrolled_at: null,
  photo_reference: `/enrollment/photos/${id}.jpg`, is_profile_photo: true,
})
const review = (id = 'employee-a', samples = [sample()]) => ({
  employee_id: id, employee_no: employee(id).employee_no, enrolled_count: samples.length, samples,
})

function compile(path, mocks, globals = {}) {
  const exports = {}
  const code = ts.transpileModule(readFileSync(join(__dirname, '..', 'src', ...path.split('/')), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  runInNewContext(code, {
    exports, Error, ...globals,
    require(name) { return name in mocks ? mocks[name] : require(name) },
  })
  return exports
}

function harness(path, mocks, props, exportName = 'default') {
  const slots = []
  let cursor = 0
  let effects = []
  let currentProps = props
  let confirm = true
  const revoked = []
  let urlIndex = 0
  const hooks = {
    ...React,
    useState(initial) {
      const index = cursor++
      if (!slots[index]) {
        slots[index] = {
          value: typeof initial === 'function' ? initial() : initial,
          set(value) { slots[index].value = typeof value === 'function' ? value(slots[index].value) : value },
        }
      }
      return [slots[index].value, slots[index].set]
    },
    useRef(initial) {
      const index = cursor++
      if (!slots[index]) slots[index] = { current: initial }
      return slots[index]
    },
    useEffect(callback, deps) {
      const index = cursor++
      const before = slots[index]
      if (!before || deps.some((value, i) => !Object.is(value, before.deps[i]))) {
        effects.push(() => {
          before?.cleanup?.()
          slots[index] = { deps, cleanup: callback() }
        })
      }
    },
  }
  const exports = compile(path, { ...mocks, react: hooks }, {
    window: { confirm: () => confirm },
    URL: { createObjectURL: () => `blob:${++urlIndex}`, revokeObjectURL: (url) => revoked.push(url) },
  })
  return {
    revoked,
    confirm(value) { confirm = value },
    render(nextProps = currentProps) {
      currentProps = nextProps
      cursor = 0
      effects = []
      const result = exports[exportName](currentProps)
      effects.forEach((effect) => effect())
      return result
    },
    unmount() { slots.forEach((slot) => slot?.cleanup?.()) },
  }
}

function findAll(node, predicate) {
  if (Array.isArray(node)) return node.flatMap((child) => findAll(child, predicate))
  if (!React.isValidElement(node)) return []
  return [...(predicate(node) ? [node] : []), ...findAll(node.props.children, predicate)]
}
function text(node) {
  if (Array.isArray(node)) return node.map(text).join('')
  if (React.isValidElement(node)) return text(node.props.children)
  return typeof node === 'string' || typeof node === 'number' ? String(node) : ''
}
const button = (app, label) => findAll(app.render(), (node) => node.type === 'button' && text(node).trim() === label)[0]
const input = (app, label) => findAll(app.render(), (node) => node.props['aria-label'] === label)[0]

test('employee changes clear the capture and ignore delayed verification or enrollment results', async () => {
  const firstLookup = deferred()
  const saving = deferred()
  const enrollments = []
  const app = harness('hooks/useFaceEnrollment.ts', {
    '../lib/authApi': {
      searchUserByEmployeeCode: (code) => code === 'SYN-A' ? firstLookup.promise : Promise.resolve({
        id: 'user-b', employee_id: 'employee-b', is_active: true,
      }),
    },
    '../lib/enrollmentApi': {
      enrollFace: (file, id) => { enrollments.push({ file, id }); return saving.promise },
    },
  }, undefined, 'useFaceEnrollment')
  app.render().changeEmployeeCode('SYN-A')
  const first = app.render().verifyEmployeeCode()
  app.render().changeEmployeeCode('SYN-B')
  await app.render().verifyEmployeeCode()
  firstLookup.resolve({ id: 'user-a', employee_id: 'employee-a', is_active: true })
  await first
  assert.equal(app.render().verifiedUser.id, 'user-b')
  app.render().selectFile({ name: 'fresh-b.jpg' })
  const submitted = app.render().submit()
  assert.equal(enrollments[0].id, 'employee-b')
  app.render().changeEmployeeCode('SYN-C')
  assert.equal(app.render().file, null)
  assert.equal(app.render().previewUrl, null)
  saving.resolve({ sample_count: 1, photo_reference: '/enrollment/photos/b.jpg' })
  await submitted
  assert.equal(app.render().result, null)
  assert.equal(app.render().verifiedUser, null)
  assert.deepEqual(app.revoked, ['blob:1'])
  app.unmount()
})

test('employee panel does not apply an old save to a newly opened employee or after unmount', async () => {
  for (const changeEmployee of [false, true]) {
    const saving = deferred()
    const savedPhotos = []
    let active = false
    const stop = () => { active = false }
    const props = { employee: employee(), isActive: true, onPhotoReferenceSaved: (reference) => savedPhotos.push(reference) }
    const app = harness('features/employees/EmployeeFaceEnrollmentPanel.tsx', {
      '../../lib/enrollmentApi': { enrollFace: () => saving.promise },
      '../../types/role': { getAvailableRoleCodes: () => [], hasPermission: () => false },
      './EmployeeFaceSamples': { __esModule: true, default: () => null },
      '../../hooks/useBlinkWebcamCapture': { useBlinkWebcamCapture: () => ({
        isActive: active, stop, start: async () => { active = true }, capture: async () => ({ name: 'capture.jpg' }),
        videoRef: { current: null }, isCheckingBlink: false, error: null, blinkStatus: '',
      }) },
    }, props)
    app.render()
    button(app, 'Use webcam').props.onClick()
    button(app, 'Blink and capture').props.onClick()
    await settle()
    button(app, 'Save Face Captured').props.onClick()
    if (changeEmployee) {
      app.render({ ...props, employee: employee('employee-b') })
      assert.equal(button(app, 'Save Face Captured').props.disabled, true)
    } else app.unmount()
    saving.resolve({ sample_count: 1, photo_reference: '/enrollment/photos/old.jpg' })
    await settle()
    assert.deepEqual(savedPhotos, [])
    if (changeEmployee) app.unmount()
  }
})

test('review/reset controls are shown only for HR administrators with employee-management permission', () => {
  const Samples = () => null
  for (const [roles, permission, visible] of [
    [['HR_ADMIN'], true, true], [['SYSTEM_ADMIN'], true, false], [['HR_ADMIN'], false, false],
  ]) {
    const stop = () => {}
    const app = harness('features/employees/EmployeeFaceEnrollmentPanel.tsx', {
      '../../lib/enrollmentApi': {},
      '../../types/role': { getAvailableRoleCodes: () => roles, hasPermission: () => permission },
      './EmployeeFaceSamples': { __esModule: true, default: Samples },
      '../../hooks/useBlinkWebcamCapture': { useBlinkWebcamCapture: () => ({ stop, videoRef: { current: null } }) },
    }, { employee: employee(), isActive: true })
    assert.equal(findAll(app.render(), (node) => node.type === Samples).length, Number(visible))
    app.unmount()
  }
})

test('sample review requires typed identity, a reason, confirmation and the exact reviewed IDs before reset', async () => {
  let current = review('employee-a', [sample('first'), sample('second'), sample('third')])
  const requests = []
  const changes = []
  const props = {
    employee: employee(), isActive: true, disabled: false, refreshVersion: 0,
    onReset: (reference) => changes.push(reference), onResettingChange() {},
  }
  const app = harness('features/employees/EmployeeFaceSamples.tsx', {
    '../../lib/apiClient': { apiClient: {} },
    '../../lib/enrollmentApi': {
      fetchFaceEnrollment: async () => current,
      resetFaceEnrollment: async (id, payload) => {
        requests.push({ id, payload })
        current = review('employee-a', [])
        return { removed_count: 3, photo_reference: null, cleanup_warning: 'Photo cleanup failed; contact an administrator.' }
      },
    },
  }, props)
  app.render()
  await settle()
  assert.match(text(app.render()), /3 enrolled sample\(s\); 3 saved record\(s\)/)
  button(app, 'Remove all face samples').props.onClick()
  assert.equal(button(app, 'Confirm removal of all face samples').props.disabled, true)
  input(app, 'Confirm face reset employee number').props.onChange({ target: { value: 'SYN-A' } })
  input(app, 'Face reset reason').props.onChange({ target: { value: 'Confirmed incorrect enrollment' } })
  assert.equal(button(app, 'Confirm removal of all face samples').props.disabled, false)
  app.confirm(false)
  button(app, 'Confirm removal of all face samples').props.onClick()
  await settle()
  assert.equal(requests.length, 0)
  app.confirm(true)
  button(app, 'Confirm removal of all face samples').props.onClick()
  await settle()
  assert.equal(requests.length, 1)
  assert.equal(requests[0].id, 'employee-a')
  assert.deepEqual(Array.from(requests[0].payload.sample_ids), ['first', 'second', 'third'])
  assert.equal(requests[0].payload.employee_no, 'SYN-A')
  assert.equal(requests[0].payload.reason, 'Confirmed incorrect enrollment')
  assert.deepEqual(changes, [null])
  app.render()
  await settle()
  assert.match(text(app.render()), /No face samples are enrolled for SYN-A/)
  assert.match(text(app.render()), /No face samples remain/)
  assert.match(text(findAll(app.render(), (node) => node.props.role === 'alert')), /cleanup failed/)
  app.unmount()
})

test('a stale reset response or sample load cannot update a different employee', async () => {
  const resetting = deferred()
  const changes = []
  const props = {
    employee: employee(), isActive: true, disabled: false, refreshVersion: 0,
    onReset: (value) => changes.push(value), onResettingChange() {},
  }
  const app = harness('features/employees/EmployeeFaceSamples.tsx', {
    '../../lib/apiClient': { apiClient: {} },
    '../../lib/enrollmentApi': {
      fetchFaceEnrollment: async (id) => review(id),
      resetFaceEnrollment: () => resetting.promise,
    },
  }, props)
  app.render()
  await settle()
  button(app, 'Remove all face samples').props.onClick()
  input(app, 'Confirm face reset employee number').props.onChange({ target: { value: 'SYN-A' } })
  input(app, 'Face reset reason').props.onChange({ target: { value: 'Correction' } })
  button(app, 'Confirm removal of all face samples').props.onClick()
  app.render({ ...props, employee: employee('employee-b') })
  resetting.resolve({ removed_count: 1, photo_reference: null, cleanup_warning: null })
  await settle()
  assert.deepEqual(changes, [])
  assert.match(text(app.render()), /SYN-B/)
  assert.equal(button(app, 'Remove all face samples').props.disabled, false)
  assert.doesNotMatch(text(app.render()), /1 face samples reset/)
  app.unmount()
})

test('a rejected reset is displayed and reloads the current sample list without changing the profile', async () => {
  let current = review()
  const changes = []
  const app = harness('features/employees/EmployeeFaceSamples.tsx', {
    '../../lib/apiClient': { apiClient: {} },
    '../../lib/enrollmentApi': {
      fetchFaceEnrollment: async () => current,
      resetFaceEnrollment: async () => {
        current = review('employee-a', [sample(), sample('new')])
        throw new Error('Face samples changed since they were reviewed.')
      },
    },
  }, {
    employee: employee(), isActive: true, disabled: false, refreshVersion: 0,
    onReset: (value) => changes.push(value), onResettingChange() {},
  })
  app.render()
  await settle()
  button(app, 'Remove all face samples').props.onClick()
  input(app, 'Confirm face reset employee number').props.onChange({ target: { value: 'SYN-A' } })
  input(app, 'Face reset reason').props.onChange({ target: { value: 'Correction' } })
  button(app, 'Confirm removal of all face samples').props.onClick()
  await settle()
  app.render()
  await settle()
  assert.match(text(app.render()), /2 enrolled sample/)
  assert.match(text(findAll(app.render(), (node) => node.props.role === 'alert')), /samples changed/)
  assert.deepEqual(changes, [])
  app.unmount()
})

test('enrollment transport sends reset preconditions and surfaces structured validation failures', async () => {
  const requests = []
  let failure
  const api = compile('lib/enrollmentApi.ts', {
    './apiClient': { apiClient: {
      get: async (url) => { requests.push(url); return { data: { data: review() } } },
      post: async (url, payload) => {
        requests.push({ url, payload })
        if (failure) throw failure
        return { data: { data: { removed_count: 1, photo_reference: null, cleanup_warning: null } } }
      },
    } },
  })
  assert.equal((await api.fetchFaceEnrollment('employee-a')).samples.length, 1)
  const payload = { employee_no: 'SYN-A', sample_ids: ['sample-a'], reason: 'Correction' }
  await api.resetFaceEnrollment('employee-a', payload)
  assert.equal(requests[1].url, '/enrollment/employees/employee-a/reset')
  assert.equal(requests[1].payload, payload)
  failure = new AxiosError('validation', undefined, undefined, undefined, { data: { detail: [{ msg: 'A reason is required.' }] } })
  await assert.rejects(api.resetFaceEnrollment('employee-a', payload), /A reason is required/)
})
