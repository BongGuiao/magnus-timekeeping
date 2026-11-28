import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiSuccessEnvelope } from '../types/auth'

export interface LeaveMatrixRange {
  worked_from: string
  worked_to: string
  leave_hours: string
}

export interface LeaveMatrix {
  company_id: string
  row_version: number
  ranges: LeaveMatrixRange[]
}

export interface MatrixCompany {
  id: string
  company_code: string
  legal_name: string
}

function rethrow(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body: unknown = error.response?.data
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = body.detail
      if (typeof detail === 'string') throw new Error(detail)
      if (Array.isArray(detail)) {
        const messages = detail.flatMap((item: unknown) =>
          item && typeof item === 'object' && 'msg' in item && typeof item.msg === 'string'
            ? [item.msg.replace(/^Value error, /, '')] : [])
        if (messages.length) throw new Error(messages.join(' '))
      }
    }
    throw new Error(fallback)
  }
  throw error
}

export async function fetchMatrixCompanies(): Promise<MatrixCompany[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<MatrixCompany[]>>('/leave-computation-matrices/companies')
    if (!Array.isArray(response.data?.data) || !response.data.data.every((company) =>
      company && typeof company.id === 'string' && typeof company.company_code === 'string'
      && typeof company.legal_name === 'string')) {
      throw new Error('Invalid company list response. Check that the backend and web proxy are up to date.')
    }
    return response.data.data
  } catch (error) {
    return rethrow(error, 'Could not load companies for leave matrices.')
  }
}

export async function fetchLeaveMatrix(companyId: string): Promise<LeaveMatrix> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<LeaveMatrix>>(`/leave-computation-matrices/${companyId}`)
    return validateMatrix(response.data?.data, companyId)
  } catch (error) {
    return rethrow(error, 'Could not load the leave matrix.')
  }
}

export async function saveLeaveMatrix(companyId: string, matrix: Pick<LeaveMatrix, 'row_version' | 'ranges'>): Promise<LeaveMatrix> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<LeaveMatrix>>(`/leave-computation-matrices/${companyId}`, matrix)
    return validateMatrix(response.data?.data, companyId)
  } catch (error) {
    return rethrow(error, 'Could not save the leave matrix. Check the ranges and try again.')
  }
}

function validateMatrix(matrix: LeaveMatrix | undefined, companyId: string): LeaveMatrix {
  if (!matrix || matrix.company_id !== companyId || !Number.isInteger(matrix.row_version)
    || matrix.row_version < 0 || !Array.isArray(matrix.ranges)) {
    throw new Error('Invalid leave matrix response. Check that the backend and web proxy are up to date.')
  }
  return matrix
}
