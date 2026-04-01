import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api/client'
import { KeyRound } from 'lucide-react'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const login = useAuthStore((s) => s.login)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const tokens = await api.post<{
        access_token: string
        refresh_token: string
      }>('/auth/login', { email, password })

      // Fetch user profile
      // Temporarily set token for the /me call
      useAuthStore.getState().updateToken(tokens.access_token, tokens.refresh_token)
      const user = await api.get<{
        id: string; email: string; full_name: string; role: 'admin' | 'editor' | 'viewer'; is_active: boolean
      }>('/auth/me')

      login(user, tokens.access_token, tokens.refresh_token)
      navigate('/')
    } catch (err: any) {
      setError('Invalid email or password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-50 dark:bg-surface-950 px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="mx-auto w-12 h-12 rounded-xl bg-brand-500 flex items-center justify-center mb-4">
            <KeyRound className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-surface-800 dark:text-surface-100">
            SEO Platform
          </h1>
          <p className="text-sm text-surface-500 mt-1">KeyGap + Inkwell</p>
        </div>

        <form onSubmit={handleSubmit} className="card p-6 space-y-4">
          {error && (
            <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm">
              {error}
            </div>
          )}

          <div>
            <label className="label">Email</label>
            <input
              type="email"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@legendary-parts.com"
              required
              autoFocus
            />
          </div>

          <div>
            <label className="label">Password</label>
            <input
              type="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </div>

          <button type="submit" disabled={loading} className="btn-primary w-full justify-center">
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
