import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

type AttendanceDeviceAction = 'CLOCK' | 'BREAK'

interface DeviceEnrollmentResponse {
  id: string
  device_uuid: string
  registration_status: string
}

interface DeviceRegistrationRecord {
  device_uuid: string
  registration_status: string
  is_active: boolean
}

interface DeviceChallengeResponse {
  challenge_id: string
  message: string
  expires_at: string
}

export type AttendanceBrowserRegistrationStatus =
  | 'APPROVED'
  | 'PENDING'
  | 'REJECTED'
  | 'REVOKED'
  | 'INACTIVE'
  | 'NOT_REGISTERED'
  | 'UNKNOWN'

interface StoredDeviceKey {
  privateKey: CryptoKey
  publicKeyJwk: JsonWebKey
}

interface LocalDeviceIdentity {
  deviceUuid: string
}

interface UserAgentData {
  model?: string
  platform?: string
  platformVersion?: string
  getHighEntropyValues?: (hints: string[]) => Promise<{
    model?: string
    platform?: string
    platformVersion?: string
  }>
}

const KEY_DATABASE = 'magnus-attendance-device-keys'
const KEY_STORE = 'device-keys'
const LOCAL_IDENTITY_PREFIX = 'magnus-attendance-device:'

function apiError(error: unknown, fallback: string): Error {
  if (!(error instanceof AxiosError)) {
    return error instanceof Error ? error : new Error(fallback)
  }
  const response = error.response?.data as ApiErrorEnvelope | undefined
  return new Error(typeof response?.detail === 'string' ? response.detail : fallback)
}

function identityStorageKey(userId: string): string {
  return `${LOCAL_IDENTITY_PREFIX}${userId}`
}

function readLocalIdentity(userId: string): LocalDeviceIdentity | null {
  const stored = localStorage.getItem(identityStorageKey(userId))
  if (!stored) return null
  try {
    const identity = JSON.parse(stored) as LocalDeviceIdentity
    return typeof identity.deviceUuid === 'string' ? identity : null
  } catch {
    return null
  }
}

function writeLocalIdentity(userId: string, identity: LocalDeviceIdentity): void {
  localStorage.setItem(identityStorageKey(userId), JSON.stringify(identity))
}

function getOperatingSystemVersion(userAgent: string): string | null {
  const windowsVersion = userAgent.match(/Windows NT ([\d.]+)/i)?.[1]
  if (windowsVersion) {
    const windowsNames: Record<string, string> = {
      '10.0': '10/11',
      '6.3': '8.1',
      '6.2': '8',
      '6.1': '7',
    }
    return `Windows ${windowsNames[windowsVersion] ?? windowsVersion}`
  }

  const androidVersion = userAgent.match(/Android ([\d.]+)/i)?.[1]
  if (androidVersion) return `Android ${androidVersion}`

  const iosVersion = userAgent.match(/(?:iPhone|iPad|iPod).* OS ([\d_]+)/i)?.[1]
  if (iosVersion) return `iOS ${iosVersion.replaceAll('_', '.')}`

  const macVersion = userAgent.match(/Mac OS X ([\d_]+)/i)?.[1]
  if (macVersion) return `macOS ${macVersion.replaceAll('_', '.')}`

  const chromeOsVersion = userAgent.match(/CrOS [^ ]+ ([\d.]+)/i)?.[1]
  if (chromeOsVersion) return `ChromeOS ${chromeOsVersion}`

  return null
}

async function getBrowserEnrollmentMetadata() {
  const userAgent = navigator.userAgent
  const userAgentData = (navigator as Navigator & { userAgentData?: UserAgentData }).userAgentData
  let hints = userAgentData
  if (userAgentData?.getHighEntropyValues) {
    try {
      hints = await userAgentData.getHighEntropyValues(['model', 'platform', 'platformVersion'])
    } catch (error) {
      console.warn('Could not read optional browser device details during enrollment.', error)
    }
  }
  const userAgentOsVersion = getOperatingSystemVersion(userAgent)

  return {
    manufacturer: null,
    model: hints?.model?.trim() || null,
    os_version: userAgentOsVersion?.startsWith('Windows ')
      ? userAgentOsVersion
      : hints?.platform && hints.platformVersion
      ? `${hints.platform} ${hints.platformVersion}`
      : userAgentOsVersion,
    app_version: import.meta.env.VITE_APP_VERSION,
  }
}

