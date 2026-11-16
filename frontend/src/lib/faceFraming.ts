/** A rectangle in normalized video-frame coordinates (0..1 on both axes). */
export interface FaceRegion {
  x: number
  y: number
  width: number
  height: number
}

interface Box {
  left: number
  top: number
  width: number
  height: number
}

interface Point {
  x: number
  y: number
}

const MIN_FACE_FILL = 0.5
const MAX_FACE_FILL = 1.1
const MAX_CENTER_OFFSET = 0.2
// Kept around the guide so the server-side detector still sees the whole head.
const CROP_PADDING = 0.4

/** Maps an on-screen guide onto the frame of a video displayed with object-fit: cover. */
export function guideRegion(
  videoBox: Box, guideBox: Box, videoWidth: number, videoHeight: number,
): FaceRegion | null {
  if (!videoWidth || !videoHeight || !videoBox.width || !videoBox.height || !guideBox.width || !guideBox.height) {
    return null
  }
  const scale = Math.max(videoBox.width / videoWidth, videoBox.height / videoHeight)
  const shownWidth = videoWidth * scale
  const shownHeight = videoHeight * scale
  const offsetX = (videoBox.width - shownWidth) / 2
  const offsetY = (videoBox.height - shownHeight) / 2
  return {
    x: (guideBox.left - videoBox.left - offsetX) / shownWidth,
    y: (guideBox.top - videoBox.top - offsetY) / shownHeight,
    width: guideBox.width / shownWidth,
    height: guideBox.height / shownHeight,
  }
}

/** Returns what the person should change, or null when the face fills and is centered in the guide. */
export function faceFramingIssue(
  landmarks: Point[], guide: FaceRegion, videoWidth: number, videoHeight: number,
): string | null {
  if (!landmarks.length) return null
  const xs = landmarks.map((point) => point.x)
  const ys = landmarks.map((point) => point.y)
  const top = Math.min(...ys)
  const faceHeight = (Math.max(...ys) - top) * videoHeight
  const guideWidth = guide.width * videoWidth
  const guideHeight = guide.height * videoHeight

  if (faceHeight < Math.min(guideWidth, guideHeight) * MIN_FACE_FILL) {
    return 'Move closer so your face fills the guide.'
  }
  if (faceHeight > guideHeight * MAX_FACE_FILL) {
    return 'Move back so your whole face fits inside the guide.'
  }
  const centerX = (Math.min(...xs) + Math.max(...xs)) / 2
  const centerY = top + faceHeight / videoHeight / 2
  const offsetX = Math.abs(centerX - (guide.x + guide.width / 2)) / guide.width
  const offsetY = Math.abs(centerY - (guide.y + guide.height / 2)) / guide.height
  if (offsetX > MAX_CENTER_OFFSET || offsetY > MAX_CENTER_OFFSET) {
    return 'Center your face inside the guide.'
  }
  return null
}

/** Pixel rectangle to capture: the guide plus padding, clamped to the frame. */
export function cropRectangle(guide: FaceRegion, videoWidth: number, videoHeight: number) {
  const left = Math.max(0, guide.x - guide.width * CROP_PADDING)
  const top = Math.max(0, guide.y - guide.height * CROP_PADDING)
  const right = Math.min(1, guide.x + guide.width * (1 + CROP_PADDING))
  const bottom = Math.min(1, guide.y + guide.height * (1 + CROP_PADDING))
  const x = Math.round(left * videoWidth)
  const y = Math.round(top * videoHeight)
  return {
    x,
    y,
    width: Math.max(1, Math.round(right * videoWidth) - x),
    height: Math.max(1, Math.round(bottom * videoHeight) - y),
  }
}
