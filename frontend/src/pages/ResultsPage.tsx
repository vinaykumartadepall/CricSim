import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { createPortal } from 'react-dom'
import { Trophy, TrendingUp, Swords, Star, RotateCcw, ChevronRight, ChevronLeft, X, Search, Users } from 'lucide-react'
import { Spinner } from '@/components/ui/Spinner'
import { ShareButton } from '@/components/ui/ShareButton'
import { RoleBadge } from '@/components/ui/RoleBadge'
import { PlayerAvatar } from '@/components/ui/Avatar'
import { FormatBadge } from '@/components/ui/FormatBadge'
import { PlacementBadge, RankBadge } from '@/components/ui/PlacementBadge'
import { PlayoffBracket } from '@/components/PlayoffBracket'
import { api } from '@/api/client'
import { getClientId } from '@/api/clientId'
import { useBodyScrollLock } from '@/hooks/useBodyScrollLock'
import { captureViewportImage } from '@/lib/shareScreenshot'
import { opaqueTint } from '@/lib/colorTint'
import type {
  TournamentResult, LeaderboardsDashboard,
  MatchItem, ChallengeLeaderboardEntry,
} from '@/types'

type Tab = 'standings' | 'leaderboards' | 'matches'

// ── Result banner background ────────────────────────────────────────────────────

// ── Share text ────────────────────────────────────────────────────────────────

function tournamentShareText(result: TournamentResult): string {
  const suffix = result.tournament_name
    ? `${result.tournament_name}${result.season && result.mode !== 'multiplayer' ? ` ${result.season}` : ''}`
    : 'a tournament'
  const team = result.user_team_name
  if (team) {
    const placement = result.user_team_placement
    if (placement === 'Winner')    return `🏆 I won ${suffix} with ${team} on CricSim! Can you do better?`
    if (placement === 'Runner-up') return `😤 So close! I finished runner-up with ${team} in ${suffix} on CricSim.`
    if (placement === 'Playoffs')  return `✨ made the playoffs with ${team} in ${suffix} on CricSim!`
    return `🏏 Just played ${suffix} with ${team} on CricSim!`
  }
  return result.winner ? `🏆 ${result.winner} won ${suffix} on CricSim!` : `🏏 Check out this ${suffix} on CricSim!`
}

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
  { label: 'Avg',    get: r => r.average     != null ? Number(r.average).toFixed(1)     : '-' },
  { label: 'SR',     get: r => r.strike_rate != null ? Number(r.strike_rate).toFixed(1) : '-' },
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
  { label: 'Avg',    get: r => r.average     != null ? Number(r.average).toFixed(1)     : '-' },
  { label: 'Econ',   get: r => r.economy     != null ? Number(r.economy).toFixed(2)     : '-' },
  { label: 'SR',     get: r => r.strike_rate != null ? Number(r.strike_rate).toFixed(1) : '-' },
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
      { label: 'SR',     get: r => r.strike_rate != null ? Number(r.strike_rate).toFixed(1) : '-' },
      { label: '4s',     get: r => r.fours as number },
      { label: '6s',     get: r => r.sixes as number },
      { label: 'vs',     get: r => r.opponent as string },
      { label: 'Venue',  get: r => (r.venue as string) ?? '-' },
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
      { label: 'Econ',     get: r => r.economy != null ? Number(r.economy).toFixed(2) : '-' },
      { label: 'vs',       get: r => r.opponent as string },
      { label: 'Venue',    get: r => (r.venue as string) ?? '-' },
    ],
  },
  { key: 'best_batting_average',title: 'Best Batting Avg',   columns: battingCols('Avg')  },
  { key: 'best_bowling_average',title: 'Best Bowling Avg',   columns: bowlingCols('Avg')  },
]

