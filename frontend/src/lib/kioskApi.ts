import axios from 'axios'
import { getOrCreateDeviceKey } from './attendanceDevice'
import { getAttendanceErrorMessage } from './attendanceApi'
import { apiClient } from './apiClient'
import type { ApiSuccessEnvelope, UserSummary } from '../types/auth'
import type { BreakResult, BreakType, ClockResult, LastAttendance } from '../types/attendance'

// Kiosk requests must never inherit an employee/admin bearer token.
const kioskClient = axios.create({ baseURL: '/attendance/kiosk', timeout: 30_000 })
const KEY_SCOPE = 'shared-kiosk-v1'
let identityRequest: ReturnType<typeof getOrCreateDeviceKey> | undefined

function kioskIdentity() {
  if (!identityRequest) {
    identityRequest = getOrCreateDeviceKey(KEY_SCOPE).finally(() => { identityRequest = undefined })
  }
  return identityRequest
}

export interface KioskDevice {
  id: string
  device_name: string
  status: 'PENDING' | 'APPROVED' | 'REVOKED'
  company_id: string | null
  location_id: string | null
  location_name?: string | null
  approved_at: string | null
  revoked_at: string | null
  last_seen_at: string | null
}

export interface KioskPairing {
  device_id: string
  status: KioskDevice['status']
  pairing_code: string | null
  pairing_expires_at: string
}

async function hashBytes(bytes: BufferSource): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

async function proof(purpose: 'STATUS' | 'IDENTIFY' | 'CLOCK' | 'BREAK', payload: string) {
  const { identity, key } = await kioskIdentity()
  const response = await kioskClient.post<ApiSuccessEnvelope<{ challenge_id: string; message: string }>>('/challenge', {
    device_id: identity.deviceUuid,
    purpose,
    payload_hash: await hashBytes(new TextEncoder().encode(payload)),
  })
  const challenge = response.data.data
  const signed = await crypto.subtle.sign(
    { name: 'ECDSA', hash: 'SHA-256' }, key.privateKey, new TextEncoder().encode(challenge.message),
  )
  const signature = btoa(String.fromCharCode(...new Uint8Array(signed)))
    .replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
  return { challenge_id: challenge.challenge_id, signature }
}

export async function enrollKiosk(deviceName: string): Promise<KioskPairing> {
  try {
    const { identity, key } = await kioskIdentity()
    const response = await kioskClient.post<ApiSuccessEnvelope<KioskPairing>>('/enroll', {
      device_id: identity.deviceUuid, device_name: deviceName.trim(), public_key_jwk: key.publicKeyJwk,
    })
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not register this kiosk.'))
  }
}

export async function fetchKioskStatus(): Promise<KioskDevice> {
  try {
    const response = await kioskClient.post<ApiSuccessEnvelope<KioskDevice>>('/status', await proof('STATUS', ''))
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not verify this kiosk. Check the network and device approval.'))
  }
}

export async function identifyKioskEmployee(employeeCode: string): Promise<{
  user: UserSummary
  last_attendance: LastAttendance | null
}> {
  try {
    const code = employeeCode.trim()
    const response = await kioskClient.post<ApiSuccessEnvelope<{
      user: UserSummary; last_attendance: LastAttendance | null
    }>>('/identify', { ...await proof('IDENTIFY', code), employee_code: code })
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not identify this employee at this kiosk.'))
  }
}

async function submitPunch<T>(path: string, purpose: 'CLOCK' | 'BREAK', file: File, userId: string, action: string): Promise<T> {
  try {
    const payload = `${userId}\n${action}\n${await hashBytes(await file.arrayBuffer())}`
    const deviceProof = await proof(purpose, payload)
    const form = new FormData()
    form.append('file', file, file.name)
    form.append('user_id', userId)
    form.append('action', action)
    form.append('challenge_id', deviceProof.challenge_id)
    form.append('signature', deviceProof.signature)
    const response = await kioskClient.post<ApiSuccessEnvelope<T>>(path, form)
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Attendance was not confirmed. Check the connection and attendance before retrying.'))
  }
}

export const kioskAttendanceTransport = {
  identify: identifyKioskEmployee,
  clock: (file: File, userId: string, clockOut: boolean) =>
    submitPunch<ClockResult>('/clock', 'CLOCK', file, userId, clockOut ? 'clock_out' : 'clock_in'),
  break: (file: File, userId: string, action: BreakType) =>
    submitPunch<BreakResult>('/break', 'BREAK', file, userId, action),
}

export async function listKioskDevices(): Promise<KioskDevice[]> {
  const response = await apiClient.get<ApiSuccessEnvelope<KioskDevice[]>>('/attendance/kiosk/devices')
  return response.data.data
}

export async function fetchKioskCompany(): Promise<{ id: string; legal_name: string }> {
  const response = await apiClient.get<ApiSuccessEnvelope<{ id: string; legal_name: string }>>('/attendance/kiosk/company')
  return response.data.data
}

export async function approveKiosk(pairingCode: string, locationId: string): Promise<void> {
  await apiClient.post('/attendance/kiosk/approve', {
    pairing_code: pairingCode.trim().toUpperCase(), location_id: locationId,
  })
}

export async function revokeKiosk(deviceId: string): Promise<void> {
  await apiClient.post(`/attendance/kiosk/devices/${encodeURIComponent(deviceId)}/revoke`)
}
