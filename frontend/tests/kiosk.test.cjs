const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const { webcrypto, createHash } = require('node:crypto')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

function compile(file) {
  return ts.transpileModule(readFileSync(join(__dirname, '..', 'src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
}

function renderAttendance(kiosk) {
  const exports = {}
  const transport = { identify() {}, clock() {}, break() {} }
  runInNewContext(compile('pages/Attendance.tsx'), {
    exports,
    require(name) {
      if (name === 'react') return { ...React, useEffectEvent: (callback) => callback }
      if (name === '../hooks/useAttendanceClock') return {
        useAttendanceClock: (received) => {
          assert.equal(received, kiosk ? transport : undefined)
          return {
            employeeCode: 'TEST', verifiedUser: { id: 'user', employee_name: 'Synthetic Employee', employee_code: 'TEST' },
            lastAttendance: null,
          }
        },
      }
      if (name === '../hooks/useWebcamCapture') return { useWebcamCapture: () => ({ isCameraApiAvailable: true }) }
      if (name === '../hooks/useLogout') return { useLogout: () => ({ logout() {} }) }
      if (name === '../components/dashboard/TopNav') return { __esModule: true, default: () => React.createElement('nav', null, 'ADMIN NAVIGATION') }
      if (name === '../components/common/Stepper') return { __esModule: true, default: () => null }
      if (name === '../lib/apiClient' || name === '../lib/attendanceApi') return {}
      return require(name)
    },
  })
  return renderToStaticMarkup(React.createElement(exports.default, {
    employeeName: '', kioskTransport: kiosk ? transport : undefined,
  }))
}

test('kiosk reuses Attendance with explicit actions and without admin navigation or employee-device enrollment', () => {
  const kiosk = renderAttendance(true)
  assert.ok(kiosk.includes('Time In'))
  assert.ok(kiosk.includes('Time Out'))
  assert.ok(!kiosk.includes('ADMIN NAVIGATION'))
  assert.ok(!kiosk.includes('Register this browser'))
  assert.ok(!kiosk.includes('marked invalid'))
  const normal = renderAttendance(false)
  assert.ok(normal.includes('ADMIN NAVIGATION'))
  assert.ok(normal.includes('Register this browser'))
  assert.ok(normal.includes('Clock In'))
})

test('unregistered kiosk screen shows registration, never attendance controls', () => {
  const exports = {}
  runInNewContext(compile('pages/Kiosk.tsx'), {
    exports,
    require(name) {
      if (name === './Attendance') return { __esModule: true, default: () => React.createElement('div', null, 'ATTENDANCE CONTROLS') }
      if (name === '../lib/kioskApi') return {}
      return require(name)
    },
  })

  const html = renderToStaticMarkup(React.createElement(exports.default))
  assert.ok(html.includes('Device not registered'))
  assert.ok(!html.includes('ATTENDANCE CONTROLS'))
})

test('kiosk management uses a read-only employment company and appears last in Settings with an icon', () => {
    const exports = {}
    let stateIndex = 0
    runInNewContext(compile('pages/KioskDevices.tsx'), {
      exports,
      require(name) {
        if (name === 'react') return {
          ...React, useEffect() {},
          useState(initial) {
            const value = stateIndex++ === 0 ? { id: 'employment-company', legal_name: 'Employee Company' } : initial
            return [value, () => {}]
          },
        }
        if (name === '../hooks/useLogout') return { useLogout: () => ({ logout() {} }) }
        if (name === '../components/dashboard/TopNav') return { __esModule: true, default: () => null }
        if (name.startsWith('../lib/')) return {}
        return require(name)
      },
    })
    const html = renderToStaticMarkup(React.createElement(exports.default, { employeeName: 'Test Admin' }))
    assert.match(html, /readonly=""/i)
    assert.ok(html.includes('Employee Company'))
    assert.ok(!html.includes('Select company'))
    const nav = readFileSync(join(__dirname, '..', 'src', 'components', 'dashboard', 'TopNav.tsx'), 'utf8')
    const settings = nav.slice(nav.indexOf("label: 'Settings'"), nav.indexOf("label: 'Payroll',"))
    assert.ok(settings.indexOf("view: 'kiosk-devices'") > settings.indexOf("label: 'Company Parameters'"))
    assert.match(nav, /'kiosk-devices': Monitor/)
})

test('kiosk API uses an isolated client and signs employee, action and image fingerprint', async () => {
  const pair = await webcrypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign', 'verify'])
  const requests = []
  let challengeRequest
  const client = {
    async post(path, body) {
      requests.push(path)
      if (path === '/challenge') {
        challengeRequest = body
        return { data: { data: { challenge_id: 'challenge', message: 'signed kiosk challenge' } } }
      }
      assert.equal(path, '/clock')
      assert.equal(body.get('action'), 'clock_out')
      assert.equal(body.get('user_id'), 'synthetic-user')
      const signature = Buffer.from(body.get('signature'), 'base64url')
      assert.ok(await webcrypto.subtle.verify(
        { name: 'ECDSA', hash: 'SHA-256' }, pair.publicKey, signature, new TextEncoder().encode('signed kiosk challenge'),
      ))
      return { data: { data: { action: 'clock_out' } } }
    },
  }
  const exports = {}
  runInNewContext(compile('lib/kioskApi.ts'), {
    exports, crypto: webcrypto, TextEncoder, FormData, btoa,
    require(name) {
      if (name === 'axios') return { __esModule: true, default: { create: (config) => {
        assert.equal(config.baseURL, '/attendance/kiosk')
        return client
      } } }
      if (name === './attendanceDevice') return {
        getOrCreateDeviceKey: async (scope) => {
          assert.equal(scope, 'shared-kiosk-v1')
          return { identity: { deviceUuid: 'station' }, key: { privateKey: pair.privateKey } }
        },
      }
      if (name === './attendanceApi') return { getAttendanceErrorMessage: (error) => error.message }
      if (name === './apiClient') return { apiClient: { post() { assert.fail('Must not inherit admin authentication') } } }
      return require(name)
    },
  })
  const file = new File(['synthetic-image'], 'face.jpg', { type: 'image/jpeg' })
  const result = await exports.kioskAttendanceTransport.clock(file, 'synthetic-user', true)
  assert.equal(result.action, 'clock_out')
  const imageHash = createHash('sha256').update('synthetic-image').digest('hex')
  assert.equal(challengeRequest.payload_hash, createHash('sha256').update(`synthetic-user\nclock_out\n${imageHash}`).digest('hex'))
  assert.deepEqual(requests, ['/challenge', '/clock'])
})
