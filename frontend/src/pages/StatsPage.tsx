import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, Trophy } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { Spinner } from '@/components/ui/Spinner'
import type { SimSummary } from '@/types'

// ── Tournament stats hook ─────────────────────────────────────────────────────

function useComputedStats(sims: SimSummary[]) {
  return useMemo(() => {
    const tournaments = sims.filter(s => s.simulation_type === 'tournament' && s.status === 'completed')
    const withPlacement = tournaments.filter(s => s.user_team_placement)

    const placements: Record<string, number> = {}
    for (const s of withPlacement) {
      const p = s.user_team_placement!
      placements[p] = (placements[p] ?? 0) + 1
    }

    const titles   = placements['Winner'] ?? 0
    const runnerUp = placements['Runner-up'] ?? 0
    const playoffs = placements['Playoffs'] ?? 0
    const group    = placements['Group stage'] ?? 0
    const winRate  = withPlacement.length > 0 ? Math.round((titles / withPlacement.length) * 100) : 0

    const byMode: Record<string, { seasons: number; titles: number }> = {}
    for (const s of tournaments) {
      const m = s.mode ?? 'fun'
      if (!byMode[m]) byMode[m] = { seasons: 0, titles: 0 }
      byMode[m].seasons++
      if (s.user_team_placement === 'Winner') byMode[m].titles++
    }

    const wins = withPlacement.filter(s => s.user_team_placement === 'Winner')

    return { titles, runnerUp, playoffs, group, winRate, byMode, wins, total: tournaments.length, withPlacement: withPlacement.length }
  }, [sims])
}

// ── Shared components ─────────────────────────────────────────────────────────

function StatCard({ label, value, accent }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <div className="card-sm px-4 py-4">
      <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 500, marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color: accent ? 'var(--score)' : 'var(--text)', letterSpacing: '-0.5px', lineHeight: 1 }}>
        {value}
      </div>
    </div>
  )
}

function PlacementBar({ label, count, total, color }: { label: string; count: number; total: number; color: string }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{ fontSize: 12, color: 'var(--text-muted)', width: 84, flexShrink: 0 }}>{label}</span>
      <div style={{ flex: 1, height: 6, background: 'var(--surface-2)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.4s ease' }} />
      </div>
      <span style={{ fontSize: 12, color: 'var(--text-muted)', width: 24, textAlign: 'right', flexShrink: 0 }}>{count}</span>
    </div>
  )
}

const TITLES_PREVIEW = 5

