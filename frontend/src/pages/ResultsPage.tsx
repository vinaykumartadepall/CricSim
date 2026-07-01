import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { createPortal } from 'react-dom'
import { Trophy, TrendingUp, Swords, Star, RotateCcw, ChevronRight, X, Search } from 'lucide-react'
import { Spinner } from '@/components/ui/Spinner'
import { PlayoffBracket } from '@/components/PlayoffBracket'
import { api } from '@/api/client'
import { getClientId } from '@/api/clientId'
import type {
  TournamentResult, LeaderboardsDashboard,
  MatchItem,
} from '@/types'

type Tab = 'standings' | 'leaderboards' | 'matches'

const POLL_MS = 2500

// ── Leaderboard modal ─────────────────────────────────────────────────────────

type Col = { label: string; get: (r: Record<string, unknown>) => string | number; accent?: boolean }
type LbMeta = { key: string; title: string; columns: Col[] }

// ── Shared column sets ────────────────────────────────────────────────────────

const BATTING_BASE: Col[] = [
  { label: 'Player', get: r => r.player as string },
  { label: 'Team',   get: r => r.team as string },
  { label: 'M',      get: r => r.matches as number },
  { label: 'Inns',   get: r => r.innings as number },
  { label: 'NO',     get: r => r.not_outs as number },
  { label: 'HS',     get: r => r.highest_score as number },
  { label: 'Runs',   get: r => r.runs as number },
  { label: 'Avg',    get: r => r.average     != null ? Number(r.average).toFixed(1)     : '—' },
  { label: 'SR',     get: r => r.strike_rate != null ? Number(r.strike_rate).toFixed(1) : '—' },
  { label: '100s',   get: r => r.hundreds as number },
  { label: '50s',    get: r => r.fifties as number },
  { label: '4s',     get: r => r.fours as number },
  { label: '6s',     get: r => r.sixes as number },
]

const BOWLING_BASE: Col[] = [
  { label: 'Player', get: r => r.player as string },
  { label: 'Team',   get: r => r.team as string },
  { label: 'M',      get: r => r.matches as number },
  { label: 'Inns',   get: r => r.innings as number },
  { label: 'Overs',  get: r => r.overs as string },
  { label: 'Runs',   get: r => r.runs as number },
  { label: 'Wkts',   get: r => r.wickets as number },
  { label: 'Best',   get: r => r.best_bowling as string },
  { label: 'Avg',    get: r => r.average     != null ? Number(r.average).toFixed(1)     : '—' },
  { label: 'Econ',   get: r => r.economy     != null ? Number(r.economy).toFixed(2)     : '—' },
  { label: 'SR',     get: r => r.strike_rate != null ? Number(r.strike_rate).toFixed(1) : '—' },
  { label: '5w',     get: r => r.five_wicket_hauls as number },
  { label: '4w',     get: r => r.four_wicket_hauls as number },
  { label: 'Dots',   get: r => r.dots as number },
]

function battingCols(primary: string): Col[] {
  const rest = BATTING_BASE.filter(c => c.label !== 'Player' && c.label !== 'Team' && c.label !== primary)
  const primaryCol = BATTING_BASE.find(c => c.label === primary)!
  return [
    { label: 'Player', get: r => r.player as string },
    { label: 'Team',   get: r => r.team as string },
    { ...primaryCol, accent: true },
    ...rest,
  ]
}
function bowlingCols(primary: string): Col[] {
  const rest = BOWLING_BASE.filter(c => c.label !== 'Player' && c.label !== 'Team' && c.label !== primary)
  const primaryCol = BOWLING_BASE.find(c => c.label === primary)!
  return [
    { label: 'Player', get: r => r.player as string },
    { label: 'Team',   get: r => r.team as string },
    { ...primaryCol, accent: true },
    ...rest,
  ]
}

const LB_DEFS: LbMeta[] = [
  {
    key: 'mvp', title: 'Tournament MVP',
    columns: [
      { label: 'Player', get: r => r.player as string },
      { label: 'Team',   get: r => r.team as string },
      { label: 'Total',  get: r => Number(r.total).toFixed(1),        accent: true },
      { label: 'Bat',    get: r => Number(r.batting_pts).toFixed(1)  },
      { label: 'Bowl',   get: r => Number(r.bowling_pts).toFixed(1)  },
      { label: 'Field',  get: r => Number(r.fielding_pts).toFixed(1) },
    ],
  },
  { key: 'most_runs',           title: 'Most Runs',           columns: battingCols('Runs') },
  { key: 'most_wickets',        title: 'Most Wickets',        columns: bowlingCols('Wkts') },
  { key: 'best_strike_rate',    title: 'Best Strike Rate',    columns: battingCols('SR')   },
  { key: 'best_economy',        title: 'Best Economy',        columns: bowlingCols('Econ') },
  { key: 'most_sixes',          title: 'Most Sixes',          columns: battingCols('6s')   },
  { key: 'most_fours',          title: 'Most Fours',          columns: battingCols('4s')   },
  { key: 'most_dots',           title: 'Most Dot Balls',      columns: bowlingCols('Dots') },
  {
    key: 'highest_score', title: 'Highest Score',
    columns: [
      { label: 'Player', get: r => r.player as string },
      { label: 'Team',   get: r => r.team as string },
      { label: 'Runs',   get: r => `${r.runs as number}${r.not_out ? '*' : ''}`, accent: true },
      { label: 'Balls',  get: r => r.balls as number },
      { label: 'SR',     get: r => r.strike_rate != null ? Number(r.strike_rate).toFixed(1) : '—' },
      { label: '4s',     get: r => r.fours as number },
      { label: '6s',     get: r => r.sixes as number },
      { label: 'vs',     get: r => r.opponent as string },
      { label: 'Venue',  get: r => (r.venue as string) ?? '—' },
    ],
  },
  {
    key: 'best_bowling_figures', title: 'Best Bowling Figures',
    columns: [
      { label: 'Player',   get: r => r.player as string },
      { label: 'Team',     get: r => r.team as string },
      { label: 'Figures',  get: r => r.best_figures as string, accent: true },
      { label: 'Wkts',    get: r => r.wickets as number },
      { label: 'Runs',     get: r => r.runs as number },
      { label: 'Econ',     get: r => r.economy != null ? Number(r.economy).toFixed(2) : '—' },
      { label: 'vs',       get: r => r.opponent as string },
      { label: 'Venue',    get: r => (r.venue as string) ?? '—' },
    ],
  },
  { key: 'best_batting_average',title: 'Best Batting Avg',   columns: battingCols('Avg')  },
  { key: 'best_bowling_average',title: 'Best Bowling Avg',   columns: bowlingCols('Avg')  },
]

