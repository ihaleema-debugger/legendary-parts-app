/**
 * Typed API client with JWT auth and auto-refresh.
 */

import { useAuthStore } from '@/stores/auth'

const BASE_URL = '/api'

class ApiClient {
  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options: RequestInit = {}
  ): Promise<T> {
    const { accessToken, refreshToken, updateToken, logout } = useAuthStore.getState()

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...((options.headers as Record<string, string>) || {}),
    }

    if (accessToken) {
      headers['Authorization'] = `Bearer ${accessToken}`
    }

    const res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      ...options,
    })

    // Auto-refresh on 401
    if (res.status === 401 && refreshToken) {
      const refreshRes = await fetch(`${BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })

      if (refreshRes.ok) {
        const tokens = await refreshRes.json()
        updateToken(tokens.access_token, tokens.refresh_token)

        // Retry original request
        headers['Authorization'] = `Bearer ${tokens.access_token}`
        const retry = await fetch(`${BASE_URL}${path}`, {
          method,
          headers,
          body: body ? JSON.stringify(body) : undefined,
        })
        if (!retry.ok) throw new ApiError(retry.status, await retry.text())
        return retry.json()
      } else {
        logout()
        throw new ApiError(401, 'Session expired')
      }
    }

    if (!res.ok) {
      const errText = await res.text()
      throw new ApiError(res.status, errText)
    }

    return res.json()
  }

  get<T>(path: string) { return this.request<T>('GET', path) }
  post<T>(path: string, body?: unknown) { return this.request<T>('POST', path, body) }
  put<T>(path: string, body?: unknown) { return this.request<T>('PUT', path, body) }
  del<T>(path: string) { return this.request<T>('DELETE', path) }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export const api = new ApiClient()
