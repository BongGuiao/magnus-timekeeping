import { useCallback, useEffect, useRef, useState } from 'react'

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

  const capture = useCallback(async (): Promise<File | null> => {
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
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      canvas.getContext('2d')?.drawImage(video, 0, 0)

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