const LB_KEY_TO_API: Record<string, string> = {
  most_runs:            'most-runs',
  best_batting_average: 'best-batting-average',
  best_strike_rate:     'best-strike-rate',
  most_sixes:           'most-sixes',
  most_fours:           'most-fours',
  highest_score:        'highest-score',
  most_wickets:         'most-wickets',
  best_economy:         'best-economy',
  best_bowling_average: 'best-bowling-average',
  most_dots:            'most-dots',
  best_bowling_figures: 'best-bowling-figures',
  mvp:                  'mvp',
}

const PAGE_SIZE = 50

// ── Player avatar ─────────────────────────────────────────────────────────────

function PlayerAvatar({ name, size = 44 }: { name: string; size?: number }) {
  const initials = name.split(' ').filter(Boolean).map(w => w[0]).slice(0, 2).join('').toUpperCase()
  const COLORS = ['#0EA5E9', '#F97316', '#22C55E', '#F59E0B', '#8B5CF6', '#EF4444', '#EC4899', '#14B8A6']
  const color = COLORS[name.charCodeAt(0) % COLORS.length]
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: `${color}1A`, color, border: `1.5px solid ${color}55`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: Math.round(size * 0.36), fontWeight: 700, flexShrink: 0, letterSpacing: '-0.5px',
    }}>
      {initials}
    </div>
  )
}

// ── Role badge ────────────────────────────────────────────────────────────────

function RoleBadge({ role }: { role: string | null }) {
  if (!role) return null
  const r = role.toLowerCase()
  const [bg, color] =
    r.includes('bowl') ? ['rgba(239,68,68,0.12)', '#ef4444'] :
    r.includes('all')  ? ['rgba(14,165,233,0.12)', '#0ea5e9'] :
    r.includes('keep') ? ['rgba(245,158,11,0.12)', 'var(--score)'] :
                         ['rgba(34,197,94,0.12)', '#22c55e']
  const label =
    r.includes('bowl') ? 'BWL' :
    r.includes('all')  ? 'AR' :
    r.includes('keep') ? 'WK' : 'BAT'
  return (
    <span className="text-[10px] px-1 py-px rounded font-semibold shrink-0"
      style={{ background: bg, color }}>
      {label}
    </span>
  )
}

// ── Team XI preview panel ─────────────────────────────────────────────────────

type LineupPlayer = {
  player_id: number
  player_name: string
  player_role: string | null
  matches: number
  runs: number
  wickets: number
  mvp_points: number
  batting_pts: number
  bowling_pts: number
  fielding_pts: number
}

function TeamPreviewPanel({
  teamName,
  players,
  onClose,
}: {
  teamName: string
  players: LineupPlayer[]
  onClose: () => void
}) {
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [])

  return createPortal(
    <>
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, zIndex: 150, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(3px)' }}
      />
      <div style={{
        position: 'fixed', left: '50%', top: '50%', transform: 'translate(-50%, -50%)',
        width: 'min(380px, 96vw)', maxHeight: '85vh',
        zIndex: 151, display: 'flex', flexDirection: 'column',
        background: 'var(--bg)', borderRadius: 12, border: '1px solid var(--border)',
        overflow: 'hidden', animation: 'fadeIn 160ms ease',
      }}>
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>Squad</div>
            <div className="text-sm font-bold truncate" style={{ color: 'var(--text)' }}>{teamName}</div>
          </div>
          <button onClick={onClose} style={{ color: 'var(--text-muted)' }}><X size={16} /></button>
        </div>

        {/* Player list */}
        <div className="flex-1 overflow-y-auto">
          {players.map((p, i) => (
            <div key={p.player_id}
              className="flex items-center gap-3 px-4 py-3"
              style={{ borderBottom: '1px solid var(--border)' }}>
              <div className="text-xs w-5 text-right shrink-0 font-mono" style={{ color: 'var(--text-dim)' }}>{i + 1}</div>
              <PlayerAvatar name={p.player_name} size={32} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="text-sm font-medium truncate" style={{ color: 'var(--text)' }}>{p.player_name}</span>
                  <RoleBadge role={p.player_role} />
                </div>
                <div className="flex items-center gap-2 mt-0.5" style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                  <span>{p.runs} runs</span>
                  {p.wickets > 0 && <span>· {p.wickets} wkts</span>}
                </div>
              </div>
              {p.mvp_points > 0 && (
                <div className="text-right shrink-0">
                  <div className="text-sm font-bold" style={{ color: 'var(--score)' }}>{p.mvp_points.toFixed(1)}</div>
                  <div className="text-xs" style={{ color: 'var(--text-dim)', fontSize: 10 }}>MVP</div>
                </div>
              )}
            </div>
          ))}
          {players.length === 0 && (
            <div className="flex items-center justify-center h-32 text-sm" style={{ color: 'var(--text-dim)' }}>
              No player data
            </div>
          )}
        </div>
      </div>
      <style>{`@keyframes fadeIn { from { opacity:0;transform:translate(-50%,-50%) scale(0.96) } to { opacity:1;transform:translate(-50%,-50%) scale(1) } }`}</style>
    </>,
    document.body
  )
}

