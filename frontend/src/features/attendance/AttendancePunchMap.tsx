import { useEffect, useRef } from 'react'
import L from 'leaflet'
import type { LatLngExpression } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { SupervisorAttendancePunchLocation } from '../../lib/attendanceApi'

interface AttendancePunchMapProps {
  punches: SupervisorAttendancePunchLocation[]
}

function formatPunchTime(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString('en-PH', {
    timeZone: 'Asia/Manila',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function createPopup(punches: SupervisorAttendancePunchLocation[]): HTMLElement {
  const container = document.createElement('div')
  punches.forEach((punch, index) => {
    const entry = document.createElement('div')
    const title = document.createElement('strong')
    title.textContent = punch.action === 'CLOCK_IN' ? 'Clock in' : 'Clock out'
    entry.append(title)

    const employee = document.createElement('p')
    employee.textContent = `${punch.employee_name} (${punch.employee_code})`
    entry.append(employee)

    const time = document.createElement('p')
    time.textContent = formatPunchTime(punch.punched_at)
    entry.append(time)

    if (punch.accuracy_meters !== null) {
      const accuracy = document.createElement('p')
      accuracy.textContent = `GPS accuracy: ${Math.round(punch.accuracy_meters)} m`
      entry.append(accuracy)
    }

    const streetView = document.createElement('a')
    streetView.href = `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${encodeURIComponent(`${punch.latitude},${punch.longitude}`)}`
    streetView.target = '_blank'
    streetView.rel = 'noreferrer'
    streetView.textContent = 'Open Street View'
    entry.append(streetView)
    container.append(entry)

    if (index < punches.length - 1) {
      container.append(document.createElement('hr'))
    }
  })
  return container
}

export default function AttendancePunchMap({ punches }: AttendancePunchMapProps) {
  const mapElement = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = mapElement.current
    if (!element || punches.length === 0) return

    const positions: LatLngExpression[] = punches.map((punch) => [punch.latitude, punch.longitude])
    const map = L.map(element, { center: positions[0], zoom: 15 })
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map)

    const groupedPunches = new Map<string, SupervisorAttendancePunchLocation[]>()
    punches.forEach((punch) => {
      const key = `${punch.latitude},${punch.longitude}`
      groupedPunches.set(key, [...(groupedPunches.get(key) ?? []), punch])
    })
    groupedPunches.forEach((group) => {
      const punch = group[0]
      const hasBothPunchTypes = new Set(group.map((item) => item.action)).size > 1
      L.circleMarker([punch.latitude, punch.longitude], {
        color: '#ffffff',
        fillColor: hasBothPunchTypes
          ? '#7c3aed'
          : punch.action === 'CLOCK_IN' ? '#16a34a' : '#2563eb',
        fillOpacity: 1,
        radius: group.length > 1 ? 10 : 8,
        weight: 2,
      })
        .bindPopup(createPopup(group))
        .addTo(map)
    })

    if (positions.length > 1) {
      map.fitBounds(L.latLngBounds(positions).pad(0.15), { maxZoom: 16 })
    }

    const resizeObserver = new ResizeObserver(() => map.invalidateSize())
    resizeObserver.observe(element)
    const resizeFrame = window.requestAnimationFrame(() => map.invalidateSize())

    return () => {
      window.cancelAnimationFrame(resizeFrame)
      resizeObserver.disconnect()
      map.remove()
    }
  }, [punches])

  return <div ref={mapElement} className="z-0 h-[420px] w-full rounded-lg" aria-label="Attendance punch locations map" />
}
