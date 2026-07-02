import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { PreviewNav } from './PreviewNav'
import type { SimSummary } from '@/types'

function usePreviewTheme(theme: string) {
  useEffect(() => {
    const html = document.documentElement
    const prev = html.getAttribute('data-theme') ?? 'night-stadium'
    html.setAttribute('data-theme', theme)
    return () => html.setAttribute('data-theme', prev)
  }, [theme])
}

// ── Broadsheet ────────────────────────────────────────────────────────────────
// Warm off-white · cricket-red accent · Playfair Display
// Aesthetic: The Athletic meets Wisden almanac — premium sports editorial.
// No cards. Sections divided by ruled lines. Typography IS the design.
// Light mode deliberately chosen to break from every other cricket app.

const SERIF = "'Playfair Display', 'Georgia', serif"
const SANS  = "system-ui, -apple-system, sans-serif"

function Rule() {
  return <div style={{ height: 1, background: 'var(--border)', margin: '0' }} />
}

function SimRow({ sim }: { sim: SimSummary }) {
  const navigate = useNavigate()
  const title = sim.tournament_name
    ? (sim.season ? `${sim.tournament_name} ${sim.season}` : sim.tournament_name)
    : 'Simulation'

  const chipLabel = sim.status === 'failed' ? 'Failed'
    : sim.status !== 'completed' ? (sim.status === 'running' ? 'Running…' : 'Pending')
    : sim.user_team_placement ?? (sim.winner_name ? `🏆 ${sim.winner_name}` : null)

  const isWinner = sim.user_team_placement === 'Winner'

  return (
    <button
      onClick={() => navigate(`/results/${sim.sim_id}`)}
      style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        width: '100%', background: 'none', border: 'none', cursor: 'pointer',
        padding: '14px 0', gap: 16, textAlign: 'left',
        borderBottom: '1px solid var(--border)',
      }}
      onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'rgba(196,30,58,0.03)'}
      onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'none'}
    >
      <div style={{ minWidth: 0 }}>
        <span style={{
          fontFamily: SERIF, fontSize: 15, fontWeight: 600, color: 'var(--text)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block',
        }}>
          {title}
        </span>
        {sim.user_team_name && (
          <span style={{ fontSize: 12, color: 'var(--text-dim)', display: 'block', marginTop: 2 }}>
            {sim.user_team_name}
          </span>
        )}
      </div>
      <div style={{ flexShrink: 0, textAlign: 'right' }}>
        {chipLabel && (
          <div style={{
            fontSize: 12, fontWeight: 600,
            color: isWinner ? 'var(--accent)' : 'var(--text-dim)',
          }}>
            {chipLabel}
          </div>
        )}
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
          {new Date(sim.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}
        </div>
      </div>
    </button>
  )
}

