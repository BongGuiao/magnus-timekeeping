import { apiClient } from './apiClient'
import { getAttendanceErrorMessage } from './attendanceApi'
import type { ApiSuccessEnvelope } from '../types/auth'

export type NoticeTemplateModule = 'TARDINESS' | 'RETURN_TO_WORK'

export interface NoticeTemplate {
  id: string
  name: string
  module: NoticeTemplateModule
  is_active: boolean
  created_by: string
  created_at: string
}

export interface NoticeTemplateDetail extends NoticeTemplate {
  sanitized_html: string
}

const endpoint = '/attendance/notice-templates'

export async function listNoticeTemplates(): Promise<NoticeTemplate[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<NoticeTemplate[]>>(endpoint)
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load notice templates.'))
  }
}

export async function getNoticeTemplate(id: string): Promise<NoticeTemplateDetail> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<NoticeTemplateDetail>>(`${endpoint}/${encodeURIComponent(id)}`)
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load the template preview.'))
  }
}

export async function uploadNoticeTemplate(name: string, module: NoticeTemplateModule, file: File): Promise<NoticeTemplateDetail> {
  const form = new FormData()
  form.append('name', name)
  form.append('module', module)
  form.append('file', file)
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<NoticeTemplateDetail>>(endpoint, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not upload the notice template.'))
  }
}

export async function activateNoticeTemplate(id: string): Promise<NoticeTemplateDetail> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<NoticeTemplateDetail>>(`${endpoint}/${encodeURIComponent(id)}/activate`)
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not activate the notice template.'))
  }
}
