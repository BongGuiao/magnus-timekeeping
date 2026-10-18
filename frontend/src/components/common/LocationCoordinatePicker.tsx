import { useEffect, useRef } from 'react'
import L from 'leaflet'
import type { LatLngExpression, LeafletMouseEvent } from 'leaflet'
import 'leaflet/dist/leaflet.css'

export interface Coordinates {
  latitude: number
  longitude: number
}

interface LocationCoordinatePickerProps {
  center: Coordinates
  onSelect: (coordinates: Coordinates) => void
}

export default function LocationCoordinatePicker({ center, onSelect }: LocationCoordinatePickerProps) {
  const mapElement = useRef<HTMLDivElement>(null)
  const onSelectRef = useRef(onSelect)

  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  useEffect(() => {
    const element = mapElement.current
    if (!element) return

    const mapCenter: LatLngExpression = [center.latitude, center.longitude]
    const map = L.map(element, { center: mapCenter, doubleClickZoom: false, zoom: 16 })
    const marker = L.circleMarker(mapCenter, {
      color: '#ffffff',
      fillColor: '#4f46e5',
      fillOpacity: 1,
      radius: 8,
      weight: 3,
    }).addTo(map)

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map)

    function handleDoubleClick(event: LeafletMouseEvent) {
      marker.setLatLng(event.latlng)
      onSelectRef.current({
        latitude: Number(event.latlng.lat.toFixed(6)),
        longitude: Number(event.latlng.lng.toFixed(6)),
      })
    }

    map.on('dblclick', handleDoubleClick)
    const resizeObserver = new ResizeObserver(() => map.invalidateSize())
    resizeObserver.observe(element)
    const resizeFrame = window.requestAnimationFrame(() => map.invalidateSize())

    return () => {
      window.cancelAnimationFrame(resizeFrame)
      resizeObserver.disconnect()
      map.off('dblclick', handleDoubleClick)
      map.remove()
    }
  }, [center.latitude, center.longitude])

  return <div ref={mapElement} className="z-0 h-full min-h-0 w-full" aria-label="Double-click to select location coordinates" />
}
