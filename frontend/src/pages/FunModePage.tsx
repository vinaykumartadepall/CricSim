import { useState, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Globe, Trophy } from 'lucide-react'
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
import type { Tournament, Team, SwapEntry, SimHistoryNameCount, SimHistorySeasonCount, SimHistoryTeamBest, MyTeamRankItem } from '@/types'

type Step = 'tournament' | 'season' | 'team' | 'squad' | 'confirm'


const FUN_STEP_SLIDE: Partial<Record<Step, number>> = {
  tournament: 0,
  season: 1,
  team: 2,
  squad: 3,
}

export function FunModePage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const retrySimId = searchParams.get('retrySimId')
  const { clientId, authReady } = useAuth()
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

  const [swaps, setSwaps] = useState<SwapEntry[]>([])
  const [battingOrder, setBattingOrder] = useState<number[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  // Set when a retry/URL restore couldn't fully recover the previous build
  // (fetch failure, or the previously-picked team/season no longer resolves)
  // - shown as a banner rather than silently landing somewhere unexplained.
  const [restoreNotice, setRestoreNotice] = useState('')

  // ── Sim history state ──────────────────────────────────────────────────────
  const [nameCounts, setNameCounts] = useState<Map<string, SimHistoryNameCount>>(new Map())
  const [seasonCounts, setSeasonCounts] = useState<Map<number, SimHistorySeasonCount>>(new Map())
  const [teamBest, setTeamBest] = useState<Map<string, SimHistoryTeamBest>>(new Map())
  const [teamRanks, setTeamRanks] = useState<Map<string, MyTeamRankItem>>(new Map())

  // Leaderboard preview - lets you see a team's global leaderboard before
  // ever picking it. The team step's button navigates to a real page
  // (LeaderboardPage) since it needs to browse many teams first - a popup
  // stacked on this wizard's own flow didn't read well there. The squad step
  // already has one specific team+season though (no browsing needed), so its
  // button reuses the plain single-leaderboard popup - same shape ResultsPage
  // already uses.
  const [leaderboardsEnabled, setLeaderboardsEnabled] = useState(false)
  const [showSquadLeaderboard, setShowSquadLeaderboard] = useState(false)

  useEffect(() => {
    api.getLeaderboardsEnabled()
      .then(r => setLeaderboardsEnabled(r.enabled))
      .catch(() => setLeaderboardsEnabled(false))
  }, [])

  // Fetch name-level counts, scoped to the current search term - refetches as
  // the user narrows the tournament list instead of pulling every name the
  // client has ever touched up front.
  useEffect(() => {
    api.getSimHistoryNameCounts(clientId, undefined, search || undefined)
      .then(data => setNameCounts(new Map(data.map(r => [r.name, r]))))
      .catch(err => console.warn('Sim-history name counts unavailable (non-critical)', err))
  }, [clientId, search])

  const { updateUrlParams, goToStep } = useWizardUrlState<Step>(setStep)

  // Shared by selectSeason(), the retry flow, and the URL-restore effect below
  // - previously the retry flow fetched squads on its own without this, so
  // teamBest never got populated and going back to the team step after a
  // retry showed no "best result" badges for any team, even with real history.
  function loadSeasonData(tournamentId: number): Promise<Team[]> {
    setLoadingTeams(true)
    setAllTeams([])
    setTeamBest(new Map())
    setTeamRanks(new Map())
    return Promise.all([
      api.getTournamentSquads(tournamentId),
      api.getSimHistoryBest(clientId, tournamentId, 'fun').catch(() => [] as SimHistoryTeamBest[]),
      api.getMyChallengeRanks(clientId, tournamentId, 'fun').catch(() => [] as MyTeamRankItem[]),
    ]).then(([squadsData, bestData, rankData]) => {
      const teams = squadsData.teams || []
      setAllTeams(teams)
      setTeamBest(new Map(bestData.map(r => [r.team_name, r])))
      setTeamRanks(new Map(rankData.map(r => [r.team_name, r])))
      return teams
    }).catch(() => {
      setAllTeams([])
      return [] as Team[]
    }).finally(() => setLoadingTeams(false))
  }

  // Unified restore path - both the retry flow (?retrySimId=) and the plain
  // URL-restore (name/tournament_id/team_id/step surviving in the URL after
  // a reload or back-navigation) fetch through this one awaited function, so
  // there's exactly one place that decides which step to land on and exactly
  // one failure path - instead of several independent fire-and-forget chains
  // that could each silently do nothing (this file's history of one-off
  // patches, e.g. the loadSeasonData/teamBest comment above, came from
  // exactly that shape).
  async function restoreTo(
    target: {
      name?: string; tournamentId?: number; teamId?: number; teamName?: string
      urlStep?: string | null; swaps?: SwapEntry[]
    },
    isCancelled: () => boolean,
  ) {
    const all = await api.getTournaments()
    if (isCancelled()) return

    let season: Tournament | null = null
    let name = target.name
    if (target.tournamentId) {
      season = all.find(x => x.tournament_id === target.tournamentId) ?? null
      if (!season) throw new Error('Season not found for restore')
      name = season.name
    }
    if (!name) throw new Error('Nothing to restore')

    setTournamentName(name)
    const nameSeasons = all.filter(x => x.name === name).sort((a, b) => b.season.localeCompare(a.season))
    setSeasons(nameSeasons)

    if (!season) {
      // Only the tournament name resolved - land on the season list, which
      // now has its own data loaded (completion counts fill in separately).
      setStep('season')
      updateUrlParams({ retrySimId: undefined, name, tournament_id: undefined, team_id: undefined, step: 'season' })
      return
    }

    setSelectedSeason(season)
    const teams = await loadSeasonData(season.tournament_id)
    if (isCancelled()) return

    const wantsTeam = !!target.teamId || !!target.teamName
    const team = target.teamId
      ? teams.find(tm => tm.team_id === target.teamId) ?? null
      : target.teamName
        ? teams.find(tm => tm.team_name === target.teamName) ?? null
        : null

    if (wantsTeam && !team) {
      setRestoreNotice('That team pick is no longer available - pick again below.')
      setStep('team')
      updateUrlParams({ retrySimId: undefined, name, tournament_id: String(season.tournament_id), team_id: undefined, step: 'team' })
      return
    }
    if (team) {
      setSelectedTeam(team)
      setBattingOrder(team.players.map(p => p.player_id))
      if (target.swaps) setSwaps(target.swaps)
    }
    // Honor step=confirm even with no team (the "no preference" skipTeam
    // path) - only fall back to 'team' when there's not enough restored
    // context for either 'squad' or 'confirm' to make sense.
    const finalStep = target.urlStep === 'confirm' ? 'confirm' : team ? 'squad' : 'team'
    setStep(finalStep)
    // retrySimId cleared here (not in a follow-up call) so it lands in the
    // same URL update as the restored step/team params, instead of racing a
    // stale searchParams closure that could clobber what this call just set.
    updateUrlParams({
      retrySimId: undefined, name, tournament_id: String(season.tournament_id),
      team_id: team ? String(team.team_id) : undefined, step: finalStep,
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
        if (!result?.source_tournament_id) throw new Error('Incomplete sim result for retry')
        return restoreTo({
          tournamentId: result.source_tournament_id,
          teamName: result.user_team_name ?? undefined,
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
  // / back-navigation mid-build - covers every step from season onward. Only
  // fires when retrySimId isn't in play, since that flow is authoritative
  // (it also restores swaps, which this can't).
  useEffect(() => {
    if (retrySimId || !authReady) return
    const name = searchParams.get('name')
    const urlTournamentId = searchParams.get('tournament_id')
    const urlTeamId = searchParams.get('team_id')
    const urlStep = searchParams.get('step')
    if (!name && !urlTournamentId) return
    let cancelled = false
    restoreTo({
      name: name ?? undefined,
      tournamentId: urlTournamentId ? Number(urlTournamentId) : undefined,
      teamId: urlTeamId ? Number(urlTeamId) : undefined,
      urlStep,
    }, () => cancelled).catch(err => {
      if (cancelled) return
      console.warn('Failed to restore build from URL context', err)
      setRestoreNotice("Couldn't restore your previous session - pick a tournament to start again.")
    })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady])

  useEffect(() => {
    setLoadingTournaments(true)
    api.getTournaments(search || undefined)
      .then(data => setTournaments(data))
      .catch(() => setTournaments([]))
      .finally(() => setLoadingTournaments(false))
  }, [search])

  const grouped = tournaments.reduce<Record<string, Tournament[]>>((acc, t) => {
    if (!acc[t.name]) acc[t.name] = []
    acc[t.name].push(t)
    return acc
  }, {})
  const uniqueNames = sortTournamentNames(Object.keys(grouped))

  function selectTournamentName(name: string) {
    setRestoreNotice('')
    setTournamentName(name)
    const nameSeasons = (grouped[name] || []).sort((a, b) => b.season.localeCompare(a.season))
    setSeasons(nameSeasons)
    setSelectedSeason(null)
    setSeasonCounts(new Map())
    setStep('season')
    // A different tournament name invalidates any previously-selected season/team.
    updateUrlParams({ name, tournament_id: undefined, team_id: undefined, step: 'season' })

    // Fetch season-level counts using IDs from the already-known nameCounts
    const nameRow = nameCounts.get(name)
    const ids = nameRow?.tournament_ids ?? nameSeasons.map(s => s.tournament_id)
    if (ids.length > 0) {
      api.getSimHistorySeasonCounts(clientId, ids)
        .then(data => setSeasonCounts(new Map(data.map(r => [r.tournament_id, r]))))
        .catch(err => console.warn('Sim-history season counts unavailable (non-critical)', err))
    }
  }

  function selectSeason(t: Tournament) {
    setRestoreNotice('')
    setSelectedSeason(t)
    setSelectedTeam(null)
    setSwaps([])
    setStep('team')
    updateUrlParams({ name: tournamentName, tournament_id: String(t.tournament_id), team_id: undefined, step: 'team' })
    loadSeasonData(t.tournament_id)
  }

  function selectTeam(team: Team) {
    setRestoreNotice('')
    setSelectedTeam(team)
    setSwaps([])
    setBattingOrder(team.players.map(p => p.player_id))
    setStep('squad')
    updateUrlParams({ team_id: String(team.team_id), step: 'squad' })
  }

  function skipTeam() {
    setRestoreNotice('')
    setSelectedTeam(null)
    setSwaps([])
    setStep('confirm')
    updateUrlParams({ team_id: undefined, step: 'confirm' })
  }

  async function runSim() {
    if (!selectedSeason) return
    setRunning(true)
    setError('')
    try {
      const { sim_id } = await api.startTournamentSim({
        tournament_id: selectedSeason.tournament_id,
        team_id: selectedTeam?.team_id ?? null,
        mode: 'fun',
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
          origin: 'fun',
          tournamentId: selectedSeason!.tournament_id,
          teamId: selectedTeam?.team_id ?? null,
          tournamentName,
          season: selectedSeason!.season,
          teamName: selectedTeam?.team_name ?? null,
        },
      })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start simulation')
      setRunning(false)
    }
  }

  // Step-based help: show the relevant slide the first time each step is reached
  useEffect(() => {
    const slide = FUN_STEP_SLIDE[step]
    if (slide === undefined) return
    const key = `/fun#${step}`
    if (!hasSeenHelp(key)) {
      markHelpSeen(key)
      openHelp(slide, true)
    }
  }, [step]) // eslint-disable-line react-hooks/exhaustive-deps

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

  const overseasValid = useMemo(() => {
    if (!selectedTeam || !selectedSeason?.overseas_limit || !selectedSeason?.home_country_name) return true
    const { overseas_limit, home_country_name } = selectedSeason
    const allPlayers = allTeams.flatMap(t => t.players)
    const swapMap = new Map(swaps.map(s => [s.player_out_id, s]))
    const count = selectedTeam.players.filter(p => {
      const swap = swapMap.get(p.player_id)
      const effective = swap ? (allPlayers.find(pl => pl.player_id === swap.player_in_id) ?? p) : p
      return !!effective.country_name && effective.country_name !== home_country_name
    }).length
    return count <= overseas_limit
  }, [selectedTeam, swaps, allTeams, selectedSeason])

  const STEPS: Step[] = ['tournament', 'season', 'team', 'squad', 'confirm']
  const stepLabels = ['Tournament', 'Season', 'Team', 'Squad', 'Simulate']
  const stepIndex = STEPS.indexOf(step)

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      {/* Mode label */}
      <div className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: 'var(--accent)' }}>
        Fun Mode
      </div>
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 mb-8 flex-wrap">
        {stepLabels.map((label, i) => (
          <div key={label} className="flex items-center gap-1">
            <div
              className="flex items-center gap-1.5 text-sm"
              style={{ color: i <= stepIndex ? 'var(--accent)' : 'var(--text-dim)' }}
            >
              <span
                className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-semibold"
                style={{
                  background: i < stepIndex ? 'var(--accent)' : i === stepIndex ? 'rgba(59,130,246,0.15)' : 'var(--surface-2)',
                  color: i < stepIndex ? 'var(--bg)' : i === stepIndex ? 'var(--accent)' : 'var(--text-dim)',
                  border: i === stepIndex ? '1px solid var(--accent)' : 'none',
                }}
              >
                {i + 1}
              </span>
              <span className="hidden sm:inline">{label}</span>
            </div>
            {i < stepLabels.length - 1 && <ChevronRight size={14} style={{ color: 'var(--text-dim)' }} />}
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

      {/* Step: Tournament */}
      {step === 'tournament' && (
        <div className="fade-in">
          <button
            className="flex items-center gap-1 text-sm mb-5"
            style={{ color: 'var(--text-muted)' }}
            onClick={() => navigate('/play')}
          >
            <ChevronLeft size={14} /> Back
          </button>
          <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>Select tournament</div>
          <div className="text-sm mb-5" style={{ color: 'var(--text-muted)' }}>Choose a tournament to simulate</div>
          <input
            className="input mb-4"
            placeholder="Search tournaments…"
            type="search" autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          {loadingTournaments ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : (
            <div className="flex flex-col gap-2">
              {uniqueNames.map(name => {
                const hist = nameCounts.get(name)
                return (
                  <button
                    key={name}
                    onClick={() => selectTournamentName(name)}
                    className="card-sm flex items-center justify-between px-4 py-3 cursor-pointer w-full text-left transition-all"
                    onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
                    onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
                  >
                    <div className="flex flex-col gap-0.5">
                      <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{name}</span>
                      <div className="flex items-center gap-1.5">
                        <FormatBadge format={grouped[name][0]?.format} className="self-start" />
                        {hist && (
                          <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-dim)' }}>
                            {hist.completed}/{hist.total} complete
                          </span>
                        )}
                      </div>
                    </div>
                    <span className="text-xs shrink-0" style={{ color: 'var(--text-dim)' }}>
                      {grouped[name].length} season{grouped[name].length > 1 ? 's' : ''}
                    </span>
                  </button>
                )
              })}
              {uniqueNames.length === 0 && (
                <div className="text-sm text-center py-8" style={{ color: 'var(--text-dim)' }}>
                  No seeded tournaments found
                </div>
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
            {seasons.map(s => {
              const hist = seasonCounts.get(s.tournament_id)
              const completed = hist?.completed ?? 0
              const total = s.team_count || hist?.total || 0
              return (
                <button
                  key={s.tournament_id}
                  onClick={() => selectSeason(s)}
                  className="card-sm flex items-center justify-between px-4 py-3 cursor-pointer w-full text-left transition-all"
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
                >
                  <div className="flex flex-col gap-0.5">
                    <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{s.season} Season</span>
                    <div className="flex items-center gap-1.5">
                      <FormatBadge format={s.format} className="self-start" />
                      {total > 0 && (
                        <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-dim)' }}>
                          {completed}/{total} complete
                        </span>
                      )}
                    </div>
                  </div>
                  <span className="text-xs shrink-0" style={{ color: 'var(--text-dim)' }}>{s.team_count} teams</span>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Step: Team */}
      {step === 'team' && (
        <div className="fade-in">
          <BackButton onClick={() => goToStep('season')} />

          <div className="flex items-start justify-between gap-3 mb-1">
            <div className="text-xl font-semibold" style={{ color: 'var(--text)' }}>
              {tournamentName} {selectedSeason?.season}
            </div>
            {leaderboardsEnabled && selectedSeason && (
              <button
                onClick={() => navigate(`/leaderboard?mode=fun&tournament_id=${selectedSeason.tournament_id}`)}
                className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1.5 rounded-lg shrink-0"
                style={{ background: 'var(--accent-tint)', border: '1px solid var(--accent-tint)', color: 'var(--accent)' }}
              >
                <Trophy size={12} /> Leaderboards
              </button>
            )}
          </div>
          <div className="text-sm mb-5" style={{ color: 'var(--text-muted)' }}>
            Pick a team to follow - or simulate all equally
          </div>
          {loadingTeams ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : (
            <>
              <div className="flex flex-col gap-2 mb-3">
                {allTeams.map(team => {
                  const best = teamBest.get(team.team_name)
                  const myRank = teamRanks.get(team.team_name)
                  return (
                    <button
                      key={team.team_id}
                      onClick={() => selectTeam(team)}
                      className="card-sm flex items-center justify-between px-4 py-3 cursor-pointer text-left transition-all"
                      onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
                      onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate" style={{ color: 'var(--text)' }}>{team.team_name}</div>
                        {best ? (
                          <div className="flex items-center gap-1.5 mt-1">
                            <PlacementBadge placement={best.best_placement} />
                            <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                              {best.swap_count} trade{best.swap_count !== 1 ? 's' : ''}
                            </span>
                          </div>
                        ) : (
                          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 3 }}>Not played</div>
                        )}
                      </div>
                      {myRank && (
                        <div className="text-right shrink-0 ml-3">
                          <div className="text-xs font-medium flex items-center gap-1 justify-end" style={{ color: medalColor(myRank.rank) }}>
                            <Globe size={12} /> Global Rank #{myRank.rank}
                          </div>
                        </div>
                      )}
                    </button>
                  )
                })}
              </div>
              <button onClick={skipTeam} className="btn-outline w-full text-sm">
                No preference - simulate all teams
              </button>
            </>
          )}
        </div>
      )}


      {/* Step: Squad editor */}
      {step === 'squad' && selectedTeam && (
        <div className="fade-in">
          <BackButton onClick={() => goToStep('team')} />
          <div className="flex items-start justify-between gap-3 mb-1">
            <div className="text-xl font-semibold" style={{ color: 'var(--text)' }}>
              Edit your squad
            </div>
            {leaderboardsEnabled && (
              <button
                onClick={() => setShowSquadLeaderboard(true)}
                className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1.5 rounded-lg shrink-0"
                style={{ background: 'rgba(59,130,246,0.14)', border: '1px solid rgba(59,130,246,0.4)', color: 'var(--accent)' }}
              >
                <Trophy size={12} /> Leaderboard
              </button>
            )}
          </div>
          <div className="text-sm mb-5" style={{ color: 'var(--text-muted)' }}>
            {tournamentName} {selectedSeason?.season} · {selectedTeam.team_name}
          </div>
          <SquadEditor
            squad={selectedTeam.players}
            allTeams={allTeams}
            userTeamId={selectedTeam.team_id}
            swaps={swaps}
            onSwapsChange={setSwaps}
            onOrderChange={setBattingOrder}
            overseasLimit={selectedSeason?.overseas_limit ?? undefined}
            homeCountryName={selectedSeason?.home_country_name ?? undefined}
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
              ✈ Too many overseas players ({selectedSeason?.overseas_limit} max). Trade in a local player to continue.
            </div>
          )}
          <div className="mt-4 sticky bottom-0 -mx-4 px-4 py-3 flex flex-col gap-2" style={{ background: 'var(--bg)', borderTop: '1px solid var(--border)' }}>
            <button
              className="btn-accent w-full py-3 text-base"
              onClick={() => goToStep('confirm')}
              disabled={!hasKeeper || !overseasValid}
              style={{ opacity: (!hasKeeper || !overseasValid) ? 0.45 : 1, cursor: (!hasKeeper || !overseasValid) ? 'not-allowed' : undefined }}
            >
              Continue →
            </button>
          </div>
        </div>
      )}

      {showSquadLeaderboard && selectedSeason && selectedTeam && (
        <ChallengeLeaderboardModal
          tournamentId={selectedSeason.tournament_id}
          teamName={selectedTeam.team_name}
          mode="fun"
          onClose={() => setShowSquadLeaderboard(false)}
        />
      )}

      {/* Step: Confirm */}
      {step === 'confirm' && (
        <div className="fade-in">
          <BackButton onClick={() => goToStep(selectedTeam ? 'squad' : 'team')} />
          <div className="text-xl font-semibold mb-5" style={{ color: 'var(--text)' }}>Ready to simulate</div>

          <div className="card p-5 mb-6 space-y-3">
            <ConfirmRow label="Tournament" value={`${tournamentName} ${selectedSeason?.season}`} />
            <ConfirmRow label="Team" value={selectedTeam?.team_name ?? 'No preference'} />
            {selectedTeam && (
              <ConfirmRow
                label="Trades"
                value={swaps.length === 0 ? 'None' : `${swaps.length} trade${swaps.length !== 1 ? 's' : ''}`}
              />
            )}
            <ConfirmRow label="Mode" value="Fun Mode" accentColor="var(--accent)" />
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
            onClick={runSim}
            disabled={running}
          >
            {running ? <><Spinner size={16} /> Running…</> : '▶  Simulate'}
          </button>
        </div>
      )}
    </div>
  )
}

