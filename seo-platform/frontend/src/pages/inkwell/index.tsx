import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import { Plus, FileText, PenTool } from 'lucide-react'

// ═══════════════════════════════════════════════
// BRIEFS
// ═══════════════════════════════════════════════

export function BriefsPage() {
  const [briefs, setBriefs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<any[]>('/briefs').then(setBriefs).finally(() => setLoading(false))
  }, [])

  const statusColor = (s: string) => {
    switch (s) {
      case 'published': return 'badge-success'
      case 'writing': case 'researching': return 'badge-warning'
      case 'review': return 'badge-info'
      default: return 'badge bg-surface-200 text-surface-600 dark:bg-surface-700 dark:text-surface-300'
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Content Briefs</h1>
        <button className="btn-primary"><Plus className="w-4 h-4" /> New Brief</button>
      </div>
      <div className="card">
        {loading ? (
          <div className="p-8 text-center text-surface-500">Loading briefs...</div>
        ) : briefs.length === 0 ? (
          <div className="p-8 text-center text-surface-500">
            No briefs yet. Create a brief to start writing SEO-optimised content, or push a gap keyword from KeyGap.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-200 dark:border-surface-800">
                <th className="text-left p-3 font-medium text-surface-500">Title</th>
                <th className="text-left p-3 font-medium text-surface-500">Primary Keyword</th>
                <th className="text-left p-3 font-medium text-surface-500">Model</th>
                <th className="text-left p-3 font-medium text-surface-500">Words</th>
                <th className="text-left p-3 font-medium text-surface-500">Status</th>
              </tr>
            </thead>
            <tbody>
              {briefs.map((b) => (
                <tr key={b.id} className="border-b border-surface-100 dark:border-surface-800/50 hover:bg-surface-50 dark:hover:bg-surface-800/30 cursor-pointer">
                  <td className="p-3 font-medium">{b.title}</td>
                  <td className="p-3 text-surface-500">{b.primary_keyword}</td>
                  <td className="p-3 text-surface-500 font-mono text-xs">{b.llm_model}</td>
                  <td className="p-3 text-surface-500">{b.target_word_count?.toLocaleString()}</td>
                  <td className="p-3"><span className={statusColor(b.status)}>{b.status}</span></td>
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
// CONTENT WORKSPACE (Editor)
// ═══════════════════════════════════════════════

export function EditorPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Content Workspace</h1>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Editor area */}
        <div className="lg:col-span-2 card p-6 min-h-[500px]">
          <div className="flex items-center gap-2 mb-4 pb-4 border-b border-surface-200 dark:border-surface-800">
            <PenTool className="w-4 h-4 text-brand-500" />
            <span className="text-sm font-medium">TipTap Editor</span>
          </div>
          <div className="text-surface-400 text-sm">
            Select a brief from the Briefs page and start writing to see the editor here.
            Content will stream in real-time as the LLM generates each section.
          </div>
        </div>

        {/* Right sidebar panels */}
        <div className="space-y-4">
          <div className="card p-4">
            <h3 className="text-sm font-semibold mb-3">SEO Scorecard</h3>
            <p className="text-xs text-surface-500">Compliance checks will appear here after content is generated.</p>
          </div>
          <div className="card p-4">
            <h3 className="text-sm font-semibold mb-3">Research Notes</h3>
            <p className="text-xs text-surface-500">Sources and summaries from the research phase.</p>
          </div>
          <div className="card p-4">
            <h3 className="text-sm font-semibold mb-3">Version History</h3>
            <p className="text-xs text-surface-500">Section revision history with diff and revert.</p>
          </div>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// CONTENT LIBRARY
// ═══════════════════════════════════════════════

export function LibraryPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Content Library</h1>
      <div className="card p-6">
        <p className="text-surface-500">
          Archive of all generated content, searchable by keyword, date, status, and model used.
          Published content can be exported as HTML, Markdown, or Word document.
        </p>
      </div>
    </div>
  )
}
