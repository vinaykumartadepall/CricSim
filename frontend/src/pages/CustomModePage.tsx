import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Search, ArrowUp, ArrowDown, X } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { useHelp } from '@/contexts/HelpContext'
import { hasSeenHelp, markHelpSeen } from '@/config/helpContent'
import { Spinner } from '@/components/ui/Spinner'
import { SimulationTypeToggle } from '@/components/ui/SimulationTypeToggle'
import { FilterDropdown } from '@/components/ui/FilterDropdown'
import { FormatBadge } from '@/components/ui/FormatBadge'
import { RoleBadge } from '@/components/ui/RoleBadge'
import { Headshot } from '@/components/ui/Avatar'
import { BackButton } from '@/components/ui/BackButton'
import { ConfirmRow } from '@/components/ui/ConfirmRow'
import { useVisualViewportHeight } from '@/hooks/useVisualViewportHeight'
import { sortTournamentNames } from '@/lib/sortTournamentNames'
import type { Tournament, Team, Player, MultiplayerPlayer, PlayerFilterOptions } from '@/types'

type Step = 'tournament' | 'season' | 'team' | 'draft' | 'confirm'

const STEPS: Step[] = ['tournament', 'season', 'team', 'draft', 'confirm']
const STEP_LABELS = ['Tournament', 'Season', 'Team', 'Draft XI', 'Simulate']

// ── Squad slot view ────────────────────────────────────────────────────────────

