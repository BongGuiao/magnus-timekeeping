import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision'

const VISION_WASM_BASE =
  'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.1.1/wasm'
const FACE_LANDMARKER_MODEL =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
const BLINK_TIMEOUT_MS = 20_000
const MIN_INFERENCE_INTERVAL_MS = 80
const CLOSED_EYE_SCORE = 0.55
const OPEN_EYE_SCORE = 0.25

let faceLandmarkerPromise: Promise<FaceLandmarker> | null = null

async function getFaceLandmarker(): Promise<FaceLandmarker> {
  if (!faceLandmarkerPromise) {
    faceLandmarkerPromise = FilesetResolver.forVisionTasks(VISION_WASM_BASE)
      .then((wasmFileset) => FaceLandmarker.createFromOptions(wasmFileset, {
        baseOptions: { modelAssetPath: FACE_LANDMARKER_MODEL },
        runningMode: 'VIDEO',
        numFaces: 2,
        outputFaceBlendshapes: true,
      }))
      .catch((error: unknown) => {
        faceLandmarkerPromise = null
        throw new Error(
          `Could not load blink detection. Check your internet connection and try again. ${
            error instanceof Error ? error.message : ''
          }`.trim(),
        )
      })
  }

  return faceLandmarkerPromise
}

export async function waitForEyeBlink(
  video: HTMLVideoElement,
  onStatus: (message: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  signal?.throwIfAborted()
  onStatus('Loading blink detection…')
  const landmarker = await getFaceLandmarker()
  signal?.throwIfAborted()
  onStatus('Look at the camera and blink once.')

  await new Promise<void>((resolve, reject) => {
    let frameId = 0
    let lastInferenceAt = 0
    let hasSeenOpenEyes = false
    let hasSeenClosedEyes = false
    let settled = false
    let hasSeenFace = false
    const timeoutId = window.setTimeout(() => {
      finish(new Error(
        hasSeenFace
          ? 'A blink was not detected. Look at the camera and blink once to try again.'
          : 'No face was detected. Center your face in the camera and try again.',
      ))
    }, BLINK_TIMEOUT_MS)

    function finish(error?: Error) {
      if (settled) return
      settled = true
      window.clearTimeout(timeoutId)
      window.cancelAnimationFrame(frameId)
      signal?.removeEventListener('abort', abort)
      if (error) reject(error)
      else resolve()
    }

    function abort() {
      finish(new DOMException('Blink capture cancelled.', 'AbortError'))
    }

    function detectFrame(timestamp: number) {
      if (settled) return
      if (timestamp - lastInferenceAt < MIN_INFERENCE_INTERVAL_MS) {
        frameId = window.requestAnimationFrame(detectFrame)
        return
      }
      lastInferenceAt = timestamp

      try {
        if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
          const result = landmarker.detectForVideo(video, timestamp)
          if (result.faceLandmarks.length > 1) {
            finish(new Error('Only one person should be visible to the camera.'))
            return
          }
          if (result.faceLandmarks.length === 0) {
            hasSeenOpenEyes = false
            hasSeenClosedEyes = false
            onStatus('Center your face in the camera.')
          }

          const categories = result.faceBlendshapes[0]?.categories
          const leftBlink = categories?.find((item) => item.categoryName === 'eyeBlinkLeft')?.score
          const rightBlink = categories?.find((item) => item.categoryName === 'eyeBlinkRight')?.score
          if (leftBlink !== undefined && rightBlink !== undefined) {
            hasSeenFace = true
            onStatus('Face detected. Blink once to continue.')
            const bothEyesOpen = leftBlink < OPEN_EYE_SCORE && rightBlink < OPEN_EYE_SCORE
            const bothEyesClosed = leftBlink > CLOSED_EYE_SCORE && rightBlink > CLOSED_EYE_SCORE

            if (bothEyesOpen) {
              if (hasSeenClosedEyes) {
                finish()
                return
              }
              hasSeenOpenEyes = true
            } else if (hasSeenOpenEyes && bothEyesClosed) {
              hasSeenClosedEyes = true
            }
          }
        }
      } catch (error) {
        finish(error instanceof Error ? error : new Error('Blink detection failed. Please try again.'))
        return
      }

      frameId = window.requestAnimationFrame(detectFrame)
    }

    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) abort()
    else frameId = window.requestAnimationFrame(detectFrame)
  })
}
