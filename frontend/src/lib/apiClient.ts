import axios from 'axios'

// Relative baseURL: nginx proxies /auth/* (and other API paths) to the FastAPI backend.
export const apiClient = axios.create({
  baseURL: '/',
  headers: { 'Content-Type': 'application/json' },
})

// Attach the stored bearer token (if any) to every outgoing request.
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})
