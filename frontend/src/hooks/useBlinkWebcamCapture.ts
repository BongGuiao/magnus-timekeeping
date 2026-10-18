import { useCallback, useEffect, useRef, useState } from 'react'
import { useWebcamCapture } from './useWebcamCapture'

export function useBlinkWebcamCapture() {
  const webcam = useWebcamCapture()
  const pendingRef = useRef<AbortController | null>(null)
  const [isCheckingBlink, setIsCheckingBlink] = useState(false)
  const [blinkStatus, setBlinkStatus] = useState('')
  const [blinkError, setBlinkError] = useState<string | null>(null)

  const stopCamera = webcam.stop
  const stop = useCallback(() => {
    pendingRef.current?.abort()
    pendingRef.current = null
    setIsCheckingBlink(false)
    setBlinkStatus('')
    stopCamera()
  }, [stopCamera])

  useEffect(() => () => {
    pendingRef.current?.abort()
    pendingRef.current = null
  }, [])

  async function capture(): Promise<File | null> {
    if (pendingRef.current) return null
    const video = webcam.videoRef.current
    if (!webcam.isActive || !video) {
      setBlinkError('Start the camera before capturing a face.')
      return null
    }

    const controller = new AbortController()
    pendingRef.current = controller
    setIsCheckingBlink(true)
    setBlinkError(null)
    try {
      const { waitForEyeBlink } = await import('../lib/faceBlinkDetection')
      controller.signal.throwIfAborted()
      await waitForEyeBlink(video, setBlinkStatus, controller.signal)
      controller.signal.throwIfAborted()
      const photo = await webcam.capture()
      controller.signal.throwIfAborted()
      return photo
    } catch (error) {
      if (!controller.signal.aborted) {
        setBlinkError(error instanceof Error ? error.message : 'Blink detection failed. Please try again.')
      }
      return null
    } finally {
      if (pendingRef.current === controller) {
        pendingRef.current = null
        setIsCheckingBlink(false)
        setBlinkStatus('')
      }
    }
  }

  async function start() {
    setBlinkError(null)
    return webcam.start()
  }

  return { ...webcam, capture, start, stop, isCheckingBlink, blinkStatus, error: blinkError ?? webcam.error }
}