// Rate stats only - must mirror db/leaderboard_repository.py's qualify
// thresholds (best-batting-average/best-strike-rate: runs >= 50;
// best-bowling-average/best-economy: total_balls >= 30).
const LB_QUALIFIER: Partial<Record<string, string>> = {
  best_strike_rate:     'min. 50 runs',
  best_batting_average: 'min. 50 runs',
  best_economy:         'min. 30 balls bowled',
  best_bowling_average: 'min. 30 balls bowled',
}

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
  useBodyScrollLock(true)

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
                  <RoleBadge role={p.player_role} compact />
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

  useBodyScrollLock(true)

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
          <div className="shrink-0">
            <div className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{meta.title}</div>
            {LB_QUALIFIER[lbKey] && (
              <div className="text-xs" style={{ color: 'var(--text-dim)', opacity: 0.7 }}>
                {LB_QUALIFIER[lbKey]}
              </div>
            )}
          </div>
          <div className="flex-1 flex items-center gap-2 px-3 py-1.5 rounded-lg"
            style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
            <Search size={13} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
            <input
              type="search" autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
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

// ── Challenge leaderboard modal (global, cross-user, same tournament+team+mode) ─
// A different feature from LeaderboardModal above (that one is in-tournament
// batting/bowling stats) - named distinctly to avoid the collision.

