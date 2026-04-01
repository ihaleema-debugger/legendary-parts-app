import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import { Plus, ExternalLink } from 'lucide-react'

// ═══════════════════════════════════════════════
// PROJECTS
// ═══════════════════════════════════════════════

export function ProjectsPage() {
  const [projects, setProjects] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<any[]>('/projects').then(setProjects).finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Projects</h1>
        <button className="btn-primary"><Plus className="w-4 h-4" /> New Project</button>
      </div>
      <div className="card">
        {loading ? (
          <div className="p-8 text-center text-surface-500">Loading projects...</div>
        ) : projects.length === 0 ? (
          <div className="p-8 text-center text-surface-500">
            No projects yet. Create your first project to start analysing competitors.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-200 dark:border-surface-800">
                <th className="text-left p-3 font-medium text-surface-500">Name</th>
                <th className="text-left p-3 font-medium text-surface-500">Competitors</th>
                <th className="text-left p-3 font-medium text-surface-500">Status</th>
                <th className="text-left p-3 font-medium text-surface-500">Created</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className="border-b border-surface-100 dark:border-surface-800/50 hover:bg-surface-50 dark:hover:bg-surface-800/30">
                  <td className="p-3 font-medium">{p.name}</td>
                  <td className="p-3 text-surface-500">{p.competitor_domains?.length || 0} domains</td>
                  <td className="p-3"><span className="badge-success">{p.status}</span></td>
                  <td className="p-3 text-surface-500">{new Date(p.created_at).toLocaleDateString()}</td>
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
// CRAWL MANAGER
// ═══════════════════════════════════════════════

export function CrawlsPage() {
  const [crawls, setCrawls] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<any[]>('/crawls').then(setCrawls).finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Crawl Manager</h1>
        <button className="btn-primary"><Plus className="w-4 h-4" /> New Crawl</button>
      </div>
      <div className="card">
        {loading ? (
          <div className="p-8 text-center text-surface-500">Loading crawl jobs...</div>
        ) : crawls.length === 0 ? (
          <div className="p-8 text-center text-surface-500">
            No crawl jobs yet. Start a crawl from a project to begin extracting competitor keywords.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-200 dark:border-surface-800">
                <th className="text-left p-3 font-medium text-surface-500">Domain</th>
                <th className="text-left p-3 font-medium text-surface-500">Type</th>
                <th className="text-left p-3 font-medium text-surface-500">Status</th>
                <th className="text-left p-3 font-medium text-surface-500">Progress</th>
              </tr>
            </thead>
            <tbody>
              {crawls.map((c) => (
                <tr key={c.id} className="border-b border-surface-100 dark:border-surface-800/50">
                  <td className="p-3 font-medium">{c.target_domain}</td>
                  <td className="p-3 text-surface-500">{c.job_type}</td>
                  <td className="p-3">
                    <span className={c.status === 'complete' ? 'badge-success' : c.status === 'failed' ? 'badge-error' : 'badge-warning'}>
                      {c.status}
                    </span>
                  </td>
                  <td className="p-3 text-surface-500">{c.pages_crawled}/{c.pages_total || '?'}</td>
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
// KEYWORD EXPLORER
// ═══════════════════════════════════════════════

export function KeywordsPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Keyword Explorer</h1>
      <div className="card p-6">
        <p className="text-surface-500">
          Browse and filter all extracted keywords. Use the filters to narrow by category (primary, service, problem, local),
          source domain, volume range, and keyword difficulty range.
        </p>
        <div className="mt-4">
          <input type="text" className="input max-w-md" placeholder="Search keywords..." />
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// GAP REPORT
// ═══════════════════════════════════════════════

export function GapsPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Gap Report</h1>
      <div className="card p-6">
        <p className="text-surface-500">
          Gap analysis results will appear here after running an analysis on a project.
          Each gap keyword shows its opportunity score, Semrush metrics, and a suggested content type.
          Use the "Create Brief" button to push a gap directly into Inkwell.
        </p>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// SITE INDEX
// ═══════════════════════════════════════════════

export function SiteIndexPage() {
  const [status, setStatus] = useState<any>(null)

  useEffect(() => {
    api.get('/index/status').then(setStatus).catch(console.error)
  }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Site Index</h1>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="card p-5">
          <p className="text-sm text-surface-500 mb-1">Indexed Keywords</p>
          <p className="text-2xl font-bold">{status?.total_keywords?.toLocaleString() || '0'}</p>
        </div>
        <div className="card p-5">
          <p className="text-sm text-surface-500 mb-1">Indexed Pages</p>
          <p className="text-2xl font-bold">{status?.total_pages?.toLocaleString() || '0'}</p>
        </div>
        <div className="card p-5">
          <p className="text-sm text-surface-500 mb-1">Index Status</p>
          <p className="text-2xl font-bold">{status?.status || '—'}</p>
        </div>
      </div>
      <button className="btn-primary">Refresh Index</button>
    </div>
  )
}
