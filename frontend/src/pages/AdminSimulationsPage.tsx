import { useEffect, useState } from 'react'
import { ChevronLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { FormatBadge } from '@/components/ui/FormatBadge'
import type { AdminSimRow } from '@/types'

const SERIF = "'DM Serif Display', Georgia, 'Times New Roman', serif"
const SANS  = "'DM Sans', system-ui, sans-serif"
const PAGE_SIZE = 50

function formatCreated(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function formatDuration(created: string, completed?: string | null): string | null {
  if (!completed) return null
  const secs = Math.round((new Date(completed).getTime() - new Date(created).getTime()) / 1000)
  if (secs < 0) return null
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m ${secs % 60}s`
}

function statusColor(status: string): string {
  if (status === 'completed') return 'var(--win)'
  if (status === 'failed') return 'var(--loss)'
  return 'var(--score)'
}

const TH: React.CSSProperties = {
  textAlign: 'left', padding: '8px 10px', fontSize: 11, fontWeight: 600,
  color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em',
  borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
}

const TD: React.CSSProperties = {
  padding: '10px', fontSize: 12.5, verticalAlign: 'top',
  borderBottom: '1px solid var(--border)',
}

export function AdminSimulationsPage() {
  const navigate = useNavigate()
  const [sims, setSims]       = useState<AdminSimRow[]>([])
  const [total, setTotal]     = useState(0)
  const [loading, setLoading] = useState(true)
  const [denied, setDenied]   = useState(false)

  async function load(offset: number) {
    setLoading(true)
    try {
      const res = await api.getAdminSimulations(PAGE_SIZE, offset)
      setSims(prev => (offset === 0 ? res.simulations : [...prev, ...res.simulations]))
      setTotal(res.total)
    } catch (err) {
      const msg = String(err instanceof Error ? err.message : err)
      if (msg.startsWith('401') || msg.startsWith('403') || msg === 'Forbidden') setDenied(true)
      else console.warn('Failed to load admin simulations list', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load(0)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function simLink(s: AdminSimRow): string {
    return s.simulation_type === 'match' && s.match_id
      ? `/results/${s.sim_id}/matches/${s.match_id}`
      : `/results/${s.sim_id}`
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: SANS }}>
      <div style={{ maxWidth: 1040, margin: '0 auto', padding: '48px 24px' }}>
        <button
          className="flex items-center gap-1 text-sm mb-6"
          style={{ color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
          onClick={() => navigate('/site-admin')}
        >
          <ChevronLeft size={14} /> Admin Settings
        </button>

        <div style={{ fontFamily: SERIF, fontSize: 22, color: 'var(--text)', fontWeight: 400, marginBottom: 4 }}>
          All Simulations
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 24 }}>
          Every user's simulations across the whole server, newest first, failed runs included{total ? ` - ${total} total` : ''}.
        </div>

        {denied ? (
          <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.6 }}>
            Admin access required. Sign in with the admin account, then reload this page.
          </div>
        ) : sims.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
            {loading ? 'Loading…' : 'No simulations yet.'}
          </div>
        ) : (
          <>
            <div style={{
              overflowX: 'auto', borderRadius: 10,
              background: 'var(--surface)', border: '1px solid var(--border)',
            }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 860 }}>
                <thead>
                  <tr>
                    <th style={TH}>Created</th>
                    <th style={TH}>Simulation</th>
                    <th style={TH}>User</th>
                    <th style={TH}>Result</th>
                    <th style={TH}>Status</th>
                    <th style={TH}>Sim ID</th>
                  </tr>
                </thead>
                <tbody>
                  {sims.map(s => {
                    const duration = formatDuration(s.created_at, s.completed_at)
                    return (
                      <tr
                        key={s.sim_id}
                        onClick={() => navigate(simLink(s))}
                        style={{ cursor: 'pointer' }}
                      >
                        <td style={{ ...TD, whiteSpace: 'nowrap' }}>
                          <div style={{ color: 'var(--text)' }}>{formatCreated(s.created_at)}</div>
                          {duration && <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 2 }}>took {duration}</div>}
                        </td>
                        <td style={TD}>
                          <div style={{ color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                            {s.tournament_name ?? s.simulation_type}
                            {s.season && <span style={{ color: 'var(--text-muted)' }}>{s.season}</span>}
                            <FormatBadge format={s.match_format} />
                          </div>
                          <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 2 }}>
                            {s.simulation_type}{s.mode ? ` · ${s.mode}` : ''}
                          </div>
                        </td>
                        <td style={TD}>
                          <div style={{ color: 'var(--text)' }} title={s.client_id ?? undefined}>
                            {s.display_name ?? (s.client_id ? (
                              <span style={{ fontFamily: 'monospace' }}>{s.client_id.slice(0, 8)}</span>
                            ) : 'anon')}
                          </div>
                          <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 2 }}>
                            {s.user_team_name ?? '-'}
                            {s.swap_count ? ` · ${s.swap_count} trade${s.swap_count !== 1 ? 's' : ''}` : ''}
                          </div>
                        </td>
                        <td style={TD}>
                          <div style={{ color: 'var(--text)' }}>{s.winner_name ?? '-'}</div>
                          {s.user_team_placement && (
                            <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 2 }}>
                              user: {s.user_team_placement}
                            </div>
                          )}
                        </td>
                        <td style={TD}>
                          <div style={{ color: statusColor(s.status), fontWeight: 600 }}>{s.status}</div>
                          {s.error_message && (
                            <div style={{ color: 'var(--loss)', fontSize: 11, marginTop: 2, maxWidth: 220, whiteSpace: 'normal' }}>
                              {s.error_message}
                            </div>
                          )}
                        </td>
                        <td style={{ ...TD, fontFamily: 'monospace', fontSize: 11, color: 'var(--text-dim)' }}>
                          <span title={s.sim_id}>{s.sim_id.slice(0, 8)}</span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {sims.length < total && (
              <button
                disabled={loading}
                onClick={() => load(sims.length)}
                style={{
                  marginTop: 14, padding: '7px 16px', borderRadius: 7,
                  background: 'var(--surface-2)', border: '1px solid var(--border)',
                  color: 'var(--text-muted)', fontSize: 12,
                  cursor: loading ? 'default' : 'pointer',
                }}
              >
                {loading ? 'Loading…' : `Load more (${sims.length}/${total})`}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
