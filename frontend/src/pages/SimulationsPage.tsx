import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, Trophy } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { Spinner } from '@/components/ui/Spinner'
import type { SimSummary } from '@/types'

export function SimulationsPage() {
  const navigate = useNavigate()
  const { clientId } = useAuth()
  const [sims, setSims] = useState<SimSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listSimulations(clientId, 100)
      .then(data => setSims(data))
      .catch(() => setSims([]))
      .finally(() => setLoading(false))
  }, [clientId])

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <button
        className="flex items-center gap-1 text-sm mb-6"
        style={{ color: 'var(--text-muted)' }}
        onClick={() => navigate('/')}
      >
        <ChevronLeft size={14} /> Back to home
      </button>

      <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>All simulations</div>
      <div className="text-sm mb-6" style={{ color: 'var(--text-muted)' }}>Your full simulation history</div>

      {loading ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : sims.length === 0 ? (
        <div className="card p-8 text-center">
          <div className="text-3xl mb-3">🏏</div>
          <div className="text-sm" style={{ color: 'var(--text-dim)' }}>
            No simulations yet. Run your first one from the home page.
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {sims.map(sim => (
            <SimCard key={sim.sim_id} sim={sim} onClick={() => navigate(`/results/${sim.sim_id}`)} />
          ))}
        </div>
      )}
    </div>
  )
}

function SimCard({ sim, onClick }: { sim: SimSummary; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="card-sm px-4 py-3 cursor-pointer w-full text-left transition-all"
      onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
      onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium truncate" style={{ color: 'var(--text)' }}>
              {sim.tournament_name
                ? `${sim.tournament_name}${sim.season ? ` ${sim.season}` : ''}`
                : 'Tournament simulation'}
            </span>
            {sim.mode && (
              <span
                className="text-xs px-2 py-0.5 rounded-full font-medium shrink-0"
                style={{
                  background: sim.mode === 'challenge' ? 'rgba(245,158,11,0.12)' : 'rgba(0,229,204,0.1)',
                  color: sim.mode === 'challenge' ? 'var(--score)' : 'var(--accent)',
                }}
              >
                {sim.mode === 'challenge' ? 'Challenge' : 'Fun'}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2 mt-1 flex-wrap">
            {sim.user_team_name && (
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                {sim.user_team_name}
              </span>
            )}
            {sim.user_team_placement && (
              <span
                className="text-xs px-1.5 py-px rounded font-medium"
                style={{
                  background: sim.user_team_placement === 'Winner'
                    ? 'rgba(245,158,11,0.15)'
                    : sim.user_team_placement === 'Runner-up'
                    ? 'rgba(0,229,204,0.1)'
                    : 'rgba(255,255,255,0.05)',
                  color: sim.user_team_placement === 'Winner'
                    ? 'var(--score)'
                    : sim.user_team_placement === 'Runner-up'
                    ? 'var(--accent)'
                    : 'var(--text-dim)',
                }}
              >
                {sim.user_team_placement}
              </span>
            )}
            {sim.swap_count != null && sim.swap_count > 0 && (
              <span className="text-xs" style={{ color: 'var(--text-dim)' }}>
                {sim.swap_count} swap{sim.swap_count !== 1 ? 's' : ''}
              </span>
            )}
            <span className="text-xs" style={{ color: 'var(--text-dim)' }}>
              {new Date(sim.created_at).toLocaleDateString()}
            </span>
          </div>

          {sim.winner_name && (
            <div className="flex items-center gap-1 mt-1">
              <Trophy size={11} style={{ color: 'var(--score)' }} />
              <span className="text-xs" style={{ color: 'var(--score)' }}>{sim.winner_name}</span>
            </div>
          )}
        </div>

        <span
          className="text-xs px-2 py-0.5 rounded-full shrink-0 self-start"
          style={{
            background: sim.status === 'completed'
              ? 'rgba(34,197,94,0.15)'
              : sim.status === 'failed'
              ? 'rgba(239,68,68,0.12)'
              : 'rgba(245,158,11,0.12)',
            color: sim.status === 'completed'
              ? 'var(--win)'
              : sim.status === 'failed'
              ? 'var(--loss)'
              : 'var(--score)',
          }}
        >
          {sim.status}
        </span>
      </div>
    </button>
  )
}
