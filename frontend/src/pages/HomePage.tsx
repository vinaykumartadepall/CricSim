import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Zap, Target, Clock, Trophy } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import type { SimSummary } from '@/types'

export function HomePage() {
  const navigate = useNavigate()
  const { clientId } = useAuth()
  const [recent, setRecent] = useState<SimSummary[]>([])

  useEffect(() => {
    api.listSimulations(clientId, 5)
      .then(data => setRecent(data))
      .catch(() => setRecent([]))
  }, [clientId])

  return (
    <div className="min-h-screen" style={{ background: 'var(--bg)' }}>
      {/* Hero */}
      <div className="flex flex-col items-center text-center px-6 pt-16 pb-12">
        <div className="mb-4 text-sm font-medium tracking-widest uppercase" style={{ color: 'var(--accent)' }}>
          Ball-by-Ball Cricket Simulation
        </div>
        <h1
          className="text-4xl md:text-5xl font-bold mb-4"
          style={{ color: 'var(--text)', letterSpacing: '-1px', lineHeight: 1.1 }}
        >
          Run Your Own<br />
          <span style={{ color: 'var(--accent)' }}>IPL Season</span>
        </h1>
        <p className="text-lg max-w-md" style={{ color: 'var(--text-muted)' }}>
          Simulate full tournaments with historical player data, realistic outcomes,
          and ball-by-ball precision.
        </p>
      </div>

      {/* Mode cards */}
      <div className="max-w-2xl mx-auto px-6 grid md:grid-cols-2 gap-4 pb-12">
        <button
          onClick={() => navigate('/fun')}
          className="card text-left p-6 cursor-pointer transition-all duration-200"
          onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
        >
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center mb-4"
            style={{ background: 'rgba(0,229,204,0.1)', color: 'var(--accent)' }}
          >
            <Zap size={20} />
          </div>
          <div className="text-lg font-semibold mb-1" style={{ color: 'var(--text)' }}>Fun Mode</div>
          <div className="text-sm" style={{ color: 'var(--text-muted)' }}>
            Pick a team and watch it play out.
          </div>
          <div className="mt-4 text-sm font-medium" style={{ color: 'var(--accent)' }}>
            Pick your team →
          </div>
        </button>

        <button
          onClick={() => navigate('/challenge')}
          className="card text-left p-6 cursor-pointer transition-all duration-200"
          onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--score)'}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
        >
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center mb-4"
            style={{ background: 'rgba(245,158,11,0.1)', color: 'var(--score)' }}
          >
            <Target size={20} />
          </div>
          <div className="text-lg font-semibold mb-1" style={{ color: 'var(--text)' }}>Challenge Mode</div>
          <div className="text-sm" style={{ color: 'var(--text-muted)' }}>
            Take over an underdog. Build your squad. Win.
          </div>
          <div className="mt-4 text-sm font-medium" style={{ color: 'var(--score)' }}>
            Accept the challenge →
          </div>
        </button>
      </div>

      {/* Recent simulations */}
      <div className="max-w-2xl mx-auto px-6 pb-16">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Clock size={14} style={{ color: 'var(--text-muted)' }} />
            <span className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>
              Recent simulations
            </span>
          </div>
          {recent.length > 0 && (
            <button
              className="text-xs font-medium"
              style={{ color: 'var(--accent)' }}
              onClick={() => navigate('/simulations')}
            >
              View all →
            </button>
          )}
        </div>

        {recent.length === 0 ? (
          <div className="card p-6 text-center text-sm" style={{ color: 'var(--text-dim)' }}>
            No simulations yet. Run your first one above.
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {recent.map(sim => (
              <button
                key={sim.sim_id}
                onClick={() => navigate(`/results/${sim.sim_id}`)}
                className="card-sm px-4 py-3 cursor-pointer w-full text-left transition-all"
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    {/* Title line */}
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

                    {/* Meta line */}
                    <div className="flex items-center gap-2 mt-1 flex-wrap">
                      {sim.user_team_name ? (
                        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                          {sim.user_team_name}
                        </span>
                      ) : sim.mode && (
                        <span
                          className="text-xs px-1.5 py-px rounded font-medium"
                          style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-dim)' }}
                        >
                          Spectator
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

                    {/* Winner line */}
                    {sim.winner_name && (
                      <div className="flex items-center gap-1 mt-1">
                        <Trophy size={11} style={{ color: 'var(--score)' }} />
                        <span className="text-xs" style={{ color: 'var(--score)' }}>
                          {sim.winner_name}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Status chip */}
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
                    {sim.status.charAt(0).toUpperCase() + sim.status.slice(1)}
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
