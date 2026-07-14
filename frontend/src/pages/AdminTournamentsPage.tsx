import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Search } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { FormatBadge } from '@/components/ui/FormatBadge'
import { ADMIN_SANS, ADMIN_SERIF, AccessDenied, adminInputStyle, isAuthError } from '@/components/admin/AdminUI'
import type { AdminTournamentSummary } from '@/types'

export function AdminTournamentsPage() {
  const navigate = useNavigate()
  const [q, setQ]           = useState('')
  const [rows, setRows]     = useState<AdminTournamentSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [denied, setDenied] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true)
      api.getAdminTournaments(q.trim() || undefined)
        .then(setRows)
        .catch(err => {
          if (isAuthError(err)) setDenied(true)
          else console.warn('Failed to load seeded tournaments', err)
        })
        .finally(() => setLoading(false))
    }, q ? 300 : 0)
    return () => clearTimeout(t)
  }, [q])

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: ADMIN_SANS }}>
      <div style={{ maxWidth: 720, margin: '0 auto', padding: '48px 24px' }}>
        <button
          className="flex items-center gap-1 text-sm mb-6"
          style={{ color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
          onClick={() => navigate('/site-admin')}
        >
          <ChevronLeft size={14} /> Admin Settings
        </button>

        <div style={{ fontFamily: ADMIN_SERIF, fontSize: 22, color: 'var(--text)', fontWeight: 400, marginBottom: 4 }}>
          Tournament Editor
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 20 }}>
          Edit any seeded tournament's metadata, venues, schedule, teams and squads.
          Changes apply to new simulations only.
        </div>

        {denied ? <AccessDenied /> : (
          <>
            <div style={{ position: 'relative', marginBottom: 12 }}>
              <Search size={14} style={{ position: 'absolute', left: 10, top: 10, color: 'var(--text-dim)' }} />
              <input
                value={q}
                onChange={e => setQ(e.target.value)}
                placeholder="Search tournaments…"
                style={{ ...adminInputStyle, paddingLeft: 30 }}
              />
            </div>

            {loading ? (
              <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Loading…</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {rows.map(t => (
                  <button
                    key={t.tournament_id}
                    onClick={() => navigate(`/site-admin/tournaments/${t.tournament_id}`)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, textAlign: 'left',
                      padding: '10px 14px', borderRadius: 10, cursor: 'pointer',
                      background: 'var(--surface)', border: '1px solid var(--border)',
                    }}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 13.5, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 8 }}>
                        {t.name} <span style={{ color: 'var(--text-muted)' }}>{t.season}</span>
                        <FormatBadge format={t.format} />
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
                        {t.team_count} teams{t.gender ? ` · ${t.gender}` : ''}
                      </div>
                    </div>
                    <ChevronRight size={14} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
                  </button>
                ))}
                {rows.length === 0 && (
                  <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>No seeded tournaments match.</div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
