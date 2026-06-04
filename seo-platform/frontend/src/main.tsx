import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useThemeStore } from '@/stores/theme'
import '@/styles/globals.css'

// Layout
import { AppLayout } from '@/components/layout/AppLayout'

// Guards
import { AuthGuard, AdminGuard } from '@/guards'

// Pages — Shared
import { LoginPage } from '@/pages/shared/LoginPage'
import { DashboardPage } from '@/pages/shared/DashboardPage'

// Pages — KeyGap
import { ProjectsPage, CrawlsPage, KeywordsPage, GapsPage, SiteIndexPage } from '@/pages/keygap'

// Pages — Inkwell
import { BriefsPage, EditorPage, LibraryPage } from '@/pages/inkwell'

// Pages — Admin
import {
  UsersPage, ApiKeysPage, JobsPage, BillingPage,
  AuditPage, DatabasePage, SettingsPage
} from '@/pages/admin'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
  },
})

function App() {
  // Apply theme on mount
  const theme = useThemeStore((s) => s.theme)
  React.useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }, [theme])

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />

          {/* Authenticated */}
          <Route element={<AuthGuard />}>
            <Route element={<AppLayout />}>
              {/* Dashboard */}
              <Route path="/" element={<DashboardPage />} />

              {/* KeyGap */}
              <Route path="/keygap/projects" element={<ProjectsPage />} />
              <Route path="/keygap/crawls" element={<CrawlsPage />} />
              <Route path="/keygap/keywords" element={<KeywordsPage />} />
              <Route path="/keygap/gaps" element={<GapsPage />} />
              <Route path="/keygap/index" element={<SiteIndexPage />} />

              {/* Inkwell */}
              <Route path="/inkwell/briefs" element={<BriefsPage />} />
              <Route path="/inkwell/editor" element={<EditorPage />} />
              <Route path="/inkwell/library" element={<LibraryPage />} />

              {/* Admin (role-gated) */}
              <Route element={<AdminGuard />}>
                <Route path="/admin/users" element={<UsersPage />} />
                <Route path="/admin/api-keys" element={<ApiKeysPage />} />
                <Route path="/admin/jobs" element={<JobsPage />} />
                <Route path="/admin/billing" element={<BillingPage />} />
                <Route path="/admin/audit" element={<AuditPage />} />
                <Route path="/admin/database" element={<DatabasePage />} />
                <Route path="/admin/settings" element={<SettingsPage />} />
              </Route>
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
