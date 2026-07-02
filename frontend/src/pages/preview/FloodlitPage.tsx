import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { SimCard } from '@/components/SimCard'
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

// ── Floodlit ──────────────────────────────────────────────────────────────────
// Near-black · amber-yellow accent · Barlow Condensed
// Aesthetic: a cricket ground under stadium floodlights — everything in darkness
// except what the lights touch. The counter is the source of light on screen.

const COND = "'Barlow Condensed', 'Impact', 'Arial Narrow', sans-serif"
const BODY = "'Barlow', system-ui, sans-serif"

export function FloodlitPage() {
  const navigate = useNavigate()
  const { clientId } = useAuth()
  const [sims, setSims] = useState<SimSummary[]>([])
  const [total, setTotal] = useState<number | null>(null)

  usePreviewTheme('floodlit')

  useEffect(() => {
    api.listSimulations(clientId, 5).then(setSims).catch(() => {})
    api.getTotalSimulations().then(d => setTotal(d.total)).catch(() => {})
  }, [clientId])

  const seasonList = useMemo(() => {
    const ip = sims.filter(s => s.status !== 'completed' && s.status !== 'failed')
    const done = sims.filter(s => s.status === 'completed' || s.status === 'failed')
    return [...ip, ...done].slice(0, 5)
  }, [sims])

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: BODY }}>
      <PreviewNav current="floodlit" />

      {/* ── Masthead ── */}
      <div style={{
        borderBottom: '1px solid var(--border)',
        padding: '0 28px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        height: 52,
      }}>
        <span style={{
          fontFamily: COND, fontSize: 20, fontWeight: 700,
          color: 'var(--accent)', letterSpacing: '0.12em', textTransform: 'uppercase',
        }}>
          ◈ CRICSIM
        </span>
        <div style={{ display: 'flex', gap: 20 }}>
          {['Home', 'Stats', 'Seasons'].map(l => (
            <span key={l} style={{
              fontFamily: COND, fontSize: 13, fontWeight: 600,
              textTransform: 'uppercase', letterSpacing: '0.1em',
              color: 'var(--text-dim)', cursor: 'pointer',
            }}>
              {l}
            </span>
          ))}
        </div>
      </div>

      <div style={{ maxWidth: 660, margin: '0 auto', padding: '0 24px' }}>

        {/* ── Hero headline ── */}
        <div style={{ paddingTop: 52 }}>
          <h1 style={{
            fontFamily: COND,
            fontSize: 'clamp(56px, 13vw, 96px)',
            fontWeight: 800,
            textTransform: 'uppercase',
            letterSpacing: '0.02em',
            color: 'var(--text)',
            margin: 0,
            lineHeight: 0.92,
          }}>
            What If<br />
            You <span style={{ color: 'var(--accent)' }}>Won?</span>
          </h1>
        </div>

        {/* ── Amber rule ── */}
        <div style={{
          height: 2, background: 'var(--accent)',
          margin: '32px 0',
          boxShadow: '0 0 12px 2px rgba(255,183,0,0.3)',
        }} />

        {/* ── Counter — the source of light ── */}
        <div style={{ textAlign: 'center', padding: '16px 0 44px' }}>
          {/* LIVE badge */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            marginBottom: 20,
          }}>
            <span style={{
              width: 7, height: 7, borderRadius: '50%',
              background: 'var(--accent)',
              display: 'inline-block',
              boxShadow: '0 0 8px 3px rgba(255,183,0,0.6)',
            }} />
            <span style={{
              fontFamily: COND, fontSize: 13, fontWeight: 700,
              textTransform: 'uppercase', letterSpacing: '0.22em',
              color: 'var(--accent)',
            }}>
              Live
            </span>
          </div>

          {/* Big number */}
          {total !== null ? (
            <div style={{
              fontFamily: COND,
              fontSize: 'clamp(80px, 22vw, 128px)',
              fontWeight: 800,
              letterSpacing: '-2px',
              lineHeight: 1,
              color: 'var(--accent)',
              textShadow: '0 0 80px rgba(255,183,0,0.45), 0 0 160px rgba(255,183,0,0.2)',
            }}>
              {total.toLocaleString()}
            </div>
          ) : (
            <div style={{
              fontFamily: COND, fontSize: 'clamp(80px, 22vw, 128px)', fontWeight: 800,
              color: 'var(--border)', lineHeight: 1,
            }}>
              —
            </div>
          )}

          <div style={{
            fontFamily: COND, fontSize: 16, fontWeight: 600,
            textTransform: 'uppercase', letterSpacing: '0.22em',
            color: 'var(--text-dim)', marginTop: 12,
          }}>
            Tournaments Simulated
          </div>
        </div>

        {/* ── Thin rule ── */}
        <div style={{ height: 1, background: 'var(--border)', marginBottom: 32 }} />

        {/* ── Actions — full-width, border style ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 44 }}>
          <button
            onClick={() => navigate('/play')}
            style={{
              fontFamily: COND, fontWeight: 700,
              fontSize: 22, textTransform: 'uppercase', letterSpacing: '0.08em',
              padding: '22px 28px',
              background: 'none',
              color: 'var(--accent)',
              border: '1px solid var(--accent)',
              borderRadius: 2,
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              transition: 'background 0.15s, box-shadow 0.15s',
            }}
            onMouseEnter={e => {
              const el = e.currentTarget as HTMLElement
              el.style.background = 'rgba(255,183,0,0.07)'
              el.style.boxShadow = '0 0 24px rgba(255,183,0,0.15)'
            }}
            onMouseLeave={e => {
              const el = e.currentTarget as HTMLElement
              el.style.background = 'none'
              el.style.boxShadow = 'none'
            }}
          >
            <span>Play Now</span>
            <span style={{ fontSize: 26, lineHeight: 1, opacity: 0.7 }}>→</span>
          </button>

          <button
            onClick={() => navigate('/multiplayer')}
            style={{
              fontFamily: COND, fontWeight: 600,
              fontSize: 18, textTransform: 'uppercase', letterSpacing: '0.08em',
              padding: '18px 28px',
              background: 'none',
              color: 'var(--text-muted)',
              border: '1px solid var(--border)',
              borderRadius: 2,
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              transition: 'border-color 0.15s, color 0.15s',
            }}
            onMouseEnter={e => {
              const el = e.currentTarget as HTMLElement
              el.style.borderColor = 'var(--text-dim)'
              el.style.color = 'var(--text)'
            }}
            onMouseLeave={e => {
              const el = e.currentTarget as HTMLElement
              el.style.borderColor = 'var(--border)'
              el.style.color = 'var(--text-muted)'
            }}
          >
            <span>Multiplayer Draft</span>
            <span style={{ fontSize: 20, opacity: 0.4 }}>→</span>
          </button>
        </div>

        {/* ── Your Seasons ── */}
        {seasonList.length > 0 && (
          <div style={{ paddingBottom: 16, marginBottom: 48 }}>
            <div style={{ height: 1, background: 'var(--border)', marginBottom: 24 }} />
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              marginBottom: 16,
            }}>
              <span style={{
                fontFamily: COND, fontSize: 13, fontWeight: 700,
                textTransform: 'uppercase', letterSpacing: '0.18em', color: 'var(--text-dim)',
              }}>
                Your Seasons
              </span>
              <button
                onClick={() => navigate('/simulations')}
                style={{
                  fontFamily: COND, fontSize: 12, fontWeight: 600,
                  textTransform: 'uppercase', letterSpacing: '0.12em',
                  color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer',
                }}
              >
                All Seasons →
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {seasonList.map(sim => <SimCard key={sim.sim_id} sim={sim} />)}
            </div>
          </div>
        )}

        {/* ── Attribution ── */}
        <div style={{
          paddingBottom: 40, paddingTop: 20,
          borderTop: '1px solid var(--border)',
          fontFamily: BODY, fontSize: 11,
          color: 'var(--text-dim)', textAlign: 'center',
          letterSpacing: '0.04em', textTransform: 'uppercase',
        }}>
          Data ·{' '}
          <a href="https://cricsheet.org" target="_blank" rel="noopener noreferrer"
            style={{ color: 'var(--accent)', textDecoration: 'none' }}>
            Cricsheet.org
          </a>
          {' '}· ODC Attribution License
        </div>
      </div>
    </div>
  )
}
