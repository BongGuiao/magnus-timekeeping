import { AxiosError } from 'axios'
import { apiClient } from './apiClient'

export async function downloadDatabaseBackup(): Promise<void> {
  try {
    const response = await apiClient.post<Blob>('/auth/database-backup', undefined, {
      responseType: 'blob', timeout: 360_000,
    })
    const url = URL.createObjectURL(response.data)
    try {
      const link = document.createElement('a')
      link.href = url
      link.download = `magnus-database-${new Date().toISOString().replace(/[:.]/g, '-')}.dump`
      document.body.appendChild(link)
      link.click()
      link.remove()
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    }
  } catch (cause) {
    if (cause instanceof AxiosError) {
      const data: unknown = cause.response?.data
      if (data instanceof Blob) {
        let body: unknown
        try { body = JSON.parse(await data.text()) }
        catch (error) { if (!(error instanceof SyntaxError)) throw error }
        if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
          throw new Error(body.detail)
        }
      }
      throw new Error('Backup could not be downloaded. Check your connection and try again. Contact the administrator if the problem continues.')
    }
    throw cause
  }
}
