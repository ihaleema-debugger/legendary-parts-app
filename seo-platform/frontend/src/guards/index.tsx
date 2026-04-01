import { Navigate, Outlet } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'

export function AuthGuard() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <Outlet />
}

export function RoleGuard({ roles }: { roles: string[] }) {
  const user = useAuthStore((s) => s.user)
  if (!user || !roles.includes(user.role)) {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}

export function AdminGuard() {
  return <RoleGuard roles={['admin']} />
}
