import { useCallback, useEffect, useRef, useState } from 'react'
import { cropRectangle } from '../lib/faceFraming'
import type { FaceRegion } from '../lib/faceFraming'

export function useWebcamCapture() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [isActive, setIsActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isCameraApiAvailable = typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia)

  const start = useCallback(async () => {
    setError(null)
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Live camera access requires HTTPS. Use the device camera option instead.')
      return false
    }

    try {
      const stream = streamRef.current ?? await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      setIsActive(true)
      return true
    } catch (err) {
      streamRef.current?.getTracks().forEach((track) => track.stop())
      streamRef.current = null
      setError(err instanceof Error ? err.message : 'Could not access the webcam.')
      return false
    }
  }, [])

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
    setIsActive(false)
  }, [])

  // Release the camera if the page unmounts while the stream is still open
  useEffect(() => stop, [stop])

  const capture = useCallback(async (region?: FaceRegion): Promise<File | null> => {
    const video = videoRef.current
    if (!video) {
      setError('The camera is not ready yet. Please try again.')
      return null
    }

    if (!video.videoWidth) {
      await new Promise<void>((resolve) => {
        const timeout = window.setTimeout(resolve, 3000)
        video.addEventListener('loadeddata', () => {
          window.clearTimeout(timeout)
          resolve()
        }, { once: true })
      })
    }

    if (!video.videoWidth) {
      setError('The camera is not ready yet. Please try again.')
      return null
    }

    return new Promise((resolve) => {
      const canvas = document.createElement('canvas')
      const crop = region
        ? cropRectangle(region, video.videoWidth, video.videoHeight)
        : { x: 0, y: 0, width: video.videoWidth, height: video.videoHeight }
      canvas.width = crop.width
      canvas.height = crop.height
      canvas.getContext('2d')?.drawImage(
        video, crop.x, crop.y, crop.width, crop.height, 0, 0, crop.width, crop.height,
      )

      canvas.toBlob((blob) => {
        if (!blob) {
          setError('Could not capture an image. Please try again.')
          resolve(null)
          return
        }
        resolve(new File([blob], 'face-capture.jpg', { type: 'image/jpeg' }))
      }, 'image/jpeg', 0.92)
    })
  }, [])

  const clearError = useCallback(() => setError(null), [])

  return { videoRef, isActive, isCameraApiAvailable, error, start, stop, capture, clearError }
}