function ChallengeLeaderboardModal({
  tournamentId, teamName, mode, onClose,
}: {
  tournamentId: number
  teamName: string
  mode: string
  onClose: () => void
}) {
  const [entries, setEntries] = useState<ChallengeLeaderboardEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useBodyScrollLock(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.getChallengeLeaderboard(getClientId(), tournamentId, teamName, mode)
      .then(r => { if (!cancelled) { setEntries(r.entries); setTotal(r.total_entrants) } })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't load the leaderboard.") })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [tournamentId, teamName, mode])

  const you = entries.find(e => e.is_you)

  return createPortal(
    <>
      <div onClick={onClose}
        style={{ position: 'fixed', inset: 0, zIndex: 160, background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(3px)' }} />
      <div style={{
        position: 'fixed', left: '50%', top: '5vh', transform: 'translateX(-50%)',
        width: 'min(520px, 96vw)', maxHeight: '90vh', zIndex: 161,
        display: 'flex', flexDirection: 'column',
        background: 'var(--bg)', borderRadius: 12, border: '1px solid var(--border)',
        overflow: 'hidden', animation: 'fadeIn 150ms ease',
      }}>
        <div className="flex items-center gap-3 px-4 py-3 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{teamName}</div>
            <div className="text-xs" style={{ color: 'var(--text-dim)' }}>
              {total} {total === 1 ? 'entrant' : 'entrants'} · {mode === 'challenge' ? 'Challenge' : 'Fun'} mode
            </div>
          </div>
          <button onClick={onClose} style={{ color: 'var(--text-muted)', flexShrink: 0 }}><X size={16} /></button>
        </div>

        {loading ? (
          <div className="flex justify-center py-12"><Spinner /></div>
        ) : error ? (
          <div className="px-4 py-8 text-center text-sm" style={{ color: 'var(--text-dim)' }}>{error}</div>
        ) : entries.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm" style={{ color: 'var(--text-dim)' }}>No entrants yet.</div>
        ) : (
          <>
            {you && you.rank !== 1 && (
              <div className="flex items-center gap-3 mx-4 mt-3 mb-1 px-3 py-2.5 rounded-lg flex-shrink-0"
                style={{ background: 'rgba(59,130,246,0.08)', border: '1px solid var(--accent)' }}>
                <RankBadge rank={you.rank} />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold" style={{ color: 'var(--accent)' }}>Your rank</div>
                  <div className="text-sm font-medium truncate" style={{ color: 'var(--accent)' }}>{you.username}</div>
                </div>
                <div className="text-right shrink-0">
                  <PlacementBadge placement={you.best_placement} />
                  <div className="text-xs mt-1" style={{ color: 'var(--text-dim)' }}>
                    {you.swap_count} trade{you.swap_count !== 1 ? 's' : ''} · {(you.win_pct * 100).toFixed(0)}% wins
                  </div>
                </div>
              </div>
            )}
            <div className="flex-1 overflow-y-auto px-4 pb-4 pt-1">
              {entries.map(e => (
                <div key={e.client_id}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg mb-1.5"
                  style={{
                    background: e.is_you ? 'rgba(59,130,246,0.07)' : 'transparent',
                    boxShadow: e.is_you ? 'inset 2px 0 0 var(--accent)' : undefined,
                  }}>
                  <RankBadge rank={e.rank} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate flex items-center gap-1.5" style={{ color: e.is_you ? 'var(--accent)' : 'var(--text)' }}>
                      {e.username}
                      {e.is_you && (
                        <span className="text-xs px-1.5 py-px rounded font-semibold" style={{ background: 'rgba(59,130,246,0.12)', color: 'var(--accent)' }}>You</span>
                      )}
                    </div>
                    <div className="text-xs" style={{ color: 'var(--text-dim)' }}>
                      {e.swap_count} trade{e.swap_count !== 1 ? 's' : ''} · {(e.win_pct * 100).toFixed(0)}% wins
                    </div>
                  </div>
                  <PlacementBadge placement={e.best_placement} />
                </div>
              ))}
            </div>
          </>
        )}
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
    if (v == null) return '-'
    if (typeof v === 'string') return v // e.g. best_bowling_figures' "5/12"
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

type LineupTeam = { team_name: string; players: LineupPlayer[] }

// ── Main component ─────────────────────────────────────────────────────────────

export function ResultsPage() {
  const { simId } = useParams<{ simId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const locState = (location.state ?? {}) as Record<string, unknown>

  const scrollToMatchId = useRef<number | undefined>((locState.scrollTo as number) || undefined)
  const hasScrolled = useRef(false)

  // Simulation lifecycle (pending/running/failed) is owned by SimulatingPage -
  // by the time ResultsPage mounts normally, the sim is already completed.
  // This local status only guards against direct navigation/bookmarks/refresh
  // hitting /results/:simId before it's actually done, in which case we just
  // redirect back to the dedicated loading page instead of rendering it here.
  const [status, setStatus] = useState<'loading' | 'completed'>('loading')
  const [result, setResult] = useState<TournamentResult | null>(null)
  const [leaderboards, setLeaderboards] = useState<LeaderboardsDashboard | null>(null)
  const [matches, setMatches] = useState<MatchItem[]>([])

  const [tab, setTab] = useState<Tab>((locState.tab as Tab) ?? 'standings')
  const [activeLb, setActiveLb] = useState<string | null>(null)
  const [showChallengeLb, setShowChallengeLb] = useState(false)
  // Defaults closed (fail-safe) until the admin kill switch is confirmed on -
  // avoids flashing a button that then has to disappear, and matches this
  // being an emergency-disable feature rather than an opt-in one.
  const [leaderboardsEnabled, setLeaderboardsEnabled] = useState(false)
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
    api.getLeaderboardsEnabled()
      .then(r => setLeaderboardsEnabled(r.enabled))
      .catch(() => setLeaderboardsEnabled(false))
  }, [])

  useEffect(() => {
    if (!simId) return
    let cancelled = false
    async function checkAndLoad() {
      try {
        const s = await api.getSimStatus(simId!)
        if (cancelled) return
        if (s.status !== 'completed') {
          // Not actually done (direct nav/bookmark/refresh hit this too early,
          // or the job failed) - SimulatingPage owns that UI, hand off to it.
          navigate(`/simulating/${simId}`, { replace: true, state: location.state })
          return
        }
        setStatus('completed')
        const clientId = getClientId()
        const [r, lb, m] = await Promise.all([
          api.getSimResult(simId!, clientId),
          api.getLeaderboards(simId!),
          api.getMatches(simId!),
        ])
        if (cancelled) return
        setResult(r)
        setLeaderboards(lb)
        setMatches(m)
        // Pre-fetch lineups for team preview on points-table click
        api.getLineups(simId!).then(l => { if (!cancelled) setLineupTeams(l.teams) })
          .catch(err => console.warn('Team lineups unavailable (non-critical)', err))
      } catch { /* transient error - user can refresh */ }
    }
    checkAndLoad()
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
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

  if (status === 'loading') {
    return (
      <div className="flex flex-col items-center justify-center min-h-[calc(100vh-64px)] gap-4">
        <Spinner size={28} />
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
  const canViewChallengeLeaderboard = leaderboardsEnabled && !!(
    result?.source_tournament_id && result?.user_team_name &&
    (result?.mode === 'challenge' || result?.mode === 'fun')
  )

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

      {/* Challenge leaderboard modal */}
      {showChallengeLb && result?.source_tournament_id && result?.user_team_name && result?.mode && (
        <ChallengeLeaderboardModal
          tournamentId={result.source_tournament_id}
          teamName={result.user_team_name}
          mode={result.mode}
          onClose={() => setShowChallengeLb(false)}
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
        <ChevronLeft size={14} /> Home
      </button>

      {/* Result banner */}
      {result && (() => {
        const placement = result.user_team_placement
        const userTeam = result.user_team_name

        type BannerTheme = { icon: string; headline: string; sub: string; border: string; bg: string; color: string }
        const theme: BannerTheme = (() => {
          // Same medal-ladder colors as SimCard's placement badges: gold/silver/bronze,
          // tinted at low opacity over the real page background (not mixed into
          // --surface-2 at 20-30%, which read as a muddy, low-contrast fill that
          // swallowed the --text-dim/--text-muted sub-text). bg is computed as an
          // opaque color via opaqueTint() rather than a translucent color-mix()/
          // rgba() value - same visual result, but without leaving any alpha
          // compositing for a renderer to get wrong (this tripped up html2canvas
          // during share-screenshot capture even with an explicitly opaque
          // background forced at capture time - removing the translucency here,
          // at the source, sidesteps that regardless of the exact cause).
          if (userTeam) {
            if (placement === 'Winner')    return { icon: '🏆', headline: 'Champions!',             sub: `${userTeam} won the title`,             border: 'var(--score)', bg: opaqueTint('var(--score)', 10), color: 'var(--score)' }
            if (placement === 'Runner-up') return { icon: '💔', headline: 'So close…',              sub: `${userTeam} - Runner-up`,               border: '#C0C0C0',       bg: opaqueTint('#C0C0C0', 10),      color: '#C0C0C0' }
            if (placement === 'Playoffs')  return { icon: '✨', headline: 'You made the Playoffs!', sub: `${userTeam} reached the knockout stage`, border: '#CD7F32',       bg: opaqueTint('#CD7F32', 10),      color: '#CD7F32' }
            return { icon: '😞', headline: 'Did not qualify', sub: `${userTeam} was eliminated in the group stage`, border: 'var(--border)', bg: opaqueTint('#FFFFFF', 6), color: 'var(--text)' }
          }
          return { icon: '🏆', headline: result.winner ? `${result.winner} won the tournament` : 'Tournament complete', sub: '', border: 'var(--score)', bg: opaqueTint('var(--score)', 10), color: 'var(--score)' }
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

        // Buttons sit beside the text (right-aligned, vertically centered)
        // when there's room (md breakpoint and up), stacked below on
        // narrower screens - a real breakpoint rather than flex-wrap, since
        // the text block can always shrink further by wrapping onto more
        // lines instead of actually running out of room, so wrap-on-overflow
        // never actually triggered. Nested one level in from the icon so the
        // stacked button row starts at the same x-position as the headline
        // text above it, not the icon.
        // A flat neutral-gray fill read as a disabled control regardless of
        // text brightness - tinting the button with the banner's own accent
        // (gold/silver/bronze/neutral, same color as theme.border/color)
        // instead makes each banner's buttons feel branded to it rather than
        // generic. A dark outer shadow on an already near-black page just
        // reads as a smear, not lift, so only a faint inward top highlight
        // is used for sheen.
        const buttonStyle: React.CSSProperties = {
          background: opaqueTint(theme.border, 18),
          padding: '6px 10px',
          color: theme.color,
          boxShadow: 'inset 1px 1px 0 rgba(255,255,255,0.07)',
        }
        return (
          <div className="rounded-xl mb-5 fade-in overflow-hidden"
            style={{ border: `0.1px solid ${theme.border}`, background: theme.bg }}>
            <div className="flex items-start gap-3 px-4 py-3">
              <span className="text-2xl shrink-0 leading-none" style={{ marginTop: 4 }}>{theme.icon}</span>
              <div className="flex flex-col md:flex-row md:items-center flex-1 min-w-0">
                <div className="flex-1 min-w-0">
                  <div className="text-base font-bold leading-tight flex items-center gap-2" style={{ color: theme.color }}>
                    {theme.headline}
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: 'var(--text)', lineHeight: 1.5 }}>
                    {theme.sub && <span>{theme.sub}</span>}
                    {result.tournament_name && (
                      <span style={{ color: 'var(--text-dim)' }}>
                        {theme.sub ? ' · ' : ''}{result.tournament_name}{result.season && result.mode !== 'multiplayer' ? ` ${result.season}` : ''} · {result.total_matches} matches
                      </span>
                    )}
                    <FormatBadge format={result.format} className="ml-1.5" />
                  </div>
                  {secondaryLine && (
                    <div className="text-xs mt-1" style={{ color: placement === 'Winner' ? 'var(--text-dim)' : 'var(--score)' }}>{secondaryLine}</div>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0 mt-3 md:mt-0 flex-wrap">
                  {result.room_id && (
                    <button
                      className="btn-outline flex items-center gap-1.5 text-xs"
                      style={buttonStyle}
                      onClick={() => navigate(`/multiplayer/draft/${result.room_id}`)}
                    >
                      <Users size={12} /> Return to Lobby
                    </button>
                  )}
                  {canTryAgain && (
                    <button
                      className="btn-outline flex items-center gap-1.5 text-xs"
                      style={buttonStyle}
                      // A URL query param (not router state) so this also works when
                      // opened from a historical sim, or if the destination page gets
                      // reloaded - FunModePage/ChallengeModePage re-fetch the full
                      // session (tournament, team, swaps) from sim_id on mount rather
                      // than depending on anything carried only in memory.
                      onClick={() => navigate(`/${result!.mode}?retrySimId=${result!.sim_id}`)}
                    >
                      <RotateCcw size={12} /> Try again
                    </button>
                  )}
                  {canViewChallengeLeaderboard && (
                    <button
                      className="btn-outline flex items-center gap-1.5 text-xs"
                      style={buttonStyle}
                      onClick={() => setShowChallengeLb(true)}
                    >
                      <Trophy size={12} /> Leaderboard
                    </button>
                  )}
                  <ShareButton
                    text={tournamentShareText(result)}
                    url={window.location.href}
                    buildImage={() => captureViewportImage(`${result.tournament_name || 'tournament'}-result.png`)}
                    style={buttonStyle}
                  />
                </div>
              </div>
            </div>
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
                case 'best_bowling_figures': return ['best_figures', 0] as const
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
                {m.match_format === 'Test' && m.home_innings && m.home_innings.length > 0 ? (
                  <div className="text-sm font-bold font-mono leading-none"
                    style={{ color: m.winner === m.home_team ? 'var(--score)' : 'var(--text-muted)' }}>
                    {m.home_innings.map((inn, i) => (
                      <span key={i}>{i > 0 ? ' & ' : ''}{inn.runs}/{inn.wkts}</span>
                    ))}
                  </div>
                ) : m.home_score != null ? (
                  <>
                    <div className="text-base font-bold font-mono leading-none"
                      style={{ color: m.winner === m.home_team ? 'var(--score)' : 'var(--text-muted)' }}>
                      {m.home_score}/{m.home_wickets ?? 0}
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>
                      ({m.home_overs ?? '-'} Ov)
                    </div>
                  </>
                ) : (
                  <div className="text-base font-bold" style={{ color: 'var(--text-dim)' }}>-</div>
                )}
              </div>

              <div className="text-sm font-bold shrink-0 px-1" style={{ color: 'var(--text-dim)' }}>vs</div>

              <div className="flex-1 text-right">
                <div className="text-xs font-medium mb-1 truncate"
                  style={{ color: m.winner === m.away_team ? 'var(--text)' : 'var(--text-muted)' }}>
                  {m.away_team}
                </div>
                {m.match_format === 'Test' && m.away_innings && m.away_innings.length > 0 ? (
                  <div className="text-sm font-bold font-mono leading-none"
                    style={{ color: m.winner === m.away_team ? 'var(--score)' : 'var(--text-muted)' }}>
                    {m.away_innings.map((inn, i) => (
                      <span key={i}>{i > 0 ? ' & ' : ''}{inn.runs}/{inn.wkts}</span>
                    ))}
                  </div>
                ) : m.away_score != null ? (
                  <>
                    <div className="text-base font-bold font-mono leading-none"
                      style={{ color: m.winner === m.away_team ? 'var(--score)' : 'var(--text-muted)' }}>
                      {m.away_score}/{m.away_wickets ?? 0}
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>
                      ({m.away_overs ?? '-'} Ov)
                    </div>
                  </>
                ) : (
                  <div className="text-base font-bold" style={{ color: 'var(--text-dim)' }}>-</div>
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