function TitlesWonCard({ wins, navigate, hideSeasons }: { wins: SimSummary[]; navigate: (path: string) => void; hideSeasons?: boolean }) {
  const preview = wins.slice(0, TITLES_PREVIEW)
  return (
    <div className="card p-5">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>🏆 Titles Won</div>
        {wins.length > TITLES_PREVIEW && (
          <button
            onClick={() => navigate('/stats/titles')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--text-muted)' }}
          >
            View all →
          </button>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {preview.map(sim => (
          <button
            key={sim.sim_id}
            onClick={() => navigate(`/results/${sim.sim_id}`)}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              background: 'none', border: 'none', cursor: 'pointer', padding: '4px 0',
              borderBottom: '1px solid var(--border)', width: '100%', textAlign: 'left',
            }}
          >
            <div>
              <div style={{ fontSize: 13, color: 'var(--text)', fontWeight: 500 }}>
                {sim.tournament_name ?? 'Tournament'}{!hideSeasons && sim.season ? ` ${sim.season}` : ''}
              </div>
              {sim.user_team_name && (
                <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 1 }}>{sim.user_team_name}</div>
              )}
            </div>
            <span style={{ fontSize: 11, color: 'var(--text-dim)', flexShrink: 0, marginLeft: 12 }}>
              {new Date(sim.created_at).toLocaleDateString()}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

const MODE_LABELS: Record<string, string> = {
  fun: 'Fun', challenge: 'Challenge', custom: 'Custom', multiplayer: 'Multiplayer',
}

// ── Tournament stats panel (single player + multiplayer tournaments) ───────────

function TournamentStatsPanel({ sims, showByMode, hideSeasons, navigate }: {
  sims: SimSummary[]
  showByMode: boolean
  hideSeasons?: boolean
  navigate: (path: string) => void
}) {
  const s = useComputedStats(sims)

  if (s.total === 0) {
    return (
      <div className="card p-10 text-center">
        <div style={{ fontSize: 36, marginBottom: 12 }}>🏏</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>No seasons played yet</div>
        <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Complete a tournament to see your stats here.</div>
      </div>
    )
  }

  return (
    <>
      <div className="grid grid-cols-4 gap-3 mb-5">
        <StatCard label="Seasons"   value={s.total} />
        <StatCard label="Titles"    value={s.titles} accent={s.titles > 0} />
        <StatCard label="Win Rate"  value={s.withPlacement > 0 ? `${s.winRate}%` : '—'} />
        <StatCard label="Runner-up" value={s.runnerUp} />
      </div>

      <div className="card p-5 mb-4">
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 14 }}>Placement Breakdown</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <PlacementBar label="🏆 Winner"     count={s.titles}   total={s.withPlacement} color="var(--score)" />
          <PlacementBar label="🥈 Runner-up"  count={s.runnerUp} total={s.withPlacement} color="#C0C0C0" />
          <PlacementBar label="🏅 Playoffs"   count={s.playoffs} total={s.withPlacement} color="#CD7F32" />
          <PlacementBar label="   Group exit" count={s.group}    total={s.withPlacement} color="var(--border)" />
        </div>
      </div>

      {showByMode && Object.keys(s.byMode).length > 1 && (
        <div className="card p-5 mb-4">
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>By Mode</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {Object.entries(s.byMode).map(([mode, data]) => (
              <div key={mode} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{MODE_LABELS[mode] ?? mode}</span>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>{data.seasons} season{data.seasons !== 1 ? 's' : ''}</span>
                  {data.titles > 0 && (
                    <span style={{ fontSize: 12, color: 'var(--score)', display: 'flex', alignItems: 'center', gap: 3 }}>
                      <Trophy size={10} /> {data.titles}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {s.wins.length > 0 && (
        <TitlesWonCard wins={s.wins} navigate={navigate} hideSeasons={hideSeasons} />
      )}
    </>
  )
}

// ── 1v1 stats panel ───────────────────────────────────────────────────────────

function OneVOnePanel({ sims, navigate }: { sims: SimSummary[]; navigate: (path: string) => void }) {
  const completed = useMemo(
    () => sims.filter(s => s.simulation_type === 'match' && s.status === 'completed'),
    [sims]
  )
  const withResult = completed.filter(s => s.user_team_placement)
  const wins   = withResult.filter(s => s.user_team_placement === 'Winner').length
  const losses = withResult.filter(s => s.user_team_placement === 'Loser').length
  const winRate = withResult.length > 0 ? Math.round((wins / withResult.length) * 100) : 0
  const recent  = completed.slice(0, 10)

  if (completed.length === 0) {
    return (
      <div className="card p-10 text-center">
        <div style={{ fontSize: 36, marginBottom: 12 }}>🏏</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>No 1v1 matches yet</div>
        <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Challenge another player to see your record here.</div>
      </div>
    )
  }

  return (
    <>
      <div className="grid grid-cols-4 gap-3 mb-5">
        <StatCard label="Matches"  value={completed.length} />
        <StatCard label="Wins"     value={wins}   accent={wins > 0} />
        <StatCard label="Win Rate" value={withResult.length > 0 ? `${winRate}%` : '—'} />
        <StatCard label="Losses"   value={losses} />
      </div>

      {withResult.length > 0 && (
        <div className="card p-5 mb-4">
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 14 }}>Record</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <PlacementBar label="🏆 Won"  count={wins}   total={withResult.length} color="var(--win)" />
            <PlacementBar label="   Lost" count={losses} total={withResult.length} color="var(--loss)" />
          </div>
        </div>
      )}

      {recent.length > 0 && (
        <div className="card p-5">
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>Recent Matches</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {recent.map(sim => {
              const won = sim.user_team_placement === 'Winner'
              const lost = sim.user_team_placement === 'Loser'
              return (
                <button
                  key={sim.sim_id}
                  onClick={() => navigate(`/results/${sim.sim_id}`)}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    background: 'none', border: 'none', cursor: 'pointer', padding: '4px 0',
                    borderBottom: '1px solid var(--border)', width: '100%', textAlign: 'left',
                  }}
                >
                  <div>
                    <div style={{ fontSize: 13, color: 'var(--text)', fontWeight: 500 }}>
                      {sim.tournament_name ?? 'Match'}
                    </div>
                    {sim.user_team_name && (
                      <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 1 }}>{sim.user_team_name}</div>
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0, marginLeft: 12 }}>
                    {sim.user_team_placement && (
                      <span style={{
                        fontSize: 11, fontWeight: 600, paddingRight: 6,
                        color: won ? 'var(--win)' : lost ? 'var(--loss)' : 'var(--text-dim)',
                      }}>
                        {won ? 'W' : lost ? 'L' : sim.user_team_placement}
                      </span>
                    )}
                    <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      {new Date(sim.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

type StatsTab = 'singleplayer' | 'multiplayer' | '1v1'

const TABS: { id: StatsTab; label: string }[] = [
  { id: 'singleplayer', label: 'Single Player' },
  { id: 'multiplayer',  label: 'Multiplayer'   },
  { id: '1v1',          label: '1v1'           },
]

export function StatsPage() {
  const navigate = useNavigate()
  const { clientId } = useAuth()
  const [sims, setSims] = useState<SimSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<StatsTab>('singleplayer')

  useEffect(() => {
    api.listSimulations(clientId, 200)
      .then(data => setSims(data))
      .catch(() => setSims([]))
      .finally(() => setLoading(false))
  }, [clientId])

  const spSims = useMemo(() => sims.filter(s => s.mode !== 'multiplayer'), [sims])
  const mpTournamentSims = useMemo(
    () => sims.filter(s => s.mode === 'multiplayer' && s.simulation_type === 'tournament'),
    [sims]
  )
  const oneVOneSims = useMemo(
    () => sims.filter(s => s.mode === 'multiplayer' && s.simulation_type === 'match'),
    [sims]
  )

  if (loading) {
    return <div className="flex justify-center py-24"><Spinner /></div>
  }

  const totalAll = sims.filter(s => s.status === 'completed').length

  if (totalAll === 0) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-12">
        <button className="flex items-center gap-1 text-sm mb-8" style={{ color: 'var(--text-muted)' }} onClick={() => navigate('/')}>
          <ChevronLeft size={14} /> Home
        </button>
        <div className="card p-10 text-center">
          <div style={{ fontSize: 36, marginBottom: 12 }}>🏏</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>No seasons played yet</div>
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Complete a tournament to see your stats here.</div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      <button className="flex items-center gap-1 text-sm mb-6" style={{ color: 'var(--text-muted)' }} onClick={() => navigate('/')}>
        <ChevronLeft size={14} /> Home
      </button>

      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', marginBottom: 2 }}>My Stats</div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 24, borderBottom: '1px solid var(--border)' }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: '8px 16px', background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 13, fontWeight: tab === t.id ? 600 : 400,
              color: tab === t.id ? 'var(--accent)' : 'var(--text-muted)',
              borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
              marginBottom: -1, transition: 'color 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'singleplayer' && (
        <TournamentStatsPanel sims={spSims} showByMode navigate={navigate} />
      )}
      {tab === 'multiplayer' && (
        <TournamentStatsPanel sims={mpTournamentSims} showByMode={false} hideSeasons navigate={navigate} />
      )}
      {tab === '1v1' && (
        <OneVOnePanel sims={oneVOneSims} navigate={navigate} />
      )}
    </div>
  )
}
