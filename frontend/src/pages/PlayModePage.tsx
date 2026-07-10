import { useNavigate } from 'react-router-dom'
import { ChevronLeft, Zap, Target, Pencil } from 'lucide-react'

export function PlayModePage() {
  const navigate = useNavigate()

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      <button
        className="flex items-center gap-1 text-sm mb-8"
        style={{ color: 'var(--text-muted)' }}
        onClick={() => navigate('/')}
      >
        <ChevronLeft size={14} /> Home
      </button>

      <div className="mb-8">
        <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>Single Player</div>
        <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Pick a mode to get started</div>
      </div>

      <div className="flex flex-col gap-4">
        {/* Fun Mode */}
        <button
          onClick={() => navigate('/fun')}
          className="card text-left p-6 cursor-pointer transition-all duration-200"
          onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
        >
          <div className="flex items-start gap-4">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--accent)' }}
            >
              <Zap size={20} />
            </div>
            <div>
              <div className="text-base font-semibold mb-1" style={{ color: 'var(--text)' }}>Fun Mode</div>
              <div className="text-sm" style={{ color: 'var(--text-muted)' }}>
                Pick a tournament, season, and team - then watch the season play out with optional squad tweaks.
              </div>
              <div className="mt-3 text-sm font-medium" style={{ color: 'var(--accent)' }}>
                Start →
              </div>
            </div>
          </div>
        </button>

        {/* Challenge Mode */}
        <button
          onClick={() => navigate('/challenge')}
          className="card text-left p-6 cursor-pointer transition-all duration-200"
          onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--score)'}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
        >
          <div className="flex items-start gap-4">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(245,158,11,0.1)', color: 'var(--score)' }}
            >
              <Target size={20} />
            </div>
            <div>
              <div className="text-base font-semibold mb-1" style={{ color: 'var(--text)' }}>Challenge Mode</div>
              <div className="text-sm" style={{ color: 'var(--text-muted)' }}>
                Take over an underdog team, trade in better players, and fight your way to the title.
              </div>
              <div className="mt-3 text-sm font-medium" style={{ color: 'var(--score)' }}>
                Accept challenge →
              </div>
            </div>
          </div>
        </button>

        {/* Custom Mode */}
        <button
          onClick={() => navigate('/custom')}
          className="card text-left p-6 cursor-pointer transition-all duration-200"
          onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = '#a855f7'}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
        >
          <div className="flex items-start gap-4">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}
            >
              <Pencil size={20} />
            </div>
            <div>
              <div className="text-base font-semibold mb-1" style={{ color: 'var(--text)' }}>Custom Mode</div>
              <div className="text-sm" style={{ color: 'var(--text-muted)' }}>
                Draft your own XI from any player in the tournament pool, set your batting order, and simulate.
              </div>
              <div className="mt-3 text-sm font-medium" style={{ color: '#a855f7' }}>
                Build your squad →
              </div>
            </div>
          </div>
        </button>
      </div>
    </div>
  )
}