function SquadSlots({
  squad, onMoveUp, onMoveDown, onRemove, homeCountryName,
}: {
  squad: (Player | null)[]
  onMoveUp: (i: number) => void
  onMoveDown: (i: number) => void
  onRemove: (i: number) => void
  homeCountryName?: string | null
}) {
  function isOverseas(p: Player): boolean {
    return !!homeCountryName && !!p.country_name && p.country_name !== homeCountryName
  }

  return (
    <div className="flex flex-col gap-1.5 px-3 py-3 overflow-y-auto flex-1" style={{ minHeight: 0 }}>
      {squad.map((p, idx) => {
        if (!p) {
          return (
            <div key={idx} className="flex items-center gap-3 px-3 py-2 rounded-lg"
              style={{ border: '1px dashed var(--border)', opacity: 0.4 }}>
              <span className="text-xs font-mono w-4 text-right flex-shrink-0" style={{ color: 'var(--text-dim)' }}>{idx + 1}</span>
              <div className="w-7 h-7 rounded-full flex-shrink-0" style={{ background: 'var(--surface-2)' }} />
              <span className="text-xs flex-1" style={{ color: 'var(--text-dim)' }}>Empty</span>
            </div>
          )
        }
        const overseas = isOverseas(p)
        return (
          <div key={`${p.player_id}-${idx}`} className="flex items-center gap-2.5 px-3 py-2 rounded-lg"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
            <span className="text-xs font-mono w-4 text-right flex-shrink-0" style={{ color: 'var(--text-dim)' }}>{idx + 1}</span>
            <Headshot url={p.headshot_url} name={p.player_name} size={28} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 min-w-0">
                <div className="text-xs font-medium truncate" style={{ color: 'var(--text)' }}>{p.player_name}</div>
                {overseas && (
                  <span className="text-[9px] px-1.5 py-px rounded font-bold flex-shrink-0"
                    style={{ background: 'rgba(56,189,248,0.15)', color: '#38bdf8', border: '1px solid rgba(56,189,248,0.35)' }}>
                    ✈
                  </span>
                )}
              </div>
            </div>
            <RoleBadge role={p.player_role} />
            <div className="flex gap-0.5 flex-shrink-0">
              <button onClick={() => onMoveUp(idx)} disabled={idx === 0}
                className="p-1 rounded" style={{ color: idx === 0 ? 'var(--text-dim)' : 'var(--text-muted)', opacity: idx === 0 ? 0.3 : 1 }}>
                <ArrowUp size={12} />
              </button>
              <button onClick={() => onMoveDown(idx)} disabled={idx === 10}
                className="p-1 rounded" style={{ color: idx === 10 ? 'var(--text-dim)' : 'var(--text-muted)', opacity: idx === 10 ? 0.3 : 1 }}>
                <ArrowDown size={12} />
              </button>
              <button onClick={() => onRemove(idx)} className="p-1 rounded ml-0.5" style={{ color: 'var(--text-dim)' }}>
                <X size={12} />
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Pick panel ────────────────────────────────────────────────────────────────

function PickPanel({
  open, onClose, pickedIds, takenByTeam, onPick, overseasCount, overseasLimit, homeCountryName,
}: {
  open: boolean; onClose: () => void
  pickedIds: Set<number>; takenByTeam: Map<number, string>
  onPick: (p: Player) => void
  overseasCount: number; overseasLimit?: number | null; homeCountryName?: string | null
}) {
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Player[]>([])
  const [searching, setSearching] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const viewportHeight = useVisualViewportHeight()

  const [roles, setRoles] = useState<string[]>([])
  const [countryIds, setCountryIds] = useState<number[]>([])
  const [battingStyles, setBattingStyles] = useState<string[]>([])
  const [bowlingStyles, setBowlingStyles] = useState<string[]>([])
  const [filterOptions, setFilterOptions] = useState<PlayerFilterOptions | null>(null)

  useEffect(() => {
    api.getPlayerFilters().then(setFilterOptions).catch(() => setFilterOptions(null))
  }, [])

  function isOverseas(p: Player): boolean {
    return !!homeCountryName && !!p.country_name && p.country_name !== homeCountryName
  }

  function mpToPlayer(mp: MultiplayerPlayer): Player {
    return {
      player_id: mp.player_id,
      player_name: mp.name,
      player_role: mp.role,
      batting_style: mp.batting_style,
      bowling_style: mp.bowling_style,
      headshot_url: mp.headshot_url,
      cricinfo_id: null,
      country_name: mp.country,
    }
  }

  const trimmed = query.trim()
  const hasFilter = roles.length > 0 || countryIds.length > 0 || battingStyles.length > 0 || bowlingStyles.length > 0
  const isSearching = trimmed.length >= 2 || hasFilter

  useEffect(() => {
    if (!isSearching) {
      setSearchResults([])
      setSearching(false)
      return
    }
    setSearching(true)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      api.searchPlayers(trimmed, { roles, countryIds, battingStyles, bowlingStyles })
        .then(data => setSearchResults(data.map(mpToPlayer)))
        .catch(() => setSearchResults([]))
        .finally(() => setSearching(false))
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [trimmed, isSearching, roles, countryIds, battingStyles, bowlingStyles])

  // Reset on close
  useEffect(() => {
    if (!open) {
      setQuery(''); setSearchResults([])
      setRoles([]); setCountryIds([]); setBattingStyles([]); setBowlingStyles([])
    }
  }, [open])

  if (!open) return null

  function renderRow(p: Player) {
    const alreadyPicked = pickedIds.has(p.player_id)
    const takenBy = takenByTeam.get(p.player_id)
    const overseas = isOverseas(p)
    const overseasBlocked = !alreadyPicked && !takenBy && overseas && overseasLimit != null && overseasCount >= overseasLimit
    const isDisabled = alreadyPicked || !!takenBy || overseasBlocked

    const subLabel = takenBy
      ? `Already present in ${takenBy}`
      : overseasBlocked
        ? 'Overseas limit full'
        : null

    return (
      <button key={p.player_id}
        onClick={() => { if (!isDisabled) { onPick(p); onClose() } }}
        aria-disabled={isDisabled}
        className="flex items-center gap-3 px-3 py-2.5 rounded-xl w-full text-left transition-all"
        style={{ opacity: isDisabled ? 0.38 : 1, cursor: isDisabled ? 'not-allowed' : 'pointer' }}
        onMouseEnter={e => { if (!isDisabled) (e.currentTarget as HTMLElement).style.background = 'rgba(168,85,247,0.07)' }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
      >
        <Headshot url={p.headshot_url} name={p.player_name} size={32} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="text-sm font-medium truncate" style={{ color: isDisabled ? 'var(--text-dim)' : 'var(--text)' }}>
              {p.player_name}
              {alreadyPicked && <span className="ml-1.5 text-xs" style={{ color: 'var(--text-dim)' }}>· Picked</span>}
            </span>
            {p.country_name && (
              <span className="text-xs font-normal flex-shrink-0" style={{ color: 'var(--text-dim)' }}>{p.country_name}</span>
            )}
            {overseas && (
              <span className="text-[9px] px-1.5 py-px rounded font-bold flex-shrink-0"
                style={{
                  background: isDisabled ? 'rgba(56,189,248,0.07)' : 'rgba(56,189,248,0.15)',
                  color: isDisabled ? 'rgba(56,189,248,0.4)' : '#38bdf8',
                  border: `1px solid ${isDisabled ? 'rgba(56,189,248,0.15)' : 'rgba(56,189,248,0.35)'}`,
                }}>
                ✈
              </span>
            )}
          </div>
          {subLabel ? (
            <div className="text-xs truncate" style={{ color: 'var(--text-dim)' }}>{subLabel}</div>
          ) : !alreadyPicked && (p.batting_style || p.bowling_style) ? (
            <div className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
              {p.batting_style}{p.bowling_style ? ` · ${p.bowling_style}` : ''}
            </div>
          ) : null}
        </div>
        <RoleBadge role={p.player_role} />
      </button>
    )
  }

  return createPortal(
    <div className="fixed top-0 left-0 right-0 z-50 flex flex-col justify-end md:items-center md:justify-center"
      style={{ height: viewportHeight ?? '100dvh', background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="w-full md:max-w-md rounded-t-2xl md:rounded-2xl flex flex-col overflow-hidden fade-in"
        style={{
          background: 'var(--surface)', border: '1px solid var(--border)',
          maxHeight: viewportHeight ? viewportHeight * 0.85 : '85dvh',
          boxShadow: '0 -8px 32px rgba(0,0,0,0.4)',
        }}>

        <div className="flex justify-center pt-3 pb-1 md:hidden">
          <div className="w-10 h-1 rounded-full" style={{ background: 'var(--border)' }} />
        </div>

        <div className="flex items-center justify-between px-4 py-3 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border)' }}>
          <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Pick a Player</span>
          <button onClick={onClose} style={{ color: 'var(--text-muted)', fontSize: 18, lineHeight: 1 }}>✕</button>
        </div>

        <div className="px-4 py-3 flex-shrink-0 flex flex-col gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: 'var(--text-muted)' }} />
            {/* paddingLeft as an inline style, not the pl-9 utility class: Tailwind
                v4's utilities live in @layer, and .input's own unlayered padding
                shorthand in index.css always wins over any layered utility
                regardless of source order - pl-9 was silently never applying,
                which is why the icon sat on top of the placeholder text. */}
            <input
              className="input w-full"
              style={{ paddingLeft: 34 }}
              placeholder="Search all players…"
              type="search" autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
              value={query}
              onChange={e => setQuery(e.target.value)}
              autoFocus
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <FilterDropdown
              placeholder="All roles"
              values={roles}
              options={(filterOptions?.roles ?? []).map(r => ({ value: r, label: r }))}
              onChange={setRoles}
            />
            <FilterDropdown
              placeholder="All countries"
              values={countryIds.map(String)}
              searchable
              options={(filterOptions?.countries ?? []).map(c => ({ value: String(c.country_id), label: c.name }))}
              onChange={vals => setCountryIds(vals.map(Number))}
            />
            <FilterDropdown
              placeholder="Any bat type"
              values={battingStyles}
              options={(filterOptions?.batting_styles ?? []).map(b => ({ value: b, label: b }))}
              onChange={setBattingStyles}
            />
            <FilterDropdown
              placeholder="Any bowl type"
              values={bowlingStyles}
              options={(filterOptions?.bowling_styles ?? []).map(b => ({ value: b, label: b }))}
              onChange={setBowlingStyles}
            />
          </div>
          {!isSearching && (
            <div className="text-xs px-1" style={{ color: 'var(--text-dim)' }}>
              Type 2+ characters or use a filter to search all players
            </div>
          )}
        </div>

        <div className="overflow-y-auto flex-1 px-2 pb-4" style={{ minHeight: 0 }}>
          {!isSearching ? (
            <div className="flex flex-col items-center justify-center py-12 gap-2">
              <div className="text-2xl">🏏</div>
              <div className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>Search to find players</div>
              <div className="text-xs text-center px-6" style={{ color: 'var(--text-dim)' }}>
                Search across all players in the database
              </div>
            </div>
          ) : searching ? (
            <div className="flex justify-center py-8">
              <div className="w-5 h-5 rounded-full border-2 border-t-transparent spin" style={{ borderColor: '#a855f7', borderTopColor: 'transparent' }} />
            </div>
          ) : searchResults.length === 0 ? (
            <div className="text-center py-6 text-sm" style={{ color: 'var(--text-dim)' }}>
              {trimmed ? `No players found for "${trimmed}"` : 'No players found'}
            </div>
          ) : (
            <>
              <div className="px-3 py-1.5 text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>
                {searchResults.length} result{searchResults.length !== 1 ? 's' : ''}
              </div>
              {searchResults.map(p => renderRow(p))}
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function CustomModePage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { clientId } = useAuth()
  const { openHelp } = useHelp()

  const [step, setStep] = useState<Step>('tournament')
  const [search, setSearch] = useState('')
  const [tournaments, setTournaments] = useState<Tournament[]>([])
  const [loadingTournaments, setLoadingTournaments] = useState(false)

  const [tournamentName, setTournamentName] = useState('')
  const [seasons, setSeasons] = useState<Tournament[]>([])
  const [selectedSeason, setSelectedSeason] = useState<Tournament | null>(null)

  const [allTeams, setAllTeams] = useState<Team[]>([])
  const [loadingTeams, setLoadingTeams] = useState(false)
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null)

  // Squad: 11 slots, null = empty
  const [squad, setSquad] = useState<(Player | null)[]>(Array(11).fill(null))
  const [pickPanelOpen, setPickPanelOpen] = useState(false)

  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  // Keeps the URL as the durable record of "where am I" (tournament + team +
  // step) so reload/back/forward/history land back in the right place instead
  // of resetting to step 1. The squad itself (11 in-progress picks) is
  // deliberately NOT restored this way - same reasoning as swaps in Fun/
  // Challenge Mode: it's frequently-mutated, fiddly to serialize, and not
  // worth the URL noise. Reloading mid-draft restores the right team, with an
  // empty XI to re-pick, rather than resetting all the way to step 1.
  function updateUrlParams(patch: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams)
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) next.delete(k)
      else next.set(k, v)
    }
    setSearchParams(next, { replace: true })
  }

  function goToStep(newStep: Step, extra?: Record<string, string | undefined>) {
    setStep(newStep)
    updateUrlParams({ step: newStep, ...extra })
  }

  // URL-driven restore on mount - Custom Mode has no retrySimId/try-again flow
  // (there's nothing to trade), so this is the only restoration path.
  useEffect(() => {
    const urlTournamentId = searchParams.get('tournament_id')
    if (!urlTournamentId) return
    const tid = Number(urlTournamentId)
    const urlTeamId = searchParams.get('team_id')
    api.getTournaments().then(all => {
      const t = all.find(x => x.tournament_id === tid)
      if (!t) return
      setTournamentName(t.name)
      setSelectedSeason(t)
      setLoadingTeams(true)
      return api.getTournamentSquads(tid)
        .then(data => {
          const teams = data.teams || []
          setAllTeams(teams)
          const team = urlTeamId ? teams.find(tm => tm.team_id === Number(urlTeamId)) ?? null : null
          if (team) {
            // Always land on 'draft', never 'confirm' - the squad itself isn't
            // restorable, so 'confirm' would show a broken empty-XI state.
            setSelectedTeam(team)
            setStep('draft')
          } else {
            setStep('team')
          }
        })
        .catch(() => setAllTeams([]))
        .finally(() => setLoadingTeams(false))
    }).catch(err => console.warn('Failed to restore build from URL context', err))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const stepIndex = STEPS.indexOf(step)
  const pickedCount = squad.filter(Boolean).length
  const pickedIds = useMemo(() => new Set(squad.filter(Boolean).map(p => p!.player_id)), [squad])
  const hasKeeper = useMemo(() => squad.filter(Boolean).some(p => p!.player_role === 'Keeper'), [squad])

  const overseasCount = useMemo(() => {
    if (!selectedSeason?.home_country_name) return 0
    const home = selectedSeason.home_country_name
    return squad.filter(Boolean).filter(p => !!p!.country_name && p!.country_name !== home).length
  }, [squad, selectedSeason])

  const overseasExceeded = !!(selectedSeason?.overseas_limit && overseasCount > selectedSeason.overseas_limit)

  // Players already in other teams' seeded squads - player_id → team_name
  const takenByTeam = useMemo(() => {
    const map = new Map<number, string>()
    for (const team of allTeams) {
      if (team.team_id === selectedTeam?.team_id) continue
      for (const player of team.players) {
        map.set(player.player_id, team.team_name)
      }
    }
    return map
  }, [allTeams, selectedTeam])

  // Step-based help (draft step auto-shows slide 1; other steps show slide 0),
  // shown the first time each step is reached
  useEffect(() => {
    const slideMap: Partial<Record<Step, number>> = { tournament: 0, draft: 1 }
    const slide = slideMap[step]
    if (slide === undefined) return
    const key = `/custom#${step}`
    if (!hasSeenHelp(key)) {
      markHelpSeen(key)
      openHelp(slide, true)
    }
  }, [step]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setLoadingTournaments(true)
    api.getTournaments(search || undefined)
      .then(data => setTournaments(data))
      .catch(() => setTournaments([]))
      .finally(() => setLoadingTournaments(false))
  }, [search])

  const grouped = useMemo(() => tournaments.reduce<Record<string, Tournament[]>>((acc, t) => {
    if (!acc[t.name]) acc[t.name] = []
    acc[t.name].push(t)
    return acc
  }, {}), [tournaments])
  const uniqueNames = sortTournamentNames(Object.keys(grouped))

  function selectTournamentName(name: string) {
    setTournamentName(name)
    setSeasons((grouped[name] || []).sort((a, b) => b.season.localeCompare(a.season)))
    setSelectedSeason(null)
    setStep('season')
    updateUrlParams({ tournament_id: undefined, team_id: undefined, step: 'season' })
  }

  function selectSeason(t: Tournament) {
    setSelectedSeason(t)
    setLoadingTeams(true)
    setAllTeams([])
    setSelectedTeam(null)
    setSquad(Array(11).fill(null))
    api.getTournamentSquads(t.tournament_id)
      .then(data => setAllTeams(data.teams || []))
      .catch(() => setAllTeams([]))
      .finally(() => setLoadingTeams(false))
    setStep('team')
    updateUrlParams({ tournament_id: String(t.tournament_id), team_id: undefined, step: 'team' })
  }

  function selectTeam(team: Team) {
    setSelectedTeam(team)
    setSquad(Array(11).fill(null))
    setStep('draft')
    updateUrlParams({ team_id: String(team.team_id), step: 'draft' })
  }

  const pickPlayer = useCallback((player: Player) => {
    setSquad(prev => {
      const slot = prev.findIndex(s => s === null)
      if (slot === -1) return prev
      const next = [...prev]
      next[slot] = player
      return next
    })
  }, [])

  function moveUp(i: number) {
    if (i === 0) return
    setSquad(prev => { const n = [...prev]; [n[i-1], n[i]] = [n[i], n[i-1]]; return n })
  }

  function moveDown(i: number) {
    if (i === 10) return
    setSquad(prev => { const n = [...prev]; [n[i], n[i+1]] = [n[i+1], n[i]]; return n })
  }

  function removeFromSquad(i: number) {
    setSquad(prev => { const n = [...prev]; n[i] = null; return n })
  }

  async function runSim() {
    if (!selectedSeason || !selectedTeam) return
    setRunning(true)
    setError('')
    try {
      const battingOrder = squad.filter(Boolean).map(p => p!.player_id)
      const { sim_id } = await api.startTournamentSim({
        tournament_id: selectedSeason.tournament_id,
        team_id: selectedTeam.team_id,
        mode: 'custom',
        client_id: clientId,
        swaps: [],
        batting_order: battingOrder,
      })
      navigate(`/simulating/${sim_id}`, {
        state: {
          origin: 'custom',
          tournamentId: selectedSeason.tournament_id,
          teamId: selectedTeam.team_id,
          tournamentName,
          season: selectedSeason.season,
          teamName: selectedTeam.team_name,
        },
      })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start simulation')
      setRunning(false)
    }
  }

  // ── Draft step is full-screen ─────────────────────────────────────────────────
  if (step === 'draft' && selectedTeam) {
    return (
      <>
        <div className="flex flex-col" style={{ height: 'calc(100dvh - 60px)', background: 'var(--bg)' }}>
          {/* Header */}
          <div className="flex-shrink-0 px-4 py-3 flex items-center justify-between"
            style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
            <div>
              <div className="flex items-center gap-2">
                <button onClick={() => goToStep('team')} style={{ color: 'var(--text-dim)', lineHeight: 0 }}>
                  <ChevronLeft size={16} />
                </button>
                <div className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                  {selectedTeam.team_name}
                </div>
              </div>
              <div className="text-xs ml-6" style={{ color: 'var(--text-muted)' }}>
                {tournamentName} {selectedSeason?.season}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {selectedSeason?.overseas_limit != null && (
                <div
                  className="text-xs font-semibold px-2.5 py-1 rounded-full"
                  style={{
                    background: overseasExceeded ? 'rgba(239,68,68,0.12)' : 'rgba(56,189,248,0.1)',
                    color: overseasExceeded ? 'var(--loss)' : '#38bdf8',
                    border: `1px solid ${overseasExceeded ? 'rgba(239,68,68,0.3)' : 'rgba(56,189,248,0.25)'}`,
                  }}
                >
                  ✈ {overseasCount}/{selectedSeason.overseas_limit}
                  {overseasExceeded && ' ⚠'}
                </div>
              )}
              <div
                className="text-sm font-semibold px-3 py-1 rounded-full"
                style={{
                  background: pickedCount === 11 ? 'rgba(59,130,246,0.15)' : 'var(--surface-2)',
                  color: pickedCount === 11 ? 'var(--accent)' : 'var(--text-muted)',
                }}
              >
                {pickedCount}/11
              </div>
            </div>
          </div>

          {/* Squad slots */}
          <SquadSlots squad={squad} onMoveUp={moveUp} onMoveDown={moveDown} onRemove={removeFromSquad} homeCountryName={selectedSeason?.home_country_name} />

          {/* Bottom button */}
          <div className="flex-shrink-0 p-3" style={{ borderTop: '1px solid var(--border)' }}>
            {pickedCount < 11 ? (
              <button
                onClick={() => setPickPanelOpen(true)}
                className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all"
                style={{ background: '#a855f7', color: '#fff', boxShadow: '0 4px 16px rgba(168,85,247,0.4)' }}
              >
                Pick player {pickedCount + 1} of 11
              </button>
            ) : (
              <>
                {!hasKeeper && (
                  <div className="mb-2 px-3 py-2 rounded-lg text-xs text-center"
                    style={{ background: 'rgba(239,68,68,0.08)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.2)' }}>
                    No wicket-keeper in your squad - remove a player and add a keeper.
                  </div>
                )}
                {overseasExceeded && (
                  <div className="mb-2 px-3 py-2 rounded-lg text-xs text-center"
                    style={{ background: 'rgba(239,68,68,0.08)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.2)' }}>
                    ✈ Too many overseas players ({selectedSeason?.overseas_limit} max) - remove one to continue.
                  </div>
                )}
                <button
                  onClick={() => goToStep('confirm')}
                  disabled={!hasKeeper || overseasExceeded}
                  className="w-full py-3 rounded-xl font-semibold text-sm transition-all"
                  style={{ background: 'var(--accent)', color: 'var(--bg)', opacity: (!hasKeeper || overseasExceeded) ? 0.45 : 1, cursor: (!hasKeeper || overseasExceeded) ? 'not-allowed' : undefined }}
                >
                  Continue →
                </button>
              </>
            )}
          </div>
        </div>

        <PickPanel
          open={pickPanelOpen}
          onClose={() => setPickPanelOpen(false)}
          pickedIds={pickedIds}
          takenByTeam={takenByTeam}
          onPick={pickPlayer}
          overseasCount={overseasCount}
          overseasLimit={selectedSeason?.overseas_limit}
          homeCountryName={selectedSeason?.home_country_name}
        />
      </>
    )
  }

  // ── Stepped flow (tournament / season / team / confirm) ───────────────────────
  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      {/* Mode label */}
      <div className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: '#a855f7' }}>
        Custom Mode
      </div>
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 mb-8 flex-wrap">
        {STEP_LABELS.map((label, i) => (
          <div key={label} className="flex items-center gap-1">
            <div className="flex items-center gap-1.5 text-sm"
              style={{ color: i <= stepIndex ? '#a855f7' : 'var(--text-dim)' }}>
              <span className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-semibold"
                style={{
                  background: i < stepIndex ? '#a855f7' : i === stepIndex ? 'rgba(168,85,247,0.15)' : 'var(--surface-2)',
                  color: i < stepIndex ? '#fff' : i === stepIndex ? '#a855f7' : 'var(--text-dim)',
                  border: i === stepIndex ? '1px solid #a855f7' : 'none',
                }}>
                {i + 1}
              </span>
              <span className="hidden sm:inline">{label}</span>
            </div>
            {i < STEP_LABELS.length - 1 && <ChevronRight size={14} style={{ color: 'var(--text-dim)' }} />}
          </div>
        ))}
      </div>

      {/* Step: Tournament */}
      {step === 'tournament' && (
        <div className="fade-in">
          <BackButton onClick={() => navigate('/play')} />
          <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>Select tournament</div>
          <div className="text-sm mb-5" style={{ color: 'var(--text-muted)' }}>Choose a tournament to build your XI for</div>
          <input className="input mb-4" placeholder="Search tournaments…"
            type="search" autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
            value={search} onChange={e => setSearch(e.target.value)} />
          {loadingTournaments ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : (
            <div className="flex flex-col gap-2">
              {uniqueNames.map(name => (
                <button key={name} onClick={() => selectTournamentName(name)}
                  className="card-sm flex items-center justify-between px-4 py-3 cursor-pointer w-full text-left transition-all"
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = '#a855f7'}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}>
                  <div className="flex flex-col gap-0.5">
                    <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{name}</span>
                    <FormatBadge format={grouped[name][0]?.format} className="self-start" />
                  </div>
                  <span className="text-xs shrink-0" style={{ color: 'var(--text-dim)' }}>
                    {grouped[name].length} season{grouped[name].length > 1 ? 's' : ''}
                  </span>
                </button>
              ))}
              {uniqueNames.length === 0 && (
                <div className="text-sm text-center py-8" style={{ color: 'var(--text-dim)' }}>No tournaments found</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Step: Season */}
      {step === 'season' && (
        <div className="fade-in">
          <BackButton onClick={() => goToStep('tournament')} />
          <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>{tournamentName}</div>
          <div className="text-sm mb-5" style={{ color: 'var(--text-muted)' }}>Select a season</div>
          <div className="flex flex-col gap-2">
            {seasons.map(s => (
              <button key={s.tournament_id} onClick={() => selectSeason(s)}
                className="card-sm flex items-center justify-between px-4 py-3 cursor-pointer w-full text-left transition-all"
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = '#a855f7'}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}>
                <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{s.season} Season</span>
                <span className="text-xs shrink-0" style={{ color: 'var(--text-dim)' }}>{s.team_count} teams</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Step: Team */}
      {step === 'team' && (
        <div className="fade-in">
          <BackButton onClick={() => goToStep('season')} />
          <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>
            {tournamentName} {selectedSeason?.season}
          </div>
          <div className="text-sm mb-5" style={{ color: 'var(--text-muted)' }}>
            Pick a team - you'll build their XI from scratch
          </div>
          {loadingTeams ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {allTeams.map(team => (
                <button key={team.team_id} onClick={() => selectTeam(team)}
                  className="card-sm px-3 py-3 cursor-pointer text-left transition-all"
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = '#a855f7'}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}>
                  <div className="text-sm font-medium leading-snug" style={{ color: 'var(--text)' }}>{team.team_name}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Step: Confirm */}
      {step === 'confirm' && selectedTeam && (
        <div className="fade-in">
          <BackButton onClick={() => goToStep('draft')} />
          <div className="text-xl font-semibold mb-5" style={{ color: 'var(--text)' }}>Ready to simulate</div>

          <div className="card p-5 mb-4 space-y-3">
            <ConfirmRow label="Tournament" value={`${tournamentName} ${selectedSeason?.season}`} />
            <ConfirmRow label="Playing as" value={selectedTeam.team_name} />
            <div className="flex items-center justify-between">
              <span className="text-sm" style={{ color: 'var(--text-muted)' }}>Mode</span>
              <span className="text-sm font-medium px-2 py-0.5 rounded-full"
                style={{ background: 'rgba(168,85,247,0.15)', color: '#a855f7' }}>
                Custom
              </span>
            </div>
          </div>

          {/* XI preview */}
          <div className="card p-4 mb-6">
            <div className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: 'var(--text-dim)' }}>
              Your XI (batting order)
            </div>
            <div className="flex flex-col gap-1.5">
              {squad.filter(Boolean).map((p, i) => (
                <div key={p!.player_id} className="flex items-center gap-2">
                  <span className="text-xs w-5 text-right flex-shrink-0" style={{ color: 'var(--text-dim)' }}>{i + 1}</span>
                  <Headshot url={p!.headshot_url} name={p!.player_name} size={22} />
                  <span className="text-sm flex-1 truncate" style={{ color: 'var(--text)' }}>{p!.player_name}</span>
                  <RoleBadge role={p!.player_role} />
                </div>
              ))}
            </div>
          </div>

          <div className="mb-6">
            <SimulationTypeToggle />
          </div>

          {error && (
            <div className="text-sm mb-4 px-3 py-2 rounded-lg"
              style={{ background: 'rgba(239,68,68,0.1)', color: 'var(--loss)' }}>
              {error}
            </div>
          )}

          <button
            className="w-full flex items-center justify-center gap-2 text-base py-3 rounded-xl font-semibold"
            style={{ background: '#a855f7', color: '#fff', opacity: running ? 0.7 : 1 }}
            onClick={runSim} disabled={running}
          >
            {running ? <><Spinner size={16} /> Running…</> : '▶  Simulate'}
          </button>
        </div>
      )}
    </div>
  )
}

