import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export interface DeviceRecord {
  id: string
  device_uuid: string
  device_name: string | null
  enrollment_ip: string | null
  employee_id: string | null
  employee_no?: string | null
  employee_first_name?: string | null
  employee_last_name?: string | null
  platform: string
  manufacturer: string | null
  model: string | null
  os_version: string | null
  app_version: string | null
  registration_status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'REVOKED'
  is_active: boolean
  created_at: string | null
  last_seen_at: string | null
}

export interface PendingDeviceSnapshot {
  devices: DeviceRecord[]
  refreshed_at: string
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchPendingDeviceSnapshot(): Promise<PendingDeviceSnapshot> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<PendingDeviceSnapshot>>('/devices/pending-snapshot')
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load the pending device dashboard snapshot.')
  }
}

export async function updateDeviceRegistration(
  deviceId: string,
  registrationStatus: Exclude<DeviceRecord['registration_status'], 'PENDING'>,
  revocationReason?: string,
): Promise<DeviceRecord> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<DeviceRecord>>('/devices/update', {
      id: deviceId,
      registration_status: registrationStatus,
      ...(registrationStatus === 'REVOKED' ? { revocation_reason: revocationReason } : {}),
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, `Could not set this device to ${registrationStatus}.`)
  }
}
