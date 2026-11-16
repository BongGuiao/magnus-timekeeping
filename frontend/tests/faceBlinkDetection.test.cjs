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

async function detector({ failLoad = false, checkFraming } = {}) {
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
  const pending = waitForEyeBlink({ readyState: 2 }, () => {}, controller.signal, checkFraming)
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

test('a blink outside the face guide does not pass and the timeout says why', async () => {
  let issue = 'Move closer so your face fills the guide.'
  const d = await detector({ checkFraming: () => issue })
  d.tick(face(0.1))
  d.tick(face(0.9))
  d.tick(face(0.1))
  assert.equal(d.settled(), false)
  const timeout = d.timeout
  issue = null
  d.tick(face(0.1))
  d.tick(face(0.9))
  issue = 'Move closer so your face fills the guide.'
  d.tick(face(0.1))
  assert.equal(d.settled(), false)
  const rejected = assert.rejects(d.pending, /Move closer.*blink once/)
  timeout()
  await rejected
})

test('face guide maps to the video frame, judges framing, and crops the capture', () => {
  const { guideRegion, faceFramingIssue, cropRectangle } = load('lib\\faceFraming.ts', {})
  // 640x480 camera shown with object-cover in a 500x300 box; guide inset 28% / 10%.
  const guide = guideRegion(
    { left: 10, top: 20, width: 500, height: 300 },
    { left: 150, top: 50, width: 220, height: 240 },
    640, 480,
  )
  for (const [key, expected] of Object.entries({ x: 0.28, y: 0.18, width: 0.44, height: 0.64 })) {
    assert.ok(Math.abs(guide[key] - expected) < 1e-9, `${key}=${guide[key]}`)
  }
  assert.equal(guideRegion({ left: 0, top: 0, width: 500, height: 300 }, { left: 0, top: 0, width: 0, height: 0 }, 640, 480), null)

  const box = (left, top, right, bottom) => [{ x: left, y: top }, { x: right, y: bottom }]
  assert.equal(faceFramingIssue(box(0.36, 0.3, 0.64, 0.7), guide, 640, 480), null)
  assert.match(faceFramingIssue(box(0.44, 0.42, 0.56, 0.58), guide, 640, 480), /closer/)
  assert.match(faceFramingIssue(box(0.2, 0.05, 0.8, 0.95), guide, 640, 480), /Move back/)
  assert.match(faceFramingIssue(box(0.56, 0.3, 0.84, 0.7), guide, 640, 480), /Center/)

  assert.deepEqual({ ...cropRectangle(guide, 640, 480) }, { x: 67, y: 0, width: 506, height: 480 })
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
      if (name === '../lib/faceFraming') return {}
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
