import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { Spinner } from '@/components/ui/Spinner'
import type { SimSummary } from '@/types'

const PAGE_SIZE = 25

export function TitlesPage() {
  const navigate  = useNavigate()
  const { clientId } = useAuth()
  const [sims, setSims]       = useState<SimSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [visible, setVisible] = useState(PAGE_SIZE)

  useEffect(() => {
    api.listSimulations(clientId, 500, 0)
      .then(data => setSims(data))
      .catch(() => setSims([]))
      .finally(() => setLoading(false))
  }, [clientId])

  const wins = useMemo(
    () => sims.filter(s => s.simulation_type === 'tournament' && s.status === 'completed' && s.user_team_placement === 'Winner'),
    [sims]
  )

  const shown   = wins.slice(0, visible)
  const hasMore = visible < wins.length

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <button
        className="flex items-center gap-1 text-sm mb-6"
        style={{ color: 'var(--text-muted)' }}
        onClick={() => navigate('/stats')}
      >
        <ChevronLeft size={14} /> Back
      </button>

      <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>🏆 Titles Won</div>
      {!loading && (
        <div className="text-sm mb-6" style={{ color: 'var(--text-muted)' }}>
          {wins.length} title{wins.length !== 1 ? 's' : ''} in total
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : wins.length === 0 ? (
        <div className="card p-8 text-center">
          <div className="text-3xl mb-3">🏏</div>
          <div className="text-sm" style={{ color: 'var(--text-dim)' }}>
            No titles yet. Win a tournament to see them here.
          </div>
        </div>
      ) : (
        <>
          <div className="card">
            {shown.map((sim, i) => (
              <button
                key={sim.sim_id}
                onClick={() => navigate(`/results/${sim.sim_id}`)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  width: '100%', textAlign: 'left', background: 'none', border: 'none',
                  cursor: 'pointer', padding: '14px 20px',
                  borderBottom: i < shown.length - 1 ? '1px solid var(--border)' : 'none',
                  transition: 'background 0.12s',
                }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.03)'}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'none'}
              >
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>
                    {sim.tournament_name ?? 'Tournament'}
                    {sim.season && sim.mode !== 'multiplayer' ? ` ${sim.season}` : ''}
                  </div>
                  {sim.user_team_name && (
                    <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 2 }}>{sim.user_team_name}</div>
                  )}
                </div>
                <span style={{ fontSize: 12, color: 'var(--text-dim)', flexShrink: 0, marginLeft: 16 }}>
                  {new Date(sim.created_at).toLocaleDateString()}
                </span>
              </button>
            ))}
          </div>

          {hasMore && (
            <div className="flex justify-center mt-6">
              <button
                onClick={() => setVisible(v => v + PAGE_SIZE)}
                className="btn-outline px-6 py-2.5 text-sm"
              >
                Load more
              </button>
            </div>
          )}

          {!hasMore && wins.length > PAGE_SIZE && (
            <div className="text-center mt-6 text-xs" style={{ color: 'var(--text-dim)' }}>
              All {wins.length} titles loaded
            </div>
          )}
        </>
      )}
    </div>
  )
}
