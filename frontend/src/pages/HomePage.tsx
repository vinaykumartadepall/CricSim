import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { User, Users } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { SimCard } from '@/components/SimCard'
import type { SimSummary } from '@/types'
import heroImg from '@/assets/hero-landscape1.png'

const SERIF = "'DM Serif Display', Georgia, 'Times New Roman', serif"
const SANS  = "'DM Sans', system-ui, sans-serif"

function SectionHeader({ label, right, centered }: { label: string; right?: React.ReactNode; centered?: boolean }) {
  if (centered) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <div style={{ flex: 1, height: '0.5px', background: 'var(--border)' }} />
        <span style={{
          fontFamily: SANS, fontSize: 11, fontWeight: 700,
          textTransform: 'uppercase', letterSpacing: '0.14em',
          color: 'var(--accent)', whiteSpace: 'nowrap',
        }}>
          {label}
        </span>
        <div style={{ flex: 1, height: '0.5px', background: 'var(--border)' }} />
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
      <span style={{
        fontFamily: SANS, fontSize: 11, fontWeight: 700,
        textTransform: 'uppercase', letterSpacing: '0.14em',
        color: 'var(--accent)', whiteSpace: 'nowrap',
      }}>
        {label}
      </span>
      <div style={{ flex: 1, height: '0.5px', background: 'var(--border)' }} />
      {right}
    </div>
  )
}

