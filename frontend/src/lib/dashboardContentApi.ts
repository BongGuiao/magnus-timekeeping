import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type { Announcement, Holiday } from '../types/dashboard'

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function findList(value: unknown, depth = 0): unknown[] | null {
  if (Array.isArray(value)) return value
  const record = asRecord(value)
  if (!record || depth > 6) return null

  const listKeys = [
    'data',
    'items',
    'results',
    'records',
    'content',
    'result',
    'value',
    'holidays',
    'announcements',
    'announcement_list',
  ]
  for (const key of listKeys) {
    if (!(key in record)) continue
    const items = findList(record[key], depth + 1)
    if (items) return items
  }

  const nestedLists = Object.values(record)
    .filter((item) => Array.isArray(item) || asRecord(item))
    .map((item) => findList(item, depth + 1))
    .filter((items): items is unknown[] => items !== null)
  if (nestedLists.length === 1) {
    return nestedLists[0]
  }

  if ('id' in record || 'title' in record || 'holiday_name' in record) {
    return [record]
  }
  return null
}

function getList(value: unknown, label: string): unknown[] {
  const items = findList(value)
  if (items) return items
  const record = asRecord(value)
  const keys = Object.keys(record ?? {}).join(', ')
  throw new Error(`The ${label} response did not contain a list (response fields: ${keys || 'none'}).`)
}

function getText(value: unknown, fields: string[]): string | null {
  if (typeof value === 'string' && value.trim()) return value.trim()
  const record = asRecord(value)
  if (!record) return null
  for (const field of fields) {
    const text = getText(record[field], fields)
    if (text) return text
  }
  return null
}

function getId(value: unknown, fallback: string): string {
  return getText(value, ['id', 'announcement_id', 'holiday_id', 'uuid']) ?? fallback
}

function toHoliday(value: unknown, index: number): Holiday {
  const record = asRecord(value)
  const date = getText(record, ['date', 'holiday_date', 'holidayDate', 'value', 'iso'])
  const name = getText(record, ['name', 'holiday_name', 'holidayName', 'title', 'label', 'value', 'text', 'en'])
  if (!date || !name) {
    throw new Error('The upcoming holidays response contains an invalid holiday.')
  }
  return { date, name, id: getId(record, `${date}-${index}`) }
}

function toAnnouncement(value: unknown, index: number): Announcement {
  const record = asRecord(value)
  const title = getText(record, ['title', 'announcement_title', 'name'])
  if (!record || !title) {
    throw new Error('The announcements response contains an invalid announcement.')
  }
  return {
    id: getId(record, `announcement-${index}`),
    title,
    body: getText(record.body, ['body', 'content', 'description', 'text']) ?? undefined,
    postedAt: getText(record, ['posted_at', 'postedAt', 'created_at', 'createdAt']) ?? '',
  }
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchUpcomingHolidays(): Promise<Holiday[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<unknown>>('/holidays/upcoming')
    return getList(response.data, 'upcoming holidays').map(toHoliday)
  } catch (error) {
    return rethrowApiError(error, 'Could not load upcoming holidays.')
  }
}

export async function fetchAnnouncements(): Promise<Announcement[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<unknown>>('/announcements/list')
    return getList(response.data, 'announcements').map(toAnnouncement)
  } catch (error) {
    return rethrowApiError(error, 'Could not load announcements.')
  }
}