export async function checkAttendanceBrowserRegistration(
  userId: string,
  employeeId: string | null | undefined,
): Promise<AttendanceBrowserRegistrationStatus> {
  if (!employeeId) {
    throw new Error('This employee account has no linked employee record.')
  }

  const identity = readLocalIdentity(userId)
  if (!identity) return 'NOT_REGISTERED'

  try {
    const response = await apiClient.get<ApiSuccessEnvelope<DeviceRegistrationRecord[]>>('/devices/list', {
      params: { employee_id: employeeId },
    })
    const device = response.data.data.find((record) => record.device_uuid === identity.deviceUuid)
    if (!device) return 'NOT_REGISTERED'

    switch (device.registration_status) {
      case 'PENDING':
      case 'REJECTED':
      case 'REVOKED':
        return device.registration_status
      case 'APPROVED':
        return device.is_active ? 'APPROVED' : 'INACTIVE'
      default:
        return 'UNKNOWN'
    }
  } catch (error) {
    throw apiError(error, "Could not check this browser's registration status.")
  }
}

function openKeyDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(KEY_DATABASE, 1)
    request.onupgradeneeded = () => {
      request.result.createObjectStore(KEY_STORE)
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('Could not open browser key storage.'))
  })
}

async function readStoredKey(deviceUuid: string): Promise<StoredDeviceKey | undefined> {
  const database = await openKeyDatabase()
  try {
    return await new Promise((resolve, reject) => {
      const request = database.transaction(KEY_STORE, 'readonly').objectStore(KEY_STORE).get(deviceUuid)
      request.onsuccess = () => resolve(request.result as StoredDeviceKey | undefined)
      request.onerror = () => reject(request.error ?? new Error('Could not read the browser key.'))
    })
  } finally {
    database.close()
  }
}

async function writeStoredKey(deviceUuid: string, key: StoredDeviceKey): Promise<void> {
  const database = await openKeyDatabase()
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(KEY_STORE, 'readwrite')
      transaction.objectStore(KEY_STORE).put(key, deviceUuid)
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error ?? new Error('Could not save the browser key.'))
      transaction.onabort = () => reject(transaction.error ?? new Error('Browser key storage was interrupted.'))
    })
  } finally {
    database.close()
  }
}

async function getOrCreateDeviceKey(userId: string): Promise<{
  identity: LocalDeviceIdentity
  key: StoredDeviceKey
}> {
  if (!globalThis.crypto?.subtle || !window.isSecureContext) {
    throw new Error('Device verification requires HTTPS (or localhost) and Web Crypto support.')
  }

  const existingIdentity = readLocalIdentity(userId)
  if (existingIdentity) {
    const existingKey = await readStoredKey(existingIdentity.deviceUuid)
    if (existingKey) return { identity: existingIdentity, key: existingKey }
  }

  const deviceUuid = crypto.randomUUID()
  const pair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' },
    false,
    ['sign', 'verify'],
  )
  const key: StoredDeviceKey = {
    privateKey: pair.privateKey,
    publicKeyJwk: await crypto.subtle.exportKey('jwk', pair.publicKey),
  }
  await writeStoredKey(deviceUuid, key)
  const identity = { deviceUuid }
  writeLocalIdentity(userId, identity)
  return { identity, key }
}

export async function registerAttendanceBrowser(userId: string, deviceName: string): Promise<string> {
  const { identity, key } = await getOrCreateDeviceKey(userId)
  const metadata = await getBrowserEnrollmentMetadata()

  try {
    const response = await apiClient.post<ApiSuccessEnvelope<DeviceEnrollmentResponse>>(
      '/devices/enroll',
      {
        user_id: userId,
        device_uuid: identity.deviceUuid,
        device_name: deviceName.trim(),
        public_key_jwk: key.publicKeyJwk,
        manufacturer: metadata.manufacturer,
        model: metadata.model,
        os_version: metadata.os_version,
        app_version: metadata.app_version,
      },
    )
    writeLocalIdentity(userId, identity)
    switch (response.data.data.registration_status) {
      case 'APPROVED':
        return `“${deviceName.trim()}” is already registered and approved.`
      case 'PENDING':
        return `“${deviceName.trim()}” was submitted for administrator approval. Attendance will be enabled after approval.`
      default:
        return `This browser registration is ${response.data.data.registration_status.toLowerCase()}. Contact an administrator.`
    }
  } catch (error) {
    throw apiError(error, 'Could not register this browser.')
  }
}

export async function createAttendanceDeviceProof(
  userId: string,
  action: AttendanceDeviceAction,
): Promise<{ challengeId: string; signature: string }> {
  const { identity, key } = await getOrCreateDeviceKey(userId)

  try {
    const response = await apiClient.post<ApiSuccessEnvelope<DeviceChallengeResponse>>(
      '/attendance/device-challenge',
      {
        user_id: userId,
        device_uuid: identity.deviceUuid,
        action,
      },
    )
    const challenge = response.data.data
    const signedBytes = await crypto.subtle.sign(
      { name: 'ECDSA', hash: 'SHA-256' },
      key.privateKey,
      new TextEncoder().encode(challenge.message),
    )
    const binary = String.fromCharCode(...new Uint8Array(signedBytes))
    const signature = btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
    return { challengeId: challenge.challenge_id, signature }
  } catch (error) {
    throw apiError(error, 'Could not verify this browser. Check that it is approved and try again.')
  }
}
