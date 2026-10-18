const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const assert = require('node:assert/strict')
const test = require('node:test')
const ts = require('typescript')

function load(relativePath, globals) {
  const source = readFileSync(join(__dirname, '..', 'src', relativePath), 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  runInNewContext(compiled, { exports, ...globals })
  return exports
}

function face(score, count = 1) {
  return {
    faceLandmarks: Array.from({ length: count }, () => []),
    faceBlendshapes: count ? [{
      categories: [
        { categoryName: 'eyeBlinkLeft', score },
        { categoryName: 'eyeBlinkRight', score },
      ],
    }] : [],
  }
}

async function detector({ failLoad = false } = {}) {
  let frame
  let timeout
  let result
  const detector = { detectForVideo: () => result }
  const { waitForEyeBlink } = load('lib\\faceBlinkDetection.ts', {
    require: () => ({
      FilesetResolver: { forVisionTasks: async () => {
        if (failLoad) throw new Error('offline')
        return {}
      } },
      FaceLandmarker: { createFromOptions: async () => detector },
    }),
    DOMException,
    HTMLMediaElement: { HAVE_CURRENT_DATA: 2 },
    window: {
      setTimeout: (callback) => { timeout = callback; return 1 },
      clearTimeout: () => { timeout = undefined },
      requestAnimationFrame: (callback) => { frame = callback; return 1 },
      cancelAnimationFrame: () => { frame = undefined },
    },
  })
  const controller = new AbortController()
  let settled = false
  const pending = waitForEyeBlink({ readyState: 2 }, () => {}, controller.signal)
    .then(() => { settled = true })
  // Allow model-loading promises to settle before driving video frames.
  for (let i = 0; i < 10; i++) await Promise.resolve()
  let timestamp = 100
  return {
    pending,
    controller,
    settled: () => settled,
    hasFrame: () => Boolean(frame),
    tick: (next) => { result = next; frame(timestamp); timestamp += 100 },
    timeout: () => timeout(),
  }
}

test('requires open, closed, then open eyes before accepting', async () => {
  const d = await detector()
  d.tick(face(0.1))
  d.tick(face(0.9))
  assert.equal(d.settled(), false)
  d.tick(face(0.1))
  await d.pending
  assert.equal(d.settled(), true)
  assert.equal(d.hasFrame(), false)
})

test('closed eyes alone or open eyes alone do not pass', async () => {
  const d = await detector()
  const rejected = assert.rejects(d.pending, /blink was not detected/)
  d.tick(face(0.9))
  d.tick(face(0.1))
  d.tick(face(0.1))
  assert.equal(d.settled(), false)
  d.timeout()
  await rejected
})

test('losing the face resets an incomplete blink', async () => {
  const d = await detector()
  d.tick(face(0.1))
  d.tick(face(0.9))
  d.tick(face(0, 0))
  d.tick(face(0.1))
  assert.equal(d.settled(), false)
  d.tick(face(0.9))
  d.tick(face(0.1))
  await d.pending
})

test('multiple faces reject the capture', async () => {
  const d = await detector()
  const rejected = assert.rejects(d.pending, /Only one person/)
  d.tick(face(0.1, 2))
  await rejected
})

test('no face produces an explicit timeout error', async () => {
  const d = await detector()
  const rejected = assert.rejects(d.pending, /No face was detected/)
  d.tick(face(0, 0))
  d.timeout()
  await rejected
})

test('cancelling stops frame processing', async () => {
  const d = await detector()
  const rejected = assert.rejects(d.pending, { name: 'AbortError' })
  d.controller.abort()
  await rejected
  assert.equal(d.hasFrame(), false)
})

test('model download failure is explicit', async () => {
  const d = await detector({ failLoad: true })
  await assert.rejects(d.pending, /Could not load blink detection/)
})

function captureHook() {
  let acceptBlink
  let rejectBlink
  let captures = 0
  const blink = new Promise((resolve, reject) => {
    acceptBlink = resolve
    rejectBlink = reject
  })
  const photo = { name: 'face.jpg' }
  const { useBlinkWebcamCapture } = load('hooks\\useBlinkWebcamCapture.ts', {
    AbortController,
    require: (name) => {
      if (name === 'react') return {
        useCallback: (callback) => callback,
        useEffect: () => {},
        useRef: (current) => ({ current }),
        useState: (value) => [value, () => {}],
      }
      if (name === './useWebcamCapture') return { useWebcamCapture: () => ({
        isActive: true, videoRef: { current: {} },
        stop: () => {}, capture: async () => { captures++; return photo },
      }) }
      if (name === '../lib/faceBlinkDetection') return { waitForEyeBlink: () => blink }
      throw new Error(`Unexpected import: ${name}`)
    },
  })
  return { hook: useBlinkWebcamCapture(), acceptBlink, rejectBlink, captures: () => captures, photo }
}

test('enrollment captures only after a successful blink', async () => {
  const h = captureHook()
  const pending = h.hook.capture()
  await Promise.resolve()
  assert.equal(h.captures(), 0)
  h.acceptBlink()
  assert.equal(await pending, h.photo)
  assert.equal(h.captures(), 1)
})

test('failed blink never captures an enrollment photo', async () => {
  const h = captureHook()
  const pending = h.hook.capture()
  h.rejectBlink(new Error('No blink detected'))
  assert.equal(await pending, null)
  assert.equal(h.captures(), 0)
})

test('cancelled blink cannot produce a stale enrollment photo', async () => {
  const h = captureHook()
  const pending = h.hook.capture()
  await Promise.resolve()
  h.hook.stop()
  h.acceptBlink()
  assert.equal(await pending, null)
  assert.equal(h.captures(), 0)
})

test('repeated clicks do not start simultaneous captures', async () => {
  const h = captureHook()
  const first = h.hook.capture()
  assert.equal(await h.hook.capture(), null)
  h.acceptBlink()
  await first
  assert.equal(h.captures(), 1)
})
