import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import {
  FolderSearch, Bug, FileText, BookCheck, BarChart3, DollarSign
} from 'lucide-react'

interface DashboardStats {
  active_projects: number
  running_crawls: number
  active_briefs: number
  published_content: number
  total_gap_keywords: number
  monthly_cost_estimate: number
}

const statCards = [
  { key: 'active_projects', label: 'Active Projects', icon: FolderSearch, color: 'text-brand-500' },
  { key: 'running_crawls', label: 'Running Crawls', icon: Bug, color: 'text-amber-500' },
  { key: 'active_briefs', label: 'Active Briefs', icon: FileText, color: 'text-violet-500' },
  { key: 'published_content', label: 'Published Content', icon: BookCheck, color: 'text-emerald-500' },
  { key: 'total_gap_keywords', label: 'Gap Keywords', icon: BarChart3, color: 'text-sky-500' },
  { key: 'monthly_cost_estimate', label: 'Monthly Cost', icon: DollarSign, color: 'text-orange-500', prefix: '$' },
] as const

export function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<DashboardStats>('/dashboard/stats')
      .then(setStats)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Dashboard</h1>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {statCards.map((card) => (
          <div key={card.key} className="card p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm text-surface-500">{card.label}</span>
              <card.icon className={`w-5 h-5 ${card.color}`} />
            </div>
            <p className="text-2xl font-bold text-surface-800 dark:text-surface-100">
              {loading
                ? '—'
                : `${card.prefix || ''}${
                    stats
                      ? typeof stats[card.key] === 'number'
                        ? card.key === 'monthly_cost_estimate'
                          ? stats[card.key].toFixed(2)
                          : stats[card.key].toLocaleString()
                        : '0'
                      : '0'
                  }`
              }
            </p>
          </div>
        ))}
      </div>

      {/* Placeholder sections */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
        <div className="card p-6">
          <h2 className="text-lg font-semibold mb-4">Recent Crawls</h2>
          <p className="text-sm text-surface-500">Crawl activity will appear here once you start a project.</p>
        </div>
        <div className="card p-6">
          <h2 className="text-lg font-semibold mb-4">Recent Content</h2>
          <p className="text-sm text-surface-500">Content briefs and published articles will appear here.</p>
        </div>
      </div>
    </div>
  )
}
