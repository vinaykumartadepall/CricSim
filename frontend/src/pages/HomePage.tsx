import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Clock, Gamepad2, Users } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { SimCard } from '@/components/SimCard'
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
      <div className="flex flex-col items-center text-center px-6 pt-10 pb-10">
        <h1 className="text-3xl md:text-4xl font-bold mb-3" style={{ color: 'var(--text)', letterSpacing: '-0.5px', lineHeight: 1.15 }}>
          What If <span style={{ color: 'var(--accent)' }}>You Won?</span>
        </h1>
        <p className="text-sm max-w-sm" style={{ color: 'var(--text-muted)', lineHeight: 1.6 }}>
          Run ball by ball simulations across modes
        </p>
      </div>

      {/* Mode cards */}
      <div className="max-w-2xl mx-auto px-6 pb-10">
        <div className="grid md:grid-cols-2 gap-4">

          {/* Single Player */}
          <button
            onClick={() => navigate('/play')}
            className="card text-left p-5 cursor-pointer transition-all duration-200"
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
          >
            <div className="flex items-center gap-3 mb-2">
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--accent)' }}
              >
                <Gamepad2 size={18} />
              </div>
              <div className="text-base font-semibold" style={{ color: 'var(--text)' }}>Single Player</div>
            </div>
            <div className="text-sm mb-3" style={{ color: 'var(--text-muted)' }}>
              Pick a team, trade players, simulate the season.
            </div>
            <div className="text-sm font-medium" style={{ color: 'var(--accent)' }}>
              Choose a mode →
            </div>
          </button>

          {/* Multiplayer */}
          <button
            onClick={() => navigate('/multiplayer')}
            className="card text-left p-5 cursor-pointer transition-all duration-200"
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = '#a855f7'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
          >
            <div className="flex items-center gap-3 mb-2">
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}
              >
                <Users size={18} />
              </div>
              <div className="text-base font-semibold" style={{ color: 'var(--text)' }}>Multiplayer Draft</div>
            </div>
            <div className="text-sm mb-3" style={{ color: 'var(--text-muted)' }}>
              Draft your XI against friends. Best team wins.
            </div>
            <div className="text-sm font-medium" style={{ color: '#a855f7' }}>
              Start a room →
            </div>
          </button>

        </div>
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
            {recent.map(sim => <SimCard key={sim.sim_id} sim={sim} />)}
          </div>
        )}
      </div>
    </div>
  )
}
