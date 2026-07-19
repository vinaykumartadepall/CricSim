import { useState, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, TrendingDown, Search, Globe, Trophy } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { useHelp } from '@/contexts/HelpContext'
import { hasSeenHelp, markHelpSeen } from '@/config/helpContent'
import { Spinner } from '@/components/ui/Spinner'
import { SimulationTypeToggle } from '@/components/ui/SimulationTypeToggle'
import { FormatBadge } from '@/components/ui/FormatBadge'
import { PlacementBadge, medalColor } from '@/components/ui/PlacementBadge'
import { BackButton } from '@/components/ui/BackButton'
import { ConfirmRow } from '@/components/ui/ConfirmRow'
import { SquadEditor } from '@/components/SquadEditor'
import { ChallengeLeaderboardModal } from '@/components/ChallengeLeaderboardModal'
import { useWizardUrlState } from '@/hooks/useWizardUrlState'
import { sortTournamentNames } from '@/lib/sortTournamentNames'
import type { Tournament, Team, SwapEntry, SimHistoryNameCount, SimHistoryTeamBest, MyTeamRankItem } from '@/types'


type Step = 'pick_tournament' | 'pick_team_season' | 'squad' | 'confirm'

interface UnderdogEntry {
  team_id: number
  team_name: string
  tournament_id: number
  season: string
  wins: number
  total_matches: number
  win_pct: number
}

const STEP_LABELS: Record<Step, string> = {
  pick_tournament:  'Tournament',
  pick_team_season: 'Pick Team',
  squad:            'Edit Squad',
  confirm:          'Simulate',
}
const STEP_ORDER: Step[] = ['pick_tournament', 'pick_team_season', 'squad', 'confirm']

const CHALLENGE_STEP_SLIDE: Partial<Record<Step, number>> = {
  pick_tournament: 0,
  pick_team_season: 0,
  squad: 1,
}