export function HomePage() {
  const navigate = useNavigate()
  const { clientId } = useAuth()
  const [sims, setSims]   = useState<SimSummary[]>([])
  const [total, setTotal] = useState<number | null>(null)

  useEffect(() => {
    api.listSimulations(clientId, 50).then(setSims).catch(() => setSims([]))
  }, [clientId])

  useEffect(() => {
    api.getTotalSimulations().then(d => setTotal(d.total)).catch(() => {})
  }, [])

  const seasonList = useMemo(() => {
    const inProgress = sims.filter(s => s.status !== 'completed' && s.status !== 'failed')
    const done       = sims.filter(s => s.status === 'completed' || s.status === 'failed')
    return [...inProgress, ...done].slice(0, 5)
  }, [sims])

  const hasInProgress = seasonList.some(s => s.status !== 'completed' && s.status !== 'failed')

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: SANS }}>

      <style>{`
        @media (min-width: 768px) {
          .cricsim-hero          { min-height: 420px !important; }
          .cricsim-hero-content  { padding: 64px 80px 48px !important; max-width: 960px !important; }
          .cricsim-counter       { margin-top: -28px !important; }
          .cricsim-main          { max-width: 760px !important; padding: 0 48px !important; }
        }
      `}</style>

      {/* ── Hero — edge-to-edge, image bleeds 28px below container ── */}
      <div className="cricsim-hero" style={{ position: 'relative', minHeight: 300 }}>
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, bottom: -28,
          backgroundImage: `url(${heroImg})`,
          backgroundSize: 'cover',
          backgroundPosition: '66% 30%',
        }} />
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, bottom: -28,
          background: 'linear-gradient(to right, rgba(8,8,8,1) 0%, rgba(8,8,8,0.95) 28%, rgba(8,8,8,0.65) 50%, rgba(8,8,8,0.1) 70%, transparent 100%)',
        }} />
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, bottom: -28,
          background: 'linear-gradient(to bottom, rgba(8,8,8,0.3) 0%, transparent 18%, transparent 55%, rgba(8,8,8,0.8) 82%, var(--bg) 100%)',
        }} />
        <div className="cricsim-hero-content" style={{ position: 'relative', padding: '50px 28px 28px', maxWidth: 680, margin: '0 auto' }}>
          <h1 style={{
            fontFamily: SERIF,
            fontSize: 'clamp(44px, 10vw, 68px)',
            fontWeight: 400,
            color: 'var(--text)',
            lineHeight: 1.02,
            letterSpacing: '-1px',
            margin: '0 0 16px',
            textShadow: '0 2px 24px rgba(0,0,0,0.7)',
          }}>
            What If<br />
            You <em style={{ color: 'var(--accent)', fontStyle: 'italic' }}>Won?</em>
          </h1>
          <p style={{
            fontFamily: SANS, fontSize: 13, fontWeight: 600,
            color: 'var(--text-muted)',
            lineHeight: 1.65, margin: 0, maxWidth: 300,
            textShadow: '0 1px 12px rgba(0,0,0,0.9)',
          }}>
            Relive past tournaments, reshape your squad<br />
            and discover whether your team has what it takes to lift the trophy.
          </p>
        </div>
      </div>

      {/* ── Rest of content ── */}
      <div className="cricsim-main" style={{ maxWidth: 680, margin: '0 auto', padding: '0 24px' }}>

        {/* ── Counter — pulled up to overlap the hero's bottom ── */}
        {total !== null && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 24,
            padding: '14px 20px',
            background: 'var(--surface)',
            borderRadius: 6,
            border: '0.5px solid var(--border)',
            borderLeft: '3px solid var(--accent)',
            marginBottom: 32,
            marginTop: -56,
            position: 'relative', zIndex: 1,
          }}>
            <div style={{
              fontFamily: SERIF, fontSize: 52, fontWeight: 400,
              color: 'var(--accent)', lineHeight: 1, letterSpacing: '-1.5px', flexShrink: 0,
            }}>
              {total.toLocaleString()}
            </div>
            <div style={{ width: 1, height: 44, background: 'var(--border)', flexShrink: 0 }} />
            <div>
              <div style={{
                fontFamily: SANS, fontSize: 10, fontWeight: 700,
                textTransform: 'uppercase', letterSpacing: '0.14em',
                color: 'var(--text-dim)', marginBottom: 3,
              }}>
                Total Tournaments Simulated across all game modes
              </div>
              <div style={{ fontFamily: SANS, fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                
              </div>
            </div>
          </div>
        )}

        {/* ── Choose a Mode ── */}
        <SectionHeader label="Choose a Mode" centered />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 40 }}>

          {/* Single Player */}
          <button
            onClick={() => navigate('/play')}
            style={{
              background: 'none',
              border: '0.5px solid var(--accent)', borderRadius: 8,
              padding: '20px 18px', cursor: 'pointer', textAlign: 'left',
              fontFamily: SANS, display: 'flex', flexDirection: 'column',
              transition: 'background 0.2s',
            }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'var(--accent-glow)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'none'}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 3 }}>
              <User size={15} style={{ color: 'var(--accent)', flexShrink: 0 }} />
              <span style={{ fontFamily: SERIF, fontSize: 19, fontWeight: 400, color: 'var(--accent)' }}>
                Single Player
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 14 }}>
              Fun · Challenge · Custom
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.55, marginBottom: 18, flex: 1 }}>
              Build your team, make trades, and win the title.
            </div>
            <div style={{
              background: 'var(--accent-dim)', color: 'var(--bg)',
              borderRadius: 4, padding: '9px 0', textAlign: 'center',
              fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
            }}>
              PLAY NOW →
            </div>
          </button>

          {/* Multiplayer */}
          <button
            onClick={() => navigate('/multiplayer')}
            style={{
              background: 'none',
              border: '0.5px solid var(--accent)', borderRadius: 8,
              padding: '20px 18px', cursor: 'pointer', textAlign: 'left',
              fontFamily: SANS, display: 'flex', flexDirection: 'column',
              transition: 'background 0.2s',
            }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'var(--accent-glow)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'none'}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 3 }}>
              <Users size={15} style={{ color: 'var(--accent)', flexShrink: 0 }} />
              <span style={{ fontFamily: SERIF, fontSize: 19, fontWeight: 400, color: 'var(--accent)' }}>
                Multi Player
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 14 }}>
              Draft with friends
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.55, marginBottom: 18, flex: 1 }}>
              Create a room, invite your friends, and compete together.
            </div>
            <div style={{
              background: 'var(--accent-dim)', color: 'var(--bg)',
              borderRadius: 4, padding: '9px 0', textAlign: 'center',
              fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
            }}>
              PLAY TOGETHER →
            </div>
          </button>
        </div>

        {/* ── Your Recent Simulations ── */}
        {seasonList.length > 0 && (
          <div style={{ marginBottom: 40 }}>
            <SectionHeader
              label={hasInProgress ? 'Continue Playing' : 'Your Recent Simulations'}
              right={
                <button
                  onClick={() => navigate('/simulations')}
                  style={{ fontFamily: SANS, fontSize: 12, color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}
                >
                  View all →
                </button>
              }
            />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {seasonList.map(sim => <SimCard key={sim.sim_id} sim={sim} />)}
            </div>
          </div>
        )}

        {seasonList.length === 0 && (
          <div style={{
            border: '0.5px solid var(--border)', borderRadius: 8,
            padding: '48px 32px', textAlign: 'center', marginBottom: 64,
            boxShadow: '0 10px 40px rgba(0,0,0,0.45)',
          }}>
            <div style={{ fontFamily: SERIF, fontSize: 32, color: 'var(--text-dim)', marginBottom: 12 }}>🏏</div>
            <div style={{ fontFamily: SERIF, fontSize: 18, color: 'var(--text)', marginBottom: 6, fontWeight: 400 }}>
              No simulations yet
            </div>
            <div style={{ fontFamily: SANS, fontSize: 13, color: 'var(--text-dim)' }}>
              Start your first simulation above and see how far you can go.
            </div>
          </div>
        )}

        {/* ── Attribution ── */}
        <div style={{
          paddingBottom: 40, paddingTop: 20,
          borderTop: '0.5px solid var(--border)',
          fontFamily: SANS, fontSize: 11, color: 'var(--text-dim)', textAlign: 'center',
        }}>
          Match data from{' '}
          <a href="https://cricsheet.org" target="_blank" rel="noopener noreferrer"
            style={{ color: 'var(--accent)', textDecoration: 'none', opacity: 0.8 }}>
            Cricsheet.org
          </a>
          , licensed under the Open Data Commons Attribution License.
        </div>

      </div>
    </div>
  )
}