// ── Leaderboard modal ─────────────────────────────────────────────────────────

function LeaderboardModal({
  simId,
  lbKey,
  onClose,
}: {
  simId: string
  lbKey: string
  onClose: () => void
}) {
  const meta = LB_DEFS.find(d => d.key === lbKey)!
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [total, setTotal] = useState(0)
  const [fetching, setFetching] = useState(false)
  const [allLoaded, setAllLoaded] = useState(false)
  const [search, setSearch] = useState('')
  const offsetRef = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [])

  const apiType = LB_KEY_TO_API[lbKey]

  const fetchPage = useCallback(async (offset: number) => {
    if (!apiType || fetching) return
    setFetching(true)
    try {
      const r = await api.getLeaderboardPage(simId, apiType, PAGE_SIZE, offset)
      const entries = r.entries as Record<string, unknown>[]
      setRows(prev => offset === 0 ? entries : [...prev, ...entries])
      setTotal(r.total)
      const nextOffset = offset + entries.length
      offsetRef.current = nextOffset
      if (nextOffset >= r.total || entries.length < PAGE_SIZE) setAllLoaded(true)
    } catch { /* keep what we have */ }
    finally { setFetching(false) }
  }, [apiType, simId, fetching])

  useEffect(() => {
    offsetRef.current = 0
    setRows([])
    setTotal(0)
    setAllLoaded(false)
    fetchPage(0)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simId, lbKey])

  useEffect(() => {
    if (!search || allLoaded || fetching) return
    const loadAll = async () => {
      let off = offsetRef.current
      while (off < total || total === 0) {
        setFetching(true)
        try {
          const r = await api.getLeaderboardPage(simId, apiType!, PAGE_SIZE, off)
          const entries = r.entries as Record<string, unknown>[]
          setRows(prev => [...prev, ...entries])
          setTotal(r.total)
          off += entries.length
          offsetRef.current = off
          if (off >= r.total || entries.length < PAGE_SIZE) { setAllLoaded(true); break }
        } catch { break }
        finally { setFetching(false) }
      }
    }
    loadAll()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  const q = search.toLowerCase()
  const filtered = q
    ? rows.filter(r =>
        String(r.player ?? '').toLowerCase().includes(q) ||
        String(r.team ?? '').toLowerCase().includes(q)
      )
    : rows

  const hasMore = !allLoaded

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    if (!search && !fetching && !allLoaded && el.scrollHeight - el.scrollTop - el.clientHeight < 150) {
      fetchPage(offsetRef.current)
    }
  }, [search, fetching, allLoaded, fetchPage])

  return createPortal(
    <>
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, zIndex: 160, background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(3px)' }}
      />
      <div
        style={{
          position: 'fixed', left: '50%', transform: 'translateX(-50%)',
          top: '5vh', width: 'min(700px, 96vw)', height: '90vh',
          zIndex: 161, display: 'flex', flexDirection: 'column',
          background: 'var(--bg)', borderRadius: 12, border: '1px solid var(--border)',
          overflow: 'hidden', animation: 'fadeIn 150ms ease',
        }}
      >
        <div className="flex items-center gap-3 px-4 py-3 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
          <div className="text-sm font-semibold shrink-0" style={{ color: 'var(--text)' }}>{meta.title}</div>
          <div className="flex-1 flex items-center gap-2 px-3 py-1.5 rounded-lg"
            style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
            <Search size={13} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
            <input
              autoFocus
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search player or team…"
              style={{ background: 'transparent', border: 'none', outline: 'none', fontSize: 13, color: 'var(--text)', width: '100%' }}
            />
            {search && (
              <button onClick={() => setSearch('')} style={{ color: 'var(--text-dim)', lineHeight: 1 }}>
                <X size={12} />
              </button>
            )}
          </div>
          {total > 0 && (
            <div className="text-xs shrink-0" style={{ color: 'var(--text-dim)' }}>
              {allLoaded ? total : `${rows.length}/${total}`} players
            </div>
          )}
          <button onClick={onClose} style={{ color: 'var(--text-muted)', flexShrink: 0 }}><X size={16} /></button>
        </div>

        <div ref={scrollRef} className="flex-1 overflow-y-auto overflow-x-auto" onScroll={handleScroll}>
          {rows.length === 0 && fetching ? (
            <div className="flex justify-center py-12"><Spinner /></div>
          ) : (
            <table className="w-full text-sm" style={{ minWidth: meta.columns.length * 80 }}>
              {(() => {
                const cols = meta.columns.filter(c => c.label !== 'Team')
                return (
                  <>
                    <thead style={{ position: 'sticky', top: 0, background: 'var(--surface)', zIndex: 1 }}>
                      <tr style={{ borderBottom: '1px solid var(--border)' }}>
                        <th className="px-3 py-2.5 text-left font-medium" style={{ color: 'var(--text-muted)' }}>#</th>
                        {cols.map(c => (
                          <th key={c.label} className="px-3 py-2.5 text-left font-medium whitespace-nowrap"
                            style={{ color: 'var(--text-muted)' }}>{c.label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((r, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                          <td className="px-3 py-2.5" style={{ color: i === 0 && !q ? 'var(--score)' : 'var(--text-dim)' }}>
                            {(r.rank as number) ?? i + 1}
                          </td>
                          {cols.map((c, ci) => (
                            <td key={ci} className="px-3 py-2.5"
                              style={{ color: c.accent ? 'var(--score)' : 'var(--text-muted)', fontWeight: c.accent ? 600 : 400, whiteSpace: c.label === 'Player' ? 'normal' : 'nowrap' }}>
                              {c.label === 'Player' ? (
                                <div>
                                  <div style={{ color: 'var(--text)', fontWeight: 500 }}>{c.get(r)}</div>
                                  <div style={{ color: 'var(--text-dim)', fontSize: 11, fontWeight: 400 }}>{r.team as string}</div>
                                </div>
                              ) : c.get(r)}
                            </td>
                          ))}
                        </tr>
                      ))}
                      {filtered.length === 0 && !fetching && (
                        <tr><td colSpan={cols.length + 1}
                          className="px-4 py-8 text-center text-sm" style={{ color: 'var(--text-dim)' }}>
                          No results
                        </td></tr>
                      )}
                      {!search && hasMore && (
                        <tr>
                          <td colSpan={cols.length + 1} className="px-4 py-4 text-center">
                            {fetching
                              ? <div className="flex justify-center"><Spinner size={16} /></div>
                              : <div className="text-xs" style={{ color: 'var(--text-dim)' }}>Scroll for more</div>}
                          </td>
                        </tr>
                      )}
                      {search && !allLoaded && (
                        <tr>
                          <td colSpan={cols.length + 1} className="px-4 py-3 text-center">
                            <div className="flex items-center justify-center gap-2 text-xs" style={{ color: 'var(--text-dim)' }}>
                              <Spinner size={13} /> Loading remaining players…
                            </div>
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </>
                )
              })()}
            </table>
          )}
        </div>
      </div>
    </>,
    document.body
  )
}

// ── Stat card ────────────────────────────────────────────────────────────────

function StatCard({
  meta, rows, valueKey, decimals = 0, onViewAll,
}: {
  meta: LbMeta
  rows: Record<string, unknown>[]
  valueKey: string
  decimals?: number
  onViewAll: () => void
}) {
  const top5 = rows.slice(0, 5)

  const fmt = (v: unknown) => {
    if (v == null) return '—'
    const n = Number(v)
    return decimals > 0 ? n.toFixed(decimals) : String(Math.round(n))
  }

  return (
    <div
      className="card p-3 flex flex-col gap-0 cursor-pointer transition-all"
      style={{ borderColor: 'var(--border)' }}
      onClick={onViewAll}
      onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
      onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
    >
      <div className="text-xs font-semibold uppercase tracking-wider mb-2.5" style={{ color: 'var(--text-dim)' }}>
        {meta.title}
      </div>
      {top5.length === 0 ? (
        <div className="text-xs py-2" style={{ color: 'var(--text-dim)' }}>No data</div>
      ) : (
        top5.map((r, i) => (
          <div key={i} className="flex items-center gap-2 py-1.5"
            style={{ borderBottom: i < top5.length - 1 ? '1px solid var(--border)' : 'none' }}>
            <span className="text-xs w-4 text-right shrink-0 font-mono" style={{ color: 'var(--text-dim)' }}>{i + 1}</span>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium truncate" style={{ color: 'var(--text)' }}>{r.player as string}</div>
              <div className="text-xs truncate" style={{ color: 'var(--text-dim)', fontSize: 10 }}>{r.team as string}</div>
            </div>
            <span className="text-xs font-bold shrink-0" style={{ color: 'var(--score)' }}>
              {fmt(r[valueKey])}
            </span>
          </div>
        ))
      )}
      <div className="flex items-center gap-1 text-xs font-medium pt-2 mt-auto" style={{ color: 'var(--accent)' }}>
        View all <ChevronRight size={11} />
      </div>
    </div>
  )
}

// ── Lineups tab ───────────────────────────────────────────────────────────────

type LineupTeam = { team_name: string; players: LineupPlayer[] }

function LineupsTab({ simId, userTeamName }: { simId: string; userTeamName: string | null }) {
  const [teams, setTeams] = useState<LineupTeam[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getLineups(simId).then(r => {
      setTeams(r.teams)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [simId])

  if (loading) return <div className="flex justify-center py-12"><Spinner /></div>
  if (!teams.length) return <div className="text-center py-8 text-sm" style={{ color: 'var(--text-dim)' }}>No lineup data</div>

  return (
    <div className="fade-in flex flex-col gap-4">
      {teams.map(team => {
        const isMyTeam = !!userTeamName && team.team_name === userTeamName
        return (
          <div key={team.team_name} className="card overflow-hidden"
            style={{ borderColor: isMyTeam ? 'var(--accent)' : 'var(--border)' }}>
            {/* Team header */}
            <div className="flex items-center gap-2 px-4 py-2.5"
              style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
              <div className="text-sm font-bold" style={{ color: isMyTeam ? 'var(--accent)' : 'var(--text)' }}>
                {team.team_name}
              </div>
              {isMyTeam && (
                <span className="text-xs px-1.5 py-px rounded font-semibold"
                  style={{ background: 'rgba(59,130,246,0.12)', color: 'var(--accent)' }}>You</span>
              )}
              <div className="ml-auto text-xs" style={{ color: 'var(--text-dim)' }}>
                {team.players.length} players
              </div>
            </div>

            {/* Column headers */}
            <div className="grid px-4 py-1.5"
              style={{ gridTemplateColumns: '1fr 52px 52px 56px', borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
              <div className="text-xs font-medium" style={{ color: 'var(--text-dim)' }}>Player</div>
              <div className="text-xs font-medium text-right" style={{ color: 'var(--text-dim)' }}>Runs</div>
              <div className="text-xs font-medium text-right" style={{ color: 'var(--text-dim)' }}>Wkts</div>
              <div className="text-xs font-medium text-right" style={{ color: 'var(--score)' }}>MVP</div>
            </div>

            {/* Players */}
            {team.players.map((p, i) => (
              <div key={p.player_id}
                className="grid items-center px-4 py-2.5"
                style={{
                  gridTemplateColumns: '1fr 52px 52px 56px',
                  borderBottom: i < team.players.length - 1 ? '1px solid var(--border)' : 'none',
                }}>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-xs w-4 text-right shrink-0 font-mono" style={{ color: 'var(--text-dim)' }}>{i + 1}</span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-medium truncate" style={{ color: 'var(--text)' }}>{p.player_name}</span>
                      <RoleBadge role={p.player_role} />
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)', fontSize: 10 }}>{p.matches}M</div>
                  </div>
                </div>
                <div className="text-xs font-mono text-right" style={{ color: p.runs > 0 ? 'var(--text-muted)' : 'var(--text-dim)' }}>
                  {p.runs > 0 ? p.runs : '—'}
                </div>
                <div className="text-xs font-mono text-right" style={{ color: p.wickets > 0 ? 'var(--text-muted)' : 'var(--text-dim)' }}>
                  {p.wickets > 0 ? p.wickets : '—'}
                </div>
                <div className="text-xs font-bold text-right" style={{ color: p.mvp_points > 0 ? 'var(--score)' : 'var(--text-dim)' }}>
                  {p.mvp_points > 0 ? p.mvp_points.toFixed(1) : '—'}
                </div>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function ResultsPage() {
  const { simId } = useParams<{ simId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const locState = (location.state ?? {}) as Record<string, unknown>

  const scrollToMatchId = useRef<number | undefined>((locState.scrollTo as number) || undefined)
  const hasScrolled = useRef(false)

  const [status, setStatus] = useState<'pending' | 'running' | 'completed' | 'failed'>('pending')
  const [errorMsg, setErrorMsg] = useState('')
  const [result, setResult] = useState<TournamentResult | null>(null)
  const [leaderboards, setLeaderboards] = useState<LeaderboardsDashboard | null>(null)
  const [matches, setMatches] = useState<MatchItem[]>([])
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [tab, setTab] = useState<Tab>((locState.tab as Tab) ?? 'standings')
  const [activeLb, setActiveLb] = useState<string | null>(null)
  const [myTeamOnly, setMyTeamOnly] = useState(false)
  const [standingsSubTab, setStandingsSubTab] = useState<'playoffs' | 'table'>('playoffs')
  const standingsDefaultSet = useRef(false)

  // Team preview state
  const [previewTeam, setPreviewTeam] = useState<string | null>(null)
  const [lineupTeams, setLineupTeams] = useState<LineupTeam[]>([])

  useEffect(() => {
    if (locState.tab || locState.scrollTo) {
      navigate(location.pathname, { replace: true, state: {} })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!simId) return
    async function fetchStatus() {
      try {
        const s = await api.getSimStatus(simId!)
        if (s.status === 'completed') {
          clearInterval(pollRef.current!)
          setStatus('completed')
          const clientId = getClientId()
          const [r, lb, m] = await Promise.all([
            api.getSimResult(simId!, clientId),
            api.getLeaderboards(simId!),
            api.getMatches(simId!),
          ])
          setResult(r)
          setLeaderboards(lb)
          setMatches(m)
          // Pre-fetch lineups for team preview on points-table click
          api.getLineups(simId!).then(l => setLineupTeams(l.teams)).catch(() => {/* non-critical */})
        } else if (s.status === 'failed') {
          clearInterval(pollRef.current!)
          setStatus('failed')
          setErrorMsg(s.error || 'Simulation failed')
        } else {
          setStatus(s.status as 'pending' | 'running')
        }
      } catch { /* keep polling */ }
    }
    fetchStatus()
    pollRef.current = setInterval(fetchStatus, POLL_MS)
    return () => clearInterval(pollRef.current!)
  }, [simId])

  useEffect(() => {
    if (tab === 'matches' && scrollToMatchId.current && !hasScrolled.current && matches.length > 0) {
      const el = document.getElementById(`match-${scrollToMatchId.current}`)
      if (el) {
        el.scrollIntoView({ block: 'center', behavior: 'instant' })
        hasScrolled.current = true
      }
    }
  }, [tab, matches])

  useEffect(() => {
    if (standingsDefaultSet.current || !result || matches.length === 0) return
    standingsDefaultSet.current = true
    const playoffMs = matches.filter(m => !/^match\s+\d+$/i.test(m.match_label.trim()))
    if (playoffMs.length === 0) { setStandingsSubTab('table'); return }
    if (!result.user_team_name) return
    const qualified = playoffMs.some(
      m => m.home_team === result.user_team_name || m.away_team === result.user_team_name
    )
    if (!qualified) setStandingsSubTab('table')
  }, [result, matches])

  if (status === 'pending' || status === 'running') {
    return (
      <div className="flex flex-col items-center justify-center min-h-[calc(100vh-64px)] gap-4">
        <div className="pulse-accent w-16 h-16 rounded-full flex items-center justify-center"
          style={{ border: '2px solid var(--accent)' }}>
          <Spinner size={28} />
        </div>
        <div className="text-base font-medium" style={{ color: 'var(--text)' }}>Simulating tournament…</div>
        <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Running ball-by-ball. Takes 10–30 seconds.</div>
      </div>
    )
  }

  if (status === 'failed') {
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center">
        <div className="text-4xl mb-4">⚠</div>
        <div className="text-base font-medium mb-2" style={{ color: 'var(--text)' }}>Simulation failed</div>
        <div className="text-sm mb-6" style={{ color: 'var(--text-muted)' }}>{errorMsg}</div>
        <button className="btn-outline" onClick={() => navigate('/')}>Back to home</button>
      </div>
    )
  }

  const pt = result?.points_table ?? []
  const userTeamName = result?.user_team_name ?? null

  const visibleMatches = myTeamOnly && userTeamName
    ? matches.filter(m => m.home_team === userTeamName || m.away_team === userTeamName)
    : matches

  const groupStageMatches = visibleMatches.filter(m => /^match\s+\d+$/i.test(m.match_label.trim()))
  const playoffMatches = visibleMatches.filter(m => !/^match\s+\d+$/i.test(m.match_label.trim()))
  const allPlayoffMatches = matches.filter(m => !/^match\s+\d+$/i.test(m.match_label.trim()))

  const lbRows = (key: string): Record<string, unknown>[] =>
    ((leaderboards as unknown as Record<string, unknown>)?.[key] as Record<string, unknown>[]) ?? []

  const canTryAgain = !!(result?.mode && result?.source_tournament_id)

  // Team preview panel data
  const previewTeamData = previewTeam ? lineupTeams.find(t => t.team_name === previewTeam) : null

  return (
    <div className="w-full px-1 py-6">
      {/* Leaderboard modal */}
      {activeLb && (
        <LeaderboardModal
          simId={simId!}
          lbKey={activeLb}
          onClose={() => setActiveLb(null)}
        />
      )}

      {/* Team preview panel */}
      {previewTeam && previewTeamData && (
        <TeamPreviewPanel
          teamName={previewTeam}
          players={previewTeamData.players}
          onClose={() => setPreviewTeam(null)}
        />
      )}

      {/* Top nav */}
      <button
        className="flex items-center gap-1 text-sm mb-5"
        style={{ color: 'var(--text-muted)' }}
        onClick={() => navigate('/')}
      >
        <ChevronRight size={14} style={{ transform: 'rotate(180deg)' }} /> Home
      </button>

      {/* Result banner */}
      {result && (() => {
        const placement = result.user_team_placement
        const userTeam = result.user_team_name

        type BannerTheme = { icon: string; headline: string; sub: string; border: string; bg: string; color: string }
        const theme: BannerTheme = (() => {
          if (userTeam) {
            if (placement === 'Winner')    return { icon: '🏆', headline: 'Champions!',             sub: `${userTeam} won the title`,             border: 'var(--score)', bg: 'rgba(245,158,11,0.07)', color: 'var(--score)' }
            if (placement === 'Runner-up') return { icon: '🥈', headline: 'Runner-up',               sub: `${userTeam} — Finished 2nd`,            border: 'rgba(148,163,184,0.4)', bg: 'rgba(148,163,184,0.05)', color: '#94a3b8' }
            if (placement === 'Playoffs')  return { icon: '✨', headline: 'You made the Playoffs!', sub: `${userTeam} reached the knockout stage`, border: 'var(--accent)', bg: 'rgba(59,130,246,0.05)', color: 'var(--accent)' }
            return { icon: '😞', headline: 'Did not qualify', sub: `${userTeam} was eliminated in the group stage`, border: 'var(--border)', bg: 'transparent', color: 'var(--text-muted)' }
          }
          return { icon: '🏆', headline: result.winner ? `${result.winner} won the tournament` : 'Tournament complete', sub: '', border: 'var(--score)', bg: 'rgba(245,158,11,0.07)', color: 'var(--score)' }
        })()

        // Secondary info line for multiplayer (when user is a participant)
        const secondaryLine = userTeam ? (() => {
          const winner = result.winner
          const runnerUp = result.runner_up
          if (placement === 'Winner') {
            return runnerUp ? `Runner-up: ${runnerUp}` : null
          }
          return winner ? `🏆 Winner: ${winner}` : null
        })() : null

        return (
          <div className="rounded-xl mb-5 fade-in overflow-hidden"
            style={{ border: `1px solid ${theme.border}`, background: theme.bg }}>
            <div className="flex items-center gap-3 px-4 py-3">
              <span className="text-2xl shrink-0 leading-none">{theme.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="text-base font-bold leading-tight" style={{ color: theme.color }}>{theme.headline}</div>
                <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  {theme.sub && <span>{theme.sub}</span>}
                  {result.tournament_name && (
                    <span style={{ color: 'var(--text-dim)' }}>
                      {theme.sub ? ' · ' : ''}{result.tournament_name}{result.season && result.mode !== 'multiplayer' ? ` ${result.season}` : ''} · {result.total_matches} matches
                    </span>
                  )}
                </div>
                {secondaryLine && (
                  <div className="text-xs mt-1" style={{ color: 'var(--text-dim)' }}>{secondaryLine}</div>
                )}
              </div>
            </div>
            {canTryAgain && (
              <div className="px-4 pb-3">
                <button
                  className="btn-outline flex items-center gap-1.5 text-xs py-1.5 px-2.5"
                  onClick={() => navigate(`/${result!.mode}`, {
                    state: {
                      tryAgain: true,
                      tournamentId: result!.source_tournament_id,
                      teamId: result!.user_team_id ?? null,
                      tournamentName: result!.tournament_name,
                      season: result!.season,
                      teamName: result!.user_team_name ?? null,
                    },
                  })}
                >
                  <RotateCcw size={12} /> Try again differently
                </button>
              </div>
            )}
          </div>
        )
      })()}

      {/* Tabs */}
      <div className="flex gap-1 mb-5 p-1 rounded-lg" style={{ background: 'var(--surface)' }}>
        {([
          { id: 'standings' as Tab,   label: 'Overview',     icon: <TrendingUp size={14} /> },
          { id: 'leaderboards' as Tab,label: 'Leaderboards', icon: <Star size={14} /> },
          { id: 'matches' as Tab,     label: 'Matches',      icon: <Swords size={14} /> },
        ]).map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-md text-sm font-medium transition-all"
            style={{
              background: tab === t.id ? 'var(--surface-2)' : 'transparent',
              color: tab === t.id ? 'var(--accent)' : 'var(--text-muted)',
              border: tab === t.id ? '1px solid var(--border)' : '1px solid transparent',
            }}>
            {t.icon}
            <span>{t.label}</span>
          </button>
        ))}
      </div>

      {/* ═══ Standings ═══ */}
      {tab === 'standings' && (
        <div className="fade-in flex flex-col gap-4">
          {/* Player of the Tournament */}
          {leaderboards && (() => {
            const mvpRow = lbRows('mvp')[0]
            if (!mvpRow) return null
            const name  = mvpRow.player as string
            const team  = mvpRow.team as string
            const total = Number(mvpRow.total).toFixed(1)
            return (
              <button
                onClick={() => setActiveLb('mvp')}
                className="w-full text-left rounded-xl fade-in overflow-hidden"
                style={{ border: '1px solid var(--border)', background: 'var(--surface)', display: 'block' }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
              >
                <div className="flex gap-3 items-center px-4 py-3">
                  <PlayerAvatar name={name} size={46} />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-semibold uppercase tracking-wider whitespace-nowrap" style={{ color: 'var(--text-dim)' }}>Player of the Tournament</div>
                    <div className="text-sm font-bold truncate" style={{ color: 'var(--text)' }}>{name}</div>
                    <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{team}</div>
                  </div>
                  <div className="text-right flex-shrink-0 mr-1">
                    <div className="text-xl font-extrabold" style={{ color: 'var(--score)' }}>{total}</div>
                    <div className="text-xs" style={{ color: 'var(--text-dim)' }}>MVP pts</div>
                  </div>
                  <ChevronRight size={14} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
                </div>
              </button>
            )
          })()}

          {/* Sub-tabs */}
          {allPlayoffMatches.length > 0 && (
            <div className="flex gap-1 p-1 rounded-lg" style={{ background: 'var(--surface)' }}>
              {(['playoffs', 'table'] as const).map(st => (
                <button
                  key={st}
                  onClick={() => setStandingsSubTab(st)}
                  className="flex-1 py-1.5 text-xs font-medium rounded-md transition-all"
                  style={{
                    background: standingsSubTab === st ? 'var(--surface-2)' : 'transparent',
                    color: standingsSubTab === st ? 'var(--text)' : 'var(--text-dim)',
                    border: standingsSubTab === st ? '1px solid var(--border)' : '1px solid transparent',
                  }}
                >
                  {st === 'playoffs' ? 'Playoffs' : 'Points Table'}
                </button>
              ))}
            </div>
          )}

          {/* Playoffs bracket */}
          {standingsSubTab === 'playoffs' && allPlayoffMatches.length > 0 && (
            <PlayoffBracket
              matches={allPlayoffMatches}
              simId={simId!}
              userTeamName={userTeamName}
            />
          )}

          {/* Points table */}
          {(allPlayoffMatches.length === 0 || standingsSubTab === 'table') && (
            <div className="card overflow-x-auto">
              <table className="w-full text-sm min-w-[400px]">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['#', 'Team', 'P', 'W', 'L', 'Pts', 'NRR'].map(h => (
                      <th key={h} className="px-3 py-2.5 text-left font-medium"
                        style={{ color: 'var(--text-muted)' }}>{h}</th>
                    ))}
                    <th className="px-3 py-2.5 text-left font-medium" style={{ color: 'var(--text-muted)' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {pt.map((row, i) => {
                    const isWinner = result?.winner === row.team
                    const isMyTeam = !!userTeamName && row.team === userTeamName
                    return (
                    <tr key={row.team}
                      className="cursor-pointer transition-colors"
                      style={{
                        borderBottom: i < pt.length - 1 ? '1px solid var(--border)' : 'none',
                        background: isWinner
                          ? 'rgba(245,158,11,0.09)'
                          : isMyTeam ? 'rgba(59,130,246,0.07)'
                          : i < 4 ? 'rgba(59,130,246,0.025)' : 'transparent',
                        boxShadow: isMyTeam && !isWinner ? 'inset 2px 0 0 var(--accent)' : undefined,
                      }}
                      onClick={() => setPreviewTeam(row.team)}
                      onMouseEnter={e => (e.currentTarget as HTMLTableRowElement).style.filter = 'brightness(1.15)'}
                      onMouseLeave={e => (e.currentTarget as HTMLTableRowElement).style.filter = ''}
                    >
                      <td className="px-3 py-2.5" style={{ color: isWinner ? 'var(--score)' : i < 4 ? 'var(--accent)' : 'var(--text-dim)' }}>
                        {isWinner ? <Trophy size={13} style={{ color: 'var(--score)' }} /> : i + 1}
                      </td>
                      <td className="px-3 py-2.5 font-medium" style={{ color: isWinner ? 'var(--score)' : isMyTeam ? 'var(--accent)' : 'var(--text)', whiteSpace: 'nowrap' }}>
                        {row.team}
                        {isWinner && (
                          <span className="ml-2 text-xs px-1.5 py-px rounded font-semibold"
                            style={{ background: 'rgba(245,158,11,0.18)', color: 'var(--score)' }}>🏆</span>
                        )}
                        {!isWinner && i < 4 && (
                          <span className="ml-2 text-xs px-1.5 py-px rounded font-semibold"
                            style={{ background: 'rgba(59,130,246,0.12)', color: 'var(--accent)' }}>Q</span>
                        )}
                        {isMyTeam && (
                          <span className="ml-2 text-xs px-1.5 py-px rounded font-semibold"
                            style={{ background: 'rgba(59,130,246,0.12)', color: 'var(--accent)' }}>You</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5" style={{ color: 'var(--text-muted)' }}>{row.played}</td>
                      <td className="px-3 py-2.5" style={{ color: 'var(--win)' }}>{row.won}</td>
                      <td className="px-3 py-2.5" style={{ color: 'var(--loss)' }}>{row.lost}</td>
                      <td className="px-3 py-2.5 font-semibold" style={{ color: isWinner ? 'var(--score)' : 'var(--text-muted)' }}>{row.points}</td>
                      <td className="px-3 py-2.5" style={{ color: row.nrr >= 0 ? 'var(--win)' : 'var(--loss)' }}>
                        {row.nrr >= 0 ? '+' : ''}{row.nrr.toFixed(3)}
                      </td>
                      <td className="px-3 py-2.5">
                        <ChevronRight size={12} style={{ color: 'var(--text-dim)' }} />
                      </td>
                    </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ═══ Lineups tab — commented out until tab label spacing is fixed ═══
      {tab === 'lineups' && (
        <LineupsTab simId={simId!} userTeamName={userTeamName} />
      )}
      */}

      {/* ═══ Leaderboards ═══ */}
      {tab === 'leaderboards' && leaderboards && (
        <div className="fade-in grid grid-cols-2 gap-3">
          {LB_DEFS.map(meta => {
            const rows = lbRows(meta.key)
            const [valueKey, decimals] = (() => {
              switch (meta.key) {
                case 'most_runs':            return ['runs', 0] as const
                case 'best_batting_average': return ['average', 1] as const
                case 'best_strike_rate':     return ['strike_rate', 1] as const
                case 'most_sixes':           return ['sixes', 0] as const
                case 'most_fours':           return ['fours', 0] as const
                case 'highest_score':        return ['runs', 0] as const
                case 'most_wickets':         return ['wickets', 0] as const
                case 'best_economy':         return ['economy', 2] as const
                case 'best_bowling_average': return ['average', 1] as const
                case 'most_dots':            return ['dots', 0] as const
                case 'best_bowling_figures': return ['wickets', 0] as const
                default:                     return ['total', 1] as const
              }
            })()
            return (
              <StatCard
                key={meta.key}
                meta={meta}
                rows={rows}
                valueKey={valueKey}
                decimals={decimals}
                onViewAll={() => setActiveLb(meta.key)}
              />
            )
          })}
        </div>
      )}

      {/* ═══ Matches ═══ */}
      {tab === 'matches' && (
        <div className="fade-in flex flex-col gap-6">
          {userTeamName && (
            <label className="flex items-center justify-end gap-1.5 cursor-pointer select-none" style={{ color: 'var(--text-dim)', fontSize: 11, fontWeight: 400 }}>
              <input
                type="checkbox"
                checked={myTeamOnly}
                onChange={e => setMyTeamOnly(e.target.checked)}
                className="accent-[var(--accent)] w-3 h-3 cursor-pointer"
              />
              Show only my matches
            </label>
          )}
          {playoffMatches.length > 0 && (
            <MatchGroup title="Playoffs" matches={[...playoffMatches].reverse()} simId={simId!} navigate={navigate} userTeamName={userTeamName} />
          )}
          {groupStageMatches.length > 0 && (
            <MatchGroup title="Group Stage" matches={[...groupStageMatches].reverse()} simId={simId!} navigate={navigate} userTeamName={userTeamName} />
          )}
          {visibleMatches.length === 0 && matches.length > 0 && (
            <div className="text-center py-8 text-sm" style={{ color: 'var(--text-dim)' }}>No matches for {userTeamName}</div>
          )}
          {matches.length === 0 && (
            <div className="text-center py-8 text-sm" style={{ color: 'var(--text-dim)' }}>No match data</div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Match group ───────────────────────────────────────────────────────────────

function MatchGroup({ title, matches, simId, navigate, userTeamName }: {
  title: string
  matches: MatchItem[]
  simId: string
  navigate: ReturnType<typeof useNavigate>
  userTeamName: string | null
}) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--text-dim)' }}>
        {title}
      </div>
      <div className="flex flex-col gap-1.5">
        {matches.map(m => (
          <button
            key={m.match_id}
            id={`match-${m.match_id}`}
            onClick={() => navigate(`/results/${simId}/matches/${m.match_id}`, { state: { backPath: `/results/${simId}`, fromTab: 'matches', userTeam: userTeamName } })}
            className="card-sm w-full px-4 py-4 text-left transition-all"
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2 min-w-0 flex-1 mr-2" style={{ color: 'var(--text-dim)' }}>
                <span className="text-xs shrink-0">{m.match_label}</span>
                {m.venue && (
                  <span className="text-xs truncate" style={{ color: 'var(--text-dim)' }}>
                    · {m.venue}{m.venue_country ? `, ${m.venue_country}` : ''}
                  </span>
                )}
                {m.is_super_over && (
                  <span className="px-1 py-px rounded text-xs shrink-0"
                    style={{ background: 'rgba(245,158,11,0.12)', color: 'var(--score)' }}>SO</span>
                )}
              </div>
              <ChevronRight size={13} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
            </div>

            <div className="flex items-center gap-3">
              <div className="flex-1 text-left">
                <div className="text-xs font-medium mb-1 truncate"
                  style={{ color: m.winner === m.home_team ? 'var(--text)' : 'var(--text-muted)' }}>
                  {m.home_team}
                </div>
                {m.home_score != null ? (
                  <>
                    <div className="text-base font-bold font-mono leading-none"
                      style={{ color: m.winner === m.home_team ? 'var(--score)' : 'var(--text-muted)' }}>
                      {m.home_score}/{m.home_wickets ?? 0}
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>
                      ({m.home_overs ?? '—'} Ov)
                    </div>
                  </>
                ) : (
                  <div className="text-base font-bold" style={{ color: 'var(--text-dim)' }}>—</div>
                )}
              </div>

              <div className="text-sm font-bold shrink-0 px-1" style={{ color: 'var(--text-dim)' }}>vs</div>

              <div className="flex-1 text-right">
                <div className="text-xs font-medium mb-1 truncate"
                  style={{ color: m.winner === m.away_team ? 'var(--text)' : 'var(--text-muted)' }}>
                  {m.away_team}
                </div>
                {m.away_score != null ? (
                  <>
                    <div className="text-base font-bold font-mono leading-none"
                      style={{ color: m.winner === m.away_team ? 'var(--score)' : 'var(--text-muted)' }}>
                      {m.away_score}/{m.away_wickets ?? 0}
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>
                      ({m.away_overs ?? '—'} Ov)
                    </div>
                  </>
                ) : (
                  <div className="text-base font-bold" style={{ color: 'var(--text-dim)' }}>—</div>
                )}
              </div>
            </div>

            {m.result && (
              <div className="text-xs mt-3 pt-2" style={{ color: 'var(--text-muted)', borderTop: '1px solid var(--border)' }}>
                {m.result}
              </div>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}