export function ChallengeModePage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const retrySimId = searchParams.get('retrySimId')
  const { openHelp } = useHelp()
  const [step, setStep] = useState<Step>('pick_tournament')

  // Tournament name pick
  const [search, setSearch] = useState('')
  const [allTournaments, setAllTournaments] = useState<Tournament[]>([])
  const [loadingTournaments, setLoadingTournaments] = useState(false)
  const [selectedName, setSelectedName] = useState('')

  // Underdog team+season pick
  const [underdogs, setUnderdogs] = useState<UnderdogEntry[]>([])
  const [loadingUnderdogs, setLoadingUnderdogs] = useState(false)
  const [underdogError, setUnderdogError] = useState('')
  const [selectedEntry, setSelectedEntry] = useState<UnderdogEntry | null>(null)

  // Squad
  const [allTeams, setAllTeams] = useState<Team[]>([])
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null)
  const [loadingSquad, setLoadingSquad] = useState(false)
  const [swaps, setSwaps] = useState<SwapEntry[]>([])
  const [battingOrder, setBattingOrder] = useState<number[]>([])

  // Sim history
  const [nameCounts, setNameCounts] = useState<Map<string, SimHistoryNameCount>>(new Map())
  // keyed by `${team_name}-${tournament_id}`
  const [teamBest, setTeamBest] = useState<Map<string, SimHistoryTeamBest>>(new Map())
  const [teamRanks, setTeamRanks] = useState<Map<string, MyTeamRankItem>>(new Map())

  // Leaderboard preview - lets you see a team's global leaderboard before
  // ever picking it. The pick_team_season step's button navigates to a real
  // page (LeaderboardPage) since it needs to browse many teams first - a
  // popup stacked on this wizard's own flow didn't read well there. The
  // squad step already has one specific team+tournament though (no browsing
  // needed), so its button reuses the plain single-leaderboard popup - same
  // shape ResultsPage already uses.
  const [leaderboardsEnabled, setLeaderboardsEnabled] = useState(false)
  const [showSquadLeaderboard, setShowSquadLeaderboard] = useState(false)

  useEffect(() => {
    api.getLeaderboardsEnabled()
      .then(r => setLeaderboardsEnabled(r.enabled))
      .catch(() => setLeaderboardsEnabled(false))
  }, [])

  // Confirm
  const { clientId, authReady } = useAuth()
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  // Set when a retry/URL restore couldn't fully recover the previous build
  // (fetch failure, or the previously-picked team/tournament no longer
  // resolves) - shown as a banner rather than silently landing somewhere
  // unexplained.
  const [restoreNotice, setRestoreNotice] = useState('')

  const { updateUrlParams, goToStep } = useWizardUrlState<Step>(setStep)

  // Shared by pickName(), the retry flow, and the URL-restore effect below -
  // previously the retry flow fetched underdogs on its own without fetching
  // teamBest, so going back to the pick_team_season step after a retry showed
  // no "best result" line for any entry, even with real history.
  function loadUnderdogs(name: string): Promise<UnderdogEntry[]> {
    setLoadingUnderdogs(true)
    setUnderdogError('')
    setTeamBest(new Map())
    setTeamRanks(new Map())
    return api.getUnderdogs(name)
      .then(data => {
        setUnderdogs(data)
        if (data.length === 0) {
          setUnderdogError('No underdog teams found - all teams win > 33% of matches in every season')
          return data
        }
        const uniqueTids = [...new Set(data.map(e => e.tournament_id))]
        Promise.all(
          uniqueTids.map(tid =>
            api.getMyChallengeRanks(clientId, tid, 'challenge')
              .then(rows => rows.map(r => ({ ...r, tournament_id: tid })))
              .catch(() => [] as (MyTeamRankItem & { tournament_id: number })[])
          )
        ).then(results => {
          const map = new Map<string, MyTeamRankItem>()
          results.flat().forEach(r => map.set(`${r.team_name}-${r.tournament_id}`, r))
          setTeamRanks(map)
        })
        return Promise.all(
          uniqueTids.map(tid =>
            api.getSimHistoryBest(clientId, tid, 'challenge')
              .then(rows => rows.map(r => ({ ...r, tournament_id: tid })))
              .catch(() => [] as (SimHistoryTeamBest & { tournament_id: number })[])
          )
        ).then(results => {
          const map = new Map<string, SimHistoryTeamBest>()
          results.flat().forEach(r => map.set(`${r.team_name}-${r.tournament_id}`, r))
          setTeamBest(map)
          return data
        })
      })
      .catch(() => {
        setUnderdogError('Failed to load teams')
        return [] as UnderdogEntry[]
      })
      .finally(() => setLoadingUnderdogs(false))
  }

  // Shared by pickEntry() and the URL-restore effect below.
  function loadTeamForTournament(tournamentId: number, teamId: number | null): Promise<Team | null> {
    setLoadingSquad(true)
    return api.getTournamentSquads(tournamentId)
      .then(data => {
        const teams = data.teams || []
        setAllTeams(teams)
        const team = teamId ? teams.find(t => t.team_id === teamId) ?? null : null
        if (team) {
          setSelectedTeam(team)
          setBattingOrder(team.players.map(p => p.player_id))
        }
        return team
      })
      .catch(err => {
        console.warn('Failed to load team squads for tournament', err)
        return null
      })
      .finally(() => setLoadingSquad(false))
  }

  // Unified restore path - both the retry flow (?retrySimId=) and the plain
  // URL-restore (name/tournament_id/team_id/step surviving in the URL after
  // a reload or back-navigation) fetch through this one awaited function, so
  // there's exactly one place that decides which step to land on and exactly
  // one failure path - instead of several independent fire-and-forget chains
  // that could each silently do nothing (this file's history of one-off
  // patches, e.g. the loadUnderdogs/teamBest comment above, came from
  // exactly that shape).
  async function restoreTo(
    target: { name: string; tournamentId?: number; teamId?: number; season?: string; urlStep?: string | null; swaps?: SwapEntry[] },
    isCancelled: () => boolean,
  ) {
    setSelectedName(target.name)
    const underdogs = await loadUnderdogs(target.name)
    if (isCancelled()) return

    if (!target.tournamentId || !target.teamId) {
      // Only the tournament name is restorable (or nothing deeper resolved) -
      // land on the team/season list, which now has its data loaded.
      setStep('pick_team_season')
      updateUrlParams({ retrySimId: undefined, name: target.name, tournament_id: undefined, team_id: undefined, step: 'pick_team_season' })
      return
    }

    const tournamentId = target.tournamentId
    const teamId = target.teamId
    const team = await loadTeamForTournament(tournamentId, teamId)
    if (isCancelled()) return
    if (!team) {
      setRestoreNotice('That team pick is no longer available - pick again below.')
      setStep('pick_team_season')
      updateUrlParams({ retrySimId: undefined, name: target.name, tournament_id: undefined, team_id: undefined, step: 'pick_team_season' })
      return
    }

    const entry = underdogs.find(e => e.tournament_id === tournamentId && e.team_id === teamId)
    setSelectedEntry(entry ?? {
      tournament_id: tournamentId, team_id: team.team_id, team_name: team.team_name,
      season: target.season ?? '', wins: 0, total_matches: 0, win_pct: 0,
    })
    if (target.swaps) setSwaps(target.swaps)
    const finalStep = target.urlStep === 'pick_team_season' ? 'pick_team_season' : target.urlStep === 'confirm' ? 'confirm' : 'squad'
    setStep(finalStep)
    // retrySimId is cleared here (not in a follow-up call after restoreTo
    // returns) so it lands in the same URL update as the restored step/team
    // params, instead of racing a stale searchParams closure that could
    // clobber what this call just set.
    updateUrlParams({
      retrySimId: undefined, name: target.name, tournament_id: String(tournamentId), team_id: String(teamId), step: finalStep,
    })
  }

  // Try-again resume flow - driven by a URL query param (?retrySimId=) and a
  // fresh fetch of that session, rather than router state carried in memory,
  // so this also works when landing here from a historical sim (My
  // Simulations) or after a reload of this very page, not just immediately
  // after finishing a fresh run. Gated on authReady so it always resolves
  // history with the final client_id, never a stale pre-link anon one.
  useEffect(() => {
    if (!retrySimId || !authReady) return
    let cancelled = false
    api.getSimResult(retrySimId, clientId)
      .then(result => {
        if (cancelled) return undefined
        if (!result?.source_tournament_id || !result?.user_team_name) {
          throw new Error('Incomplete sim result for retry')
        }
        return restoreTo({
          name: result.tournament_name ?? '',
          tournamentId: result.source_tournament_id,
          teamId: result.user_team_id ?? undefined,
          season: result.season ?? undefined,
          urlStep: 'squad',
          swaps: result.swaps ?? [],
        }, () => cancelled)
      })
      .catch(err => {
        if (cancelled) return
        console.warn('Failed to restore previous run for Try Again', err)
        setRestoreNotice("Couldn't restore your last attempt - pick a tournament to start again.")
      })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady])

  // URL-driven restore for a fresh (not-yet-simulated) build, or for a reload
  // / back-navigation mid-build - covers every step from pick_team_season
  // onward. Only fires when retrySimId isn't in play, since that flow is
  // authoritative (it also restores swaps, which this can't).
  useEffect(() => {
    if (retrySimId || !authReady) return
    const name = searchParams.get('name')
    const urlTournamentId = searchParams.get('tournament_id')
    const urlTeamId = searchParams.get('team_id')
    const urlStep = searchParams.get('step')
    if (!name && !urlTournamentId) return
    let cancelled = false
    ;(async () => {
      try {
        let resolvedName = name
        if (!resolvedName) {
          const all = await api.getTournaments()
          if (cancelled) return
          const t = all.find(x => x.tournament_id === Number(urlTournamentId))
          if (!t) throw new Error('Tournament not found for restore')
          resolvedName = t.name
        }
        await restoreTo({
          name: resolvedName,
          tournamentId: urlTournamentId ? Number(urlTournamentId) : undefined,
          teamId: urlTeamId ? Number(urlTeamId) : undefined,
          urlStep,
        }, () => cancelled)
      } catch (err) {
        if (cancelled) return
        console.warn('Failed to restore build from URL context', err)
        setRestoreNotice("Couldn't restore your previous session - pick a tournament to start again.")
      }
    })()
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady])

  useEffect(() => {
    setLoadingTournaments(true)
    api.getTournaments(search || undefined)
      .then(data => setAllTournaments(data))
      .catch(() => setAllTournaments([]))
      .finally(() => setLoadingTournaments(false))
  }, [search])

  useEffect(() => {
    api.getSimHistoryNameCounts(clientId, 'challenge', search || undefined)
      .then(data => setNameCounts(new Map(data.map(r => [r.name, r]))))
      .catch(err => console.warn('Sim-history name counts unavailable (non-critical)', err))
  }, [clientId, search])

  // Group by name for step 1 (same pattern as FunModePage)
  const grouped = allTournaments.reduce<Record<string, Tournament[]>>((acc, t) => {
    if (!acc[t.name]) acc[t.name] = []
    acc[t.name].push(t)
    return acc
  }, {})
  const uniqueNames = sortTournamentNames(Object.keys(grouped))

  function pickName(name: string) {
    setRestoreNotice('')
    setSelectedName(name)
    setSelectedEntry(null)
    setAllTeams([])
    setSelectedTeam(null)
    setSwaps([])
    setStep('pick_team_season')
    updateUrlParams({ name, tournament_id: undefined, team_id: undefined, step: 'pick_team_season' })
    loadUnderdogs(name)
  }

  function pickEntry(entry: UnderdogEntry) {
    setRestoreNotice('')
    setSelectedEntry(entry)
    setSwaps([])
    setSelectedTeam(null)
    setStep('squad')
    updateUrlParams({ name: selectedName, tournament_id: String(entry.tournament_id), team_id: String(entry.team_id), step: 'squad' })
    loadTeamForTournament(entry.tournament_id, entry.team_id).then(team => {
      if (!team) {
        // Squad fetch failed or team not found in the tournament's squads -
        // still show a placeholder rather than dead-ending the step.
        setSelectedTeam({ team_id: entry.team_id, team_name: entry.team_name, players: [] })
        setBattingOrder([])
      }
    })
  }

  async function runSim() {
    if (!selectedEntry || !selectedTeam) return
    setRunning(true)
    setError('')
    try {
      const { sim_id } = await api.startTournamentSim({
        tournament_id: selectedEntry.tournament_id,
        team_id: selectedTeam.team_id,
        mode: 'challenge',
        client_id: clientId,
        swaps: swaps.map(s => ({
          player_out_id: s.player_out_id,
          player_in_id: s.player_in_id,
          from_team_id: s.from_team_id,
        })),
        batting_order: battingOrder.length > 0 ? battingOrder : undefined,
      })
      navigate(`/simulating/${sim_id}`, {
        state: {
          origin: 'challenge',
          tournamentId: selectedEntry!.tournament_id,
          teamId: selectedTeam!.team_id,
          tournamentName: selectedName,
          season: selectedEntry!.season,
          teamName: selectedTeam!.team_name,
        },
      })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start simulation')
      setRunning(false)
    }
  }

  const hasKeeper = useMemo(() => {
    if (!selectedTeam) return true
    const allPlayers = allTeams.flatMap(t => t.players)
    const swapMap = new Map(swaps.map(s => [s.player_out_id, s]))
    return selectedTeam.players.some(p => {
      const swap = swapMap.get(p.player_id)
      if (swap) {
        const inPlayer = allPlayers.find(pl => pl.player_id === swap.player_in_id)
        return inPlayer?.player_role === 'Keeper'
      }
      return p.player_role === 'Keeper'
    })
  }, [selectedTeam, swaps, allTeams])

  const selectedTournament = useMemo(() =>
    allTournaments.find(t => t.tournament_id === selectedEntry?.tournament_id) ?? null
  , [allTournaments, selectedEntry])

  const overseasValid = useMemo(() => {
    if (!selectedTeam || !selectedTournament?.overseas_limit || !selectedTournament?.home_country_name) return true
    const { overseas_limit, home_country_name } = selectedTournament
    const allPlayers = allTeams.flatMap(t => t.players)
    const swapMap = new Map(swaps.map(s => [s.player_out_id, s]))
    const count = selectedTeam.players.filter(p => {
      const swap = swapMap.get(p.player_id)
      const effective = swap ? (allPlayers.find(pl => pl.player_id === swap.player_in_id) ?? p) : p
      return !!effective.country_name && effective.country_name !== home_country_name
    }).length
    return count <= overseas_limit
  }, [selectedTeam, swaps, allTeams, selectedTournament])

  // Step-based help: show the relevant slide the first time each step is reached
  useEffect(() => {
    const slide = CHALLENGE_STEP_SLIDE[step]
    if (slide === undefined) return
    const key = `/challenge#${step}`
    if (!hasSeenHelp(key)) {
      markHelpSeen(key)
      openHelp(slide, true)
    }
  }, [step]) // eslint-disable-line react-hooks/exhaustive-deps

  const stepIndex = STEP_ORDER.indexOf(step)

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      {/* Mode label */}
      <div className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: 'var(--score)' }}>
        Challenge Mode
      </div>
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 mb-8 flex-wrap">
        {STEP_ORDER.map((s, i) => (
          <div key={s} className="flex items-center gap-1">
            <div
              className="flex items-center gap-1.5 text-sm"
              style={{ color: i <= stepIndex ? 'var(--score)' : 'var(--text-dim)' }}
            >
              <span
                className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-semibold"
                style={{
                  background: i < stepIndex ? 'var(--score)' : i === stepIndex ? 'rgba(245,158,11,0.15)' : 'var(--surface-2)',
                  color: i < stepIndex ? 'var(--bg)' : i === stepIndex ? 'var(--score)' : 'var(--text-dim)',
                  border: i === stepIndex ? '1px solid var(--score)' : 'none',
                }}
              >
                {i + 1}
              </span>
              <span className="hidden sm:inline">{STEP_LABELS[s]}</span>
            </div>
            {i < STEP_ORDER.length - 1 && <ChevronRight size={14} style={{ color: 'var(--text-dim)' }} />}
          </div>
        ))}
      </div>

      {restoreNotice && (
        <div className="text-sm mb-5 px-3 py-2 rounded-lg flex items-center justify-between gap-3"
          style={{ background: 'rgba(239,68,68,0.1)', color: 'var(--loss)' }}
        >
          <span>{restoreNotice}</span>
          <button onClick={() => setRestoreNotice('')} style={{ color: 'var(--loss)', flexShrink: 0 }}>✕</button>
        </div>
      )}

      {/* Step 1: Pick tournament name */}
      {step === 'pick_tournament' && (
        <div className="fade-in">
          <button
            className="flex items-center gap-1 text-sm mb-5"
            style={{ color: 'var(--text-muted)' }}
            onClick={() => navigate('/play')}
          >
            <ChevronLeft size={14} /> Back
          </button>
          <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>Pick a tournament</div>
          <div className="text-sm mb-5" style={{ color: 'var(--text-muted)' }}>
            Choose the competition you want to take on
          </div>
          <div className="relative mb-4">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-dim)' }} />
            <input
              className="input"
              style={{ paddingLeft: '2rem' }}
              placeholder="Search tournaments…"
              type="search" autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          {loadingTournaments ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : (
            <div className="flex flex-col gap-2">
              {uniqueNames.map(name => {
                const hist = nameCounts.get(name)
                return (
                  <button
                    key={name}
                    onClick={() => pickName(name)}
                    className="card-sm flex items-center justify-between px-4 py-3 cursor-pointer w-full text-left transition-all"
                    onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--score)'}
                    onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
                  >
                    <div>
                      <div className="text-sm font-medium" style={{ color: 'var(--text)' }}>{name}</div>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <FormatBadge format={grouped[name][0]?.format} className="self-start" />
                        {hist && (
                          <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-dim)' }}>
                            {hist.completed}/{hist.total} complete
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-xs" style={{ color: 'var(--text-dim)' }}>
                        {grouped[name].length} season{grouped[name].length !== 1 ? 's' : ''}
                      </span>
                      <ChevronRight size={14} style={{ color: 'var(--text-dim)' }} />
                    </div>
                  </button>
                )
              })}
              {uniqueNames.length === 0 && !loadingTournaments && (
                <div className="text-sm text-center py-8" style={{ color: 'var(--text-dim)' }}>
                  No tournaments found
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Step 2: Pick underdog team+season */}
      {step === 'pick_team_season' && (
        <div className="fade-in">
          <BackButton onClick={() => goToStep('pick_tournament')} />

          <div className="flex items-start justify-between gap-3 mb-1">
            <div className="text-xl font-semibold" style={{ color: 'var(--text)' }}>
              Pick your underdog
            </div>
            {leaderboardsEnabled && (
              <button
                onClick={() => navigate(`/leaderboard?mode=challenge&name=${encodeURIComponent(selectedName)}`)}
                className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1.5 rounded-lg shrink-0"
                style={{ background: 'rgba(245,158,11,0.14)', border: '1px solid rgba(245,158,11,0.4)', color: 'var(--score)' }}
              >
                <Trophy size={12} /> Leaderboards
              </button>
            )}
          </div>
          <div className="text-sm mb-1" style={{ color: 'var(--text-muted)' }}>{selectedName}</div>
          <div className="flex items-center gap-1.5 mb-5">
            <TrendingDown size={12} style={{ color: 'var(--loss)' }} />
            <span className="text-xs" style={{ color: 'var(--text-dim)' }}>
              Teams with historical win rate &lt; 33%
            </span>
          </div>

          {loadingUnderdogs ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : underdogError ? (
            <div className="card p-6 text-center text-sm" style={{ color: 'var(--text-dim)' }}>
              {underdogError}
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {underdogs.map(entry => (
                <button
                  key={`${entry.tournament_id}-${entry.team_id}`}
                  onClick={() => pickEntry(entry)}
                  className="card-sm flex items-center justify-between px-4 py-3 cursor-pointer w-full text-left transition-all"
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--score)'}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
                >
                  <div>
                    <div className="text-sm font-medium" style={{ color: 'var(--text)' }}>
                      {entry.team_name} · {entry.season}
                    </div>
                    {(() => {
                      const best = teamBest.get(`${entry.team_name}-${entry.tournament_id}`)
                      if (best) return (
                        <div className="flex items-center gap-1.5 mt-1">
                          <PlacementBadge placement={best.best_placement} />
                          <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                            {best.swap_count} trade{best.swap_count !== 1 ? 's' : ''}
                          </span>
                        </div>
                      )
                      return <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Not played</div>
                    })()}
                  </div>
                  <div className="text-right shrink-0">
                    <div
                      className="text-sm font-semibold"
                      style={{ color: entry.win_pct < 0.2 ? 'var(--loss)' : 'var(--score)' }}
                    >
                      {(entry.win_pct * 100).toFixed(0)}%
                    </div>
                    {(() => {
                      const myRank = teamRanks.get(`${entry.team_name}-${entry.tournament_id}`)
                      if (!myRank) return null
                      return (
                        <div className="text-xs font-medium mt-1 flex items-center gap-1 justify-end" style={{ color: medalColor(myRank.rank) }}>
                          <Globe size={12} /> Global Rank #{myRank.rank}
                        </div>
                      )
                    })()}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Step 3: Squad editor */}
      {step === 'squad' && selectedEntry && (
        <div className="fade-in">
          <BackButton onClick={() => goToStep('pick_team_season')} />
          <div className="flex items-start justify-between gap-3 mb-1">
            <div className="text-xl font-semibold" style={{ color: 'var(--text)' }}>Edit your squad</div>
            {leaderboardsEnabled && (
              <button
                onClick={() => setShowSquadLeaderboard(true)}
                className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1.5 rounded-lg shrink-0"
                style={{ background: 'rgba(245,158,11,0.14)', border: '1px solid rgba(245,158,11,0.4)', color: 'var(--score)' }}
              >
                <Trophy size={12} /> Leaderboard
              </button>
            )}
          </div>
          <div className="text-sm mb-5" style={{ color: 'var(--text-muted)' }}>
            {selectedName} {selectedEntry.season} · {selectedEntry.team_name}
            {swaps.length > 0 && (
              <span
                className="ml-2 px-2 py-0.5 rounded-full text-xs font-medium"
                style={{ background: 'rgba(245,158,11,0.12)', color: 'var(--score)' }}
              >
                {swaps.length} trade{swaps.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          {loadingSquad ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : selectedTeam ? (
            <>
              <SquadEditor
                squad={selectedTeam.players}
                allTeams={allTeams}
                userTeamId={selectedTeam.team_id}
                maxSwaps={3}
                swaps={swaps}
                onSwapsChange={setSwaps}
                onOrderChange={setBattingOrder}
                overseasLimit={selectedTournament?.overseas_limit ?? undefined}
                homeCountryName={selectedTournament?.home_country_name ?? undefined}
              />
              {!hasKeeper && (
                <div className="mt-4 px-3 py-2.5 rounded-lg text-sm"
                  style={{ background: 'rgba(239,68,68,0.08)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.2)' }}>
                  No wicket-keeper in your squad. Trade in a keeper before continuing.
                </div>
              )}
              {!overseasValid && (
                <div className="mt-2 px-3 py-2.5 rounded-lg text-sm"
                  style={{ background: 'rgba(239,68,68,0.08)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.2)' }}>
                  ✈ Too many overseas players ({selectedTournament?.overseas_limit} max). Trade in a local player to continue.
                </div>
              )}
              <div className="mt-4 sticky bottom-0 -mx-4 px-4 py-3" style={{ background: 'var(--bg)', borderTop: '1px solid var(--border)' }}>
                <button
                  className="btn-accent w-full py-3 text-base"
                  style={{ background: (!hasKeeper || !overseasValid) ? undefined : 'var(--score)', color: 'var(--bg)', opacity: (!hasKeeper || !overseasValid) ? 0.45 : 1, cursor: (!hasKeeper || !overseasValid) ? 'not-allowed' : undefined }}
                  onClick={() => goToStep('confirm')}
                  disabled={!hasKeeper || !overseasValid}
                >
                  Continue →
                </button>
              </div>
            </>
          ) : null}
        </div>
      )}

      {showSquadLeaderboard && selectedEntry && (
        <ChallengeLeaderboardModal
          tournamentId={selectedEntry.tournament_id}
          teamName={selectedEntry.team_name}
          mode="challenge"
          onClose={() => setShowSquadLeaderboard(false)}
        />
      )}

      {/* Step 4: Confirm */}
      {step === 'confirm' && selectedEntry && selectedTeam && (
        <div className="fade-in">
          <BackButton onClick={() => goToStep('squad')} />
          <div className="text-xl font-semibold mb-5" style={{ color: 'var(--text)' }}>Ready to simulate</div>

          <div className="card p-5 mb-4 space-y-3">
            <ConfirmRow label="Tournament" value={`${selectedName} ${selectedEntry.season}`} />
            <ConfirmRow label="Your team" value={selectedTeam.team_name} />
            <ConfirmRow
              label="Trades"
              value={swaps.length === 0 ? 'None' : `${swaps.length} trade${swaps.length !== 1 ? 's' : ''}`}
            />
            <ConfirmRow label="Mode" value="Challenge Mode" accentColor="var(--score)" />
          </div>

          <div className="mb-6">
            <SimulationTypeToggle />
          </div>

          {error && (
            <div className="text-sm mb-4 px-3 py-2 rounded-lg"
              style={{ background: 'rgba(239,68,68,0.1)', color: 'var(--loss)' }}
            >
              {error}
            </div>
          )}

          <button
            className="btn-accent w-full flex items-center justify-center gap-2 text-base py-3"
            style={{ background: 'var(--score)', color: 'var(--bg)' }}
            onClick={runSim}
            disabled={running}
          >
            {running ? <><Spinner size={16} /> Running…</> : '▶  Start Challenge'}
          </button>
        </div>
      )}
    </div>
  )
}

