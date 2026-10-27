import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type { Company } from '../types/company'

export type CompanyWritePayload = Omit<Company, 'id' | 'created_at' | 'created_by' | 'updated_at' | 'updated_by' | 'row_version'>

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchCompanies(): Promise<Company[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<Company[]>>('/companies/list')
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load companies.')
  }
}

export async function fetchPayrollParameterCompanies(): Promise<Company[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<Company[]>>('/payroll/system-parameters/companies')
    return response.data.data
  } catch (error) {
    if (error instanceof AxiosError && error.response?.status === 404) {
      throw new Error(
        'The System Parameters company endpoint was not found. Restart or redeploy the backend so it loads the latest payroll routes.',
      )
    }
    return rethrowApiError(error, 'Could not load companies available for payroll parameters.')
  }
}

export async function fetchCompany(companyId: string): Promise<Company> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<Company>>(`/companies/${companyId}`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load this company.')
  }
}

export async function createCompany(payload: CompanyWritePayload): Promise<Company> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<Company>>('/companies/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the company.')
  }
}

export async function updateCompany(companyId: string, payload: CompanyWritePayload): Promise<Company> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<Company>>('/companies/update', { ...payload, id: companyId })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the company.')
  }
}