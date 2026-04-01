import { NavLink, Outlet } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import {
  LayoutDashboard, FolderSearch, Bug, KeyRound, BarChart3,
  FileText, PenTool, Library, Settings, Users, Shield,
  Activity, CreditCard, ScrollText, Database, ChevronLeft,
  ChevronRight, Moon, Sun, LogOut, Search
} from 'lucide-react'
import clsx from 'clsx'

const navSections = [
  {
    label: 'Overview',
    items: [
      { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
    ],
  },
  {
    label: 'KeyGap',
    items: [
      { to: '/keygap/projects', icon: FolderSearch, label: 'Projects' },
      { to: '/keygap/crawls', icon: Bug, label: 'Crawl Manager' },
      { to: '/keygap/keywords', icon: KeyRound, label: 'Keyword Explorer' },
      { to: '/keygap/gaps', icon: BarChart3, label: 'Gap Report' },
      { to: '/keygap/index', icon: Search, label: 'Site Index' },
    ],
  },
  {
    label: 'Inkwell',
    items: [
      { to: '/inkwell/briefs', icon: FileText, label: 'Briefs' },
      { to: '/inkwell/editor', icon: PenTool, label: 'Content Workspace' },
      { to: '/inkwell/library', icon: Library, label: 'Content Library' },
    ],
  },
]

const adminSection = {
  label: 'Admin',
  items: [
    { to: '/admin/users', icon: Users, label: 'Users' },
    { to: '/admin/api-keys', icon: Shield, label: 'API Keys' },
    { to: '/admin/jobs', icon: Activity, label: 'Job Queue' },
    { to: '/admin/billing', icon: CreditCard, label: 'Billing & Usage' },
    { to: '/admin/audit', icon: ScrollText, label: 'Audit Log' },
    { to: '/admin/database', icon: Database, label: 'Database' },
    { to: '/admin/settings', icon: Settings, label: 'System Settings' },
  ],
}

export function AppLayout() {
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const { theme, sidebarCollapsed, toggleTheme, toggleSidebar } = useThemeStore()

  const sections = user?.role === 'admin'
    ? [...navSections, adminSection]
    : navSections

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside
        className={clsx(
          'flex flex-col border-r border-surface-200 dark:border-surface-800',
          'bg-white dark:bg-surface-900 transition-all duration-200',
          sidebarCollapsed ? 'w-16' : 'w-60'
        )}
      >
        {/* Logo */}
        <div className="flex items-center gap-2 px-4 h-14 border-b border-surface-200 dark:border-surface-800">
          <div className="w-8 h-8 rounded-lg bg-brand-500 flex items-center justify-center text-white font-bold text-sm shrink-0">
            S
          </div>
          {!sidebarCollapsed && (
            <span className="font-semibold text-sm text-surface-800 dark:text-surface-200 truncate">
              SEO Platform
            </span>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-5">
          {sections.map((section) => (
            <div key={section.label}>
              {!sidebarCollapsed && (
                <p className="px-2 mb-1 text-[10px] font-semibold uppercase tracking-wider text-surface-400 dark:text-surface-500">
                  {section.label}
                </p>
              )}
              <ul className="space-y-0.5">
                {section.items.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.to === '/'}
                      className={({ isActive }) =>
                        clsx(
                          'flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-sm transition-colors',
                          isActive
                            ? 'bg-brand-500/10 text-brand-500 font-medium'
                            : 'text-surface-600 dark:text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-800'
                        )
                      }
                    >
                      <item.icon className="w-4 h-4 shrink-0" />
                      {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        {/* Footer controls */}
        <div className="border-t border-surface-200 dark:border-surface-800 p-2 space-y-1">
          <button onClick={toggleTheme} className="btn-ghost w-full justify-start">
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            {!sidebarCollapsed && <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>}
          </button>
          <button onClick={toggleSidebar} className="btn-ghost w-full justify-start">
            {sidebarCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
            {!sidebarCollapsed && <span>Collapse</span>}
          </button>
          <button onClick={logout} className="btn-ghost w-full justify-start text-red-500">
            <LogOut className="w-4 h-4" />
            {!sidebarCollapsed && <span>Sign out</span>}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        {/* Top bar */}
        <header className="sticky top-0 z-10 flex items-center justify-between h-14 px-6 border-b border-surface-200 dark:border-surface-800 bg-white/80 dark:bg-surface-900/80 backdrop-blur-sm">
          <div />
          <div className="flex items-center gap-3">
            <span className="text-sm text-surface-500">
              {user?.full_name}
            </span>
            <span className="badge-info capitalize">{user?.role}</span>
          </div>
        </header>

        {/* Page content */}
        <div className="p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