export function BroadsheetPage() {
  const navigate = useNavigate()
  const { clientId } = useAuth()
  const [sims, setSims] = useState<SimSummary[]>([])
  const [total, setTotal] = useState<number | null>(null)

  usePreviewTheme('broadsheet')

  useEffect(() => {
    api.listSimulations(clientId, 5).then(setSims).catch(() => {})
    api.getTotalSimulations().then(d => setTotal(d.total)).catch(() => {})
  }, [clientId])

  const seasonList = useMemo(() => {
    const ip = sims.filter(s => s.status !== 'completed' && s.status !== 'failed')
    const done = sims.filter(s => s.status === 'completed' || s.status === 'failed')
    return [...ip, ...done].slice(0, 5)
  }, [sims])

  const today = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: SANS }}>
      <PreviewNav current="broadsheet" />

      {/* ── Newspaper masthead ── */}
      <div style={{
        borderBottom: '3px solid var(--text)',
        padding: '16px 32px 14px',
        display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
        background: 'var(--bg)',
      }}>
        <div>
          <div style={{
            fontFamily: SERIF, fontSize: 28, fontWeight: 700,
            color: 'var(--text)', letterSpacing: '0.04em', lineHeight: 1,
          }}>
            CRICSIM
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-dim)', letterSpacing: '0.12em', marginTop: 3 }}>
            CRICKET SIMULATION
          </div>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', textAlign: 'right', fontStyle: 'italic' }}>
          {today}
        </div>
      </div>

      <div style={{ maxWidth: 680, margin: '0 auto', padding: '0 32px' }}>

        {/* ── Hero ── */}
        <div style={{ padding: '48px 0 0' }}>
          <h1 style={{
            fontFamily: SERIF,
            fontSize: 'clamp(46px, 9vw, 72px)',
            fontWeight: 700,
            color: 'var(--text)',
            lineHeight: 1.05,
            margin: '0 0 20px',
            letterSpacing: '-0.5px',
          }}>
            What If You Won?
          </h1>

          {/* ── Counter woven into subheadline ── */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 0, flexWrap: 'wrap', marginBottom: 36 }}>
            <span style={{ fontSize: 16, color: 'var(--text-muted)', fontFamily: SANS, lineHeight: 1.7 }}>
              Pick a side, build your XI, and compete. Join
            </span>
            {total !== null && (
              <span style={{
                fontFamily: SERIF, fontSize: 28, fontWeight: 700,
                color: 'var(--accent)', margin: '0 6px',
                lineHeight: 1,
              }}>
                {total.toLocaleString()}
              </span>
            )}
            <span style={{ fontSize: 16, color: 'var(--text-muted)', fontFamily: SANS, lineHeight: 1.7 }}>
              tournaments already simulated.
            </span>
          </div>

          <Rule />
        </div>

        {/* ── Play sections — text rows, not cards ── */}
        <div>
          {/* Single Player */}
          <button
            onClick={() => navigate('/play')}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              width: '100%', background: 'none', border: 'none', cursor: 'pointer',
              padding: '24px 0', borderBottom: '1px solid var(--border)', textAlign: 'left',
            }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'rgba(196,30,58,0.02)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'none'}
          >
            <div>
              <div style={{ fontFamily: SERIF, fontSize: 24, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>
                Single Player
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                Choose a tournament, pick your team, build your XI. Fun, Challenge, or Custom modes.
              </div>
            </div>
            <div style={{
              fontFamily: SERIF, fontSize: 28, color: 'var(--accent)',
              marginLeft: 20, flexShrink: 0, lineHeight: 1,
            }}>
              →
            </div>
          </button>

          {/* Multiplayer */}
          <button
            onClick={() => navigate('/multiplayer')}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              width: '100%', background: 'none', border: 'none', cursor: 'pointer',
              padding: '24px 0', borderBottom: '1px solid var(--border)', textAlign: 'left',
            }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'rgba(196,30,58,0.02)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'none'}
          >
            <div>
              <div style={{ fontFamily: SERIF, fontSize: 24, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>
                Multiplayer Draft
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                Create a room, draft your XI with friends, and let the best team win.
              </div>
            </div>
            <div style={{
              fontFamily: SERIF, fontSize: 28, color: 'var(--text-dim)',
              marginLeft: 20, flexShrink: 0, lineHeight: 1,
            }}>
              →
            </div>
          </button>
        </div>

        {/* ── Your Seasons ── */}
        {seasonList.length > 0 && (
          <div style={{ paddingTop: 32, marginBottom: 48 }}>
            <div style={{
              display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
              marginBottom: 16,
            }}>
              <span style={{
                fontFamily: SERIF, fontSize: 16, fontWeight: 600, color: 'var(--text)',
                letterSpacing: '0.01em',
              }}>
                Your Seasons
              </span>
              <button
                onClick={() => navigate('/simulations')}
                style={{
                  fontSize: 12, color: 'var(--accent)',
                  background: 'none', border: 'none', cursor: 'pointer',
                  fontFamily: SANS, textDecoration: 'underline',
                }}
              >
                View all
              </button>
            </div>
            <Rule />
            <div>
              {seasonList.map(sim => <SimRow key={sim.sim_id} sim={sim} />)}
            </div>
          </div>
        )}

        {/* ── Attribution ── */}
        <div style={{
          paddingBottom: 48, paddingTop: 24,
          borderTop: '1px solid var(--border)',
          fontFamily: SANS, fontSize: 11, color: 'var(--text-dim)',
          fontStyle: 'italic',
        }}>
          Match data sourced from{' '}
          <a href="https://cricsheet.org" target="_blank" rel="noopener noreferrer"
            style={{ color: 'var(--text-muted)' }}>
            Cricsheet.org
          </a>
          , licensed under the Open Data Commons Attribution License.
        </div>
      </div>
    </div>
  )
}
