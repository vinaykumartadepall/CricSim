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
    const prev = html.getAttribute('data-theme') ?? 'ember-amber'
    html.setAttribute('data-theme', theme)
    return () => html.setAttribute('data-theme', prev)
  }, [theme])
}

const SERIF = "'DM Serif Display', Georgia, 'Times New Roman', serif"
const SANS  = "'DM Sans', system-ui, sans-serif"

export function EmberPage() {
  const navigate = useNavigate()
  const { clientId } = useAuth()
  const [sims, setSims]   = useState<SimSummary[]>([])
  const [total, setTotal] = useState<number | null>(null)

  usePreviewTheme('ember-amber')

  useEffect(() => {
    api.listSimulations(clientId, 5).then(setSims).catch(() => {})
    api.getTotalSimulations().then(d => setTotal(d.total)).catch(() => {})
  }, [clientId])

  const seasonList = useMemo(() => {
    const ip   = sims.filter(s => s.status !== 'completed' && s.status !== 'failed')
    const done = sims.filter(s => s.status === 'completed' || s.status === 'failed')
    return [...ip, ...done].slice(0, 5)
  }, [sims])

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: SANS }}>
      <PreviewNav current="ember" />

      {/* Fake masthead for preview only */}
      <div style={{
        borderBottom: '1px solid var(--border)',
        padding: '0 32px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        height: 56,
      }}>
        <span style={{
          fontFamily: SERIF, fontSize: 22,
          color: 'var(--accent)', letterSpacing: '0.04em',
          textShadow: '0 0 24px var(--accent-glow)',
        }}>
          ◈ CRICSIM
        </span>
        <div style={{ display: 'flex', gap: 24 }}>
          {['Home', 'My Stats', 'All Seasons'].map(l => (
            <span key={l} style={{ fontFamily: SANS, fontSize: 13, color: 'var(--text-dim)', cursor: 'pointer' }}>
              {l}
            </span>
          ))}
        </div>
      </div>

      <div style={{ maxWidth: 680, margin: '0 auto', padding: '0 28px' }}>

        {/* ── Hero ── */}
        <div style={{ paddingTop: 60, paddingBottom: 48 }}>
          <h1 style={{
            fontFamily: SERIF,
            fontSize: 'clamp(48px, 10vw, 76px)',
            fontWeight: 400,
            color: 'var(--text)',
            lineHeight: 1.02,
            letterSpacing: '-1px',
            margin: '0 0 24px',
          }}>
            What If<br />
            You <em style={{ color: 'var(--accent)', fontStyle: 'italic', textShadow: '0 0 40px var(--accent-glow)' }}>Won?</em>
          </h1>

          <p style={{
            fontFamily: SANS, fontSize: 15, color: 'var(--text-muted)',
            lineHeight: 1.75, margin: 0, maxWidth: 400,
          }}>
            Pick a side, shape your squad, and run a full tournament —
            ball by ball, over by over.
          </p>
        </div>

        {/* ── Counter ── */}
        {total !== null && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 32,
            padding: '28px 32px',
            background: 'var(--surface)',
            borderRadius: 4,
            border: '1px solid var(--border)',
            borderLeft: '4px solid var(--accent)',
            marginBottom: 40,
            boxShadow: '-4px 0 20px var(--accent-glow)',
          }}>
            <div style={{
              fontFamily: SERIF,
              fontSize: 58,
              fontWeight: 400,
              color: 'var(--accent)',
              lineHeight: 1,
              letterSpacing: '-1.5px',
              flexShrink: 0,
              textShadow: '0 0 40px var(--accent-glow), 0 0 80px var(--accent-glow)',
            }}>
              {total.toLocaleString()}
            </div>

            <div style={{ width: 1, height: 52, background: 'var(--border)', flexShrink: 0 }} />

            <div>
              <div style={{
                fontFamily: SANS, fontSize: 11, fontWeight: 600,
                textTransform: 'uppercase', letterSpacing: '0.14em',
                color: 'var(--text-dim)', marginBottom: 6,
              }}>
                Tournaments Simulated
              </div>
              <div style={{ fontFamily: SANS, fontSize: 14, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                By the CRICSIM<br />community worldwide
              </div>
            </div>
          </div>
        )}

        {/* ── Play + Multiplayer ── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 52 }}>
          <button
            onClick={() => navigate('/play')}
            style={{
              background: 'var(--accent)',
              color: 'var(--bg)',
              border: 'none',
              borderRadius: 4,
              padding: '24px 26px',
              cursor: 'pointer',
              textAlign: 'left',
              fontFamily: SERIF,
              boxShadow: '0 0 32px var(--accent-glow)',
              transition: 'opacity 0.15s, box-shadow 0.2s',
            }}
            onMouseEnter={e => {
              const el = e.currentTarget as HTMLElement
              el.style.opacity = '0.9'
              el.style.boxShadow = '0 0 52px var(--accent-glow)'
            }}
            onMouseLeave={e => {
              const el = e.currentTarget as HTMLElement
              el.style.opacity = '1'
              el.style.boxShadow = '0 0 32px var(--accent-glow)'
            }}
          >
            <div style={{ fontSize: 22, fontWeight: 400, marginBottom: 6 }}>Single Player</div>
            <div style={{ fontSize: 12, fontFamily: SANS, opacity: 0.6, fontWeight: 500, letterSpacing: '0.02em' }}>
              Fun · Challenge · Custom
            </div>
          </button>

          <button
            onClick={() => navigate('/multiplayer')}
            style={{
              background: 'transparent',
              color: 'var(--text)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              padding: '24px 26px',
              cursor: 'pointer',
              textAlign: 'left',
              fontFamily: SERIF,
              transition: 'border-color 0.15s, color 0.15s',
            }}
            onMouseEnter={e => {
              const el = e.currentTarget as HTMLElement
              el.style.borderColor = 'var(--accent)'
              el.style.color = 'var(--accent)'
            }}
            onMouseLeave={e => {
              const el = e.currentTarget as HTMLElement
              el.style.borderColor = 'var(--border)'
              el.style.color = 'var(--text)'
            }}
          >
            <div style={{ fontSize: 22, fontWeight: 400, marginBottom: 6 }}>Multiplayer Draft</div>
            <div style={{ fontSize: 12, fontFamily: SANS, color: 'var(--text-dim)', fontWeight: 400 }}>
              Draft with friends
            </div>
          </button>
        </div>

        {/* ── Your Seasons ── */}
        {seasonList.length > 0 && (
          <div style={{ paddingBottom: 16, marginBottom: 40 }}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              borderBottom: '1px solid var(--border)',
              paddingBottom: 12, marginBottom: 18,
            }}>
              <span style={{
                fontFamily: SANS, fontSize: 11, fontWeight: 600,
                textTransform: 'uppercase', letterSpacing: '0.12em', color: 'var(--text-dim)',
              }}>
                Your Seasons
              </span>
              <button
                onClick={() => navigate('/simulations')}
                style={{ fontFamily: SANS, fontSize: 12, color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer' }}
              >
                View all →
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
