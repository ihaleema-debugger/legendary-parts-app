import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import { Plus, RotateCw, Trash2, Eye, RefreshCw } from 'lucide-react'

// ═══════════════════════════════════════════════
// USERS
// ═══════════════════════════════════════════════

export function UsersPage() {
  const [users, setUsers] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<any[]>('/admin/users').then(setUsers).finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">User Management</h1>
        <button className="btn-primary"><Plus className="w-4 h-4" /> Invite User</button>
      </div>
      <div className="card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-surface-200 dark:border-surface-800">
              <th className="text-left p-3 font-medium text-surface-500">Name</th>
              <th className="text-left p-3 font-medium text-surface-500">Email</th>
              <th className="text-left p-3 font-medium text-surface-500">Role</th>
              <th className="text-left p-3 font-medium text-surface-500">Status</th>
              <th className="text-left p-3 font-medium text-surface-500">Last Login</th>
              <th className="text-right p-3 font-medium text-surface-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="p-8 text-center text-surface-500">Loading users...</td></tr>
            ) : users.map((u) => (
              <tr key={u.id} className="border-b border-surface-100 dark:border-surface-800/50">
                <td className="p-3 font-medium">{u.full_name}</td>
                <td className="p-3 text-surface-500">{u.email}</td>
                <td className="p-3"><span className="badge-info capitalize">{u.role}</span></td>
                <td className="p-3">
                  <span className={u.is_active ? 'badge-success' : 'badge-error'}>
                    {u.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="p-3 text-surface-500 text-xs">
                  {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'Never'}
                </td>
                <td className="p-3 text-right">
                  <button className="btn-ghost text-xs">Edit</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// API KEYS
// ═══════════════════════════════════════════════

export function ApiKeysPage() {
  const [keys, setKeys] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<any[]>('/admin/api-keys').then(setKeys).finally(() => setLoading(false))
  }, [])

  const services = ['semrush', 'anthropic', 'openai', 'google', 'mistral', 'serpapi', 'copyscape']

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">API Key Vault</h1>
      <p className="text-sm text-surface-500 mb-4">
        Keys are AES-256 encrypted at rest. Only masked values are shown.
      </p>
      <div className="card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-surface-200 dark:border-surface-800">
              <th className="text-left p-3 font-medium text-surface-500">Service</th>
              <th className="text-left p-3 font-medium text-surface-500">Key</th>
              <th className="text-left p-3 font-medium text-surface-500">Status</th>
              <th className="text-left p-3 font-medium text-surface-500">Last Rotated</th>
              <th className="text-right p-3 font-medium text-surface-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {services.map((svc) => {
              const key = keys.find((k) => k.service === svc)
              return (
                <tr key={svc} className="border-b border-surface-100 dark:border-surface-800/50">
                  <td className="p-3 font-medium capitalize">{svc}</td>
                  <td className="p-3 font-mono text-xs text-surface-500">{key?.masked_key || 'Not set'}</td>
                  <td className="p-3">
                    {key?.is_active
                      ? <span className="badge-success">Active</span>
                      : <span className="badge-error">{key ? 'Inactive' : 'Missing'}</span>
                    }
                  </td>
                  <td className="p-3 text-surface-500 text-xs">
                    {key?.last_rotated_at ? new Date(key.last_rotated_at).toLocaleString() : '—'}
                  </td>
                  <td className="p-3 text-right">
                    <button className="btn-ghost text-xs"><RotateCw className="w-3 h-3" /> Rotate</button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// JOB QUEUE
// ═══════════════════════════════════════════════

export function JobsPage() {
  const [jobs, setJobs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<any[]>('/admin/jobs').then(setJobs).finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Job Queue Monitor</h1>
        <button className="btn-secondary" onClick={() => window.location.reload()}>
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>
      <div className="card">
        {loading ? (
          <div className="p-8 text-center text-surface-500">Loading jobs...</div>
        ) : jobs.length === 0 ? (
          <div className="p-8 text-center text-surface-500">No jobs in queue.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-200 dark:border-surface-800">
                <th className="text-left p-3 font-medium text-surface-500">Target</th>
                <th className="text-left p-3 font-medium text-surface-500">Type</th>
                <th className="text-left p-3 font-medium text-surface-500">Status</th>
                <th className="text-left p-3 font-medium text-surface-500">Progress</th>
                <th className="text-right p-3 font-medium text-surface-500">Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j: any) => (
                <tr key={j.id} className="border-b border-surface-100 dark:border-surface-800/50">
                  <td className="p-3 font-medium">{j.target}</td>
                  <td className="p-3 text-surface-500">{j.type}</td>
                  <td className="p-3">
                    <span className={j.status === 'complete' ? 'badge-success' : j.status === 'failed' ? 'badge-error' : 'badge-warning'}>
                      {j.status}
                    </span>
                  </td>
                  <td className="p-3 text-surface-500">{j.progress}</td>
                  <td className="p-3 text-right space-x-1">
                    {j.status === 'failed' && <button className="btn-ghost text-xs">Retry</button>}
                    {['queued', 'crawling'].includes(j.status) && <button className="btn-ghost text-xs text-red-500">Kill</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// BILLING & USAGE
// ═══════════════════════════════════════════════

export function BillingPage() {
  const [usage, setUsage] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<any[]>('/admin/usage').then(setUsage).finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Billing & Usage</h1>
      <div className="card">
        {loading ? (
          <div className="p-8 text-center text-surface-500">Loading usage data...</div>
        ) : usage.length === 0 ? (
          <div className="p-8 text-center text-surface-500">No usage data yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-200 dark:border-surface-800">
                <th className="text-left p-3 font-medium text-surface-500">Service</th>
                <th className="text-right p-3 font-medium text-surface-500">API Calls</th>
                <th className="text-right p-3 font-medium text-surface-500">Tokens In</th>
                <th className="text-right p-3 font-medium text-surface-500">Tokens Out</th>
                <th className="text-right p-3 font-medium text-surface-500">Est. Cost</th>
              </tr>
            </thead>
            <tbody>
              {usage.map((u: any) => (
                <tr key={u.service} className="border-b border-surface-100 dark:border-surface-800/50">
                  <td className="p-3 font-medium capitalize">{u.service}</td>
                  <td className="p-3 text-right text-surface-500">{u.total_calls?.toLocaleString()}</td>
                  <td className="p-3 text-right text-surface-500">{u.total_tokens_in?.toLocaleString()}</td>
                  <td className="p-3 text-right text-surface-500">{u.total_tokens_out?.toLocaleString()}</td>
                  <td className="p-3 text-right font-medium">${u.total_cost?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// AUDIT LOG
// ═══════════════════════════════════════════════

export function AuditPage() {
  const [logs, setLogs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<any[]>('/admin/audit-log').then(setLogs).finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Audit Log</h1>
      <div className="card">
        {loading ? (
          <div className="p-8 text-center text-surface-500">Loading audit log...</div>
        ) : logs.length === 0 ? (
          <div className="p-8 text-center text-surface-500">No audit entries yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-200 dark:border-surface-800">
                <th className="text-left p-3 font-medium text-surface-500">Time</th>
                <th className="text-left p-3 font-medium text-surface-500">User</th>
                <th className="text-left p-3 font-medium text-surface-500">Action</th>
                <th className="text-left p-3 font-medium text-surface-500">Resource</th>
                <th className="text-left p-3 font-medium text-surface-500">IP</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l: any) => (
                <tr key={l.id} className="border-b border-surface-100 dark:border-surface-800/50">
                  <td className="p-3 text-xs text-surface-500 whitespace-nowrap">{new Date(l.created_at).toLocaleString()}</td>
                  <td className="p-3 text-surface-500">{l.user_email || 'System'}</td>
                  <td className="p-3 font-mono text-xs">{l.action}</td>
                  <td className="p-3 text-surface-500 text-xs">{l.resource_type || '—'}</td>
                  <td className="p-3 text-surface-500 text-xs">{l.ip_address || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// DATABASE MANAGEMENT
// ═══════════════════════════════════════════════

export function DatabasePage() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Database Management</h1>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
        <div className="card p-5">
          <h3 className="text-sm font-semibold mb-2">Manual Backup</h3>
          <p className="text-xs text-surface-500 mb-3">Trigger an immediate PostgreSQL dump.</p>
          <button className="btn-primary text-sm">Trigger Backup</button>
        </div>
        <div className="card p-5">
          <h3 className="text-sm font-semibold mb-2">Prune Stale Data</h3>
          <p className="text-xs text-surface-500 mb-3">Remove expired cache, old crawl data, and orphaned records.</p>
          <button className="btn-danger text-sm">Prune Data</button>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// SYSTEM SETTINGS
// ═══════════════════════════════════════════════

export function SettingsPage() {
  const [settings, setSettings] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<any[]>('/admin/system/settings').then(setSettings).finally(() => setLoading(false))
  }, [])

  const categories = [...new Set(settings.map((s) => s.category))].sort()

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">System Settings</h1>
      {loading ? (
        <div className="card p-8 text-center text-surface-500">Loading settings...</div>
      ) : (
        categories.map((cat) => (
          <div key={cat} className="card mb-4">
            <div className="px-4 py-3 border-b border-surface-200 dark:border-surface-800">
              <h2 className="text-sm font-semibold capitalize">{cat}</h2>
            </div>
            <table className="w-full text-sm">
              <tbody>
                {settings.filter((s) => s.category === cat).map((s) => (
                  <tr key={s.key} className="border-b border-surface-100 dark:border-surface-800/50">
                    <td className="p-3 font-mono text-xs w-1/3">{s.key}</td>
                    <td className="p-3">{JSON.stringify(s.value)}</td>
                    <td className="p-3 text-right">
                      <button className="btn-ghost text-xs">Edit</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))
      )}
    </div>
  )
}
