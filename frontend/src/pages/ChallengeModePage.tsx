import { useState, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, TrendingDown, Search } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { useHelp } from '@/contexts/HelpContext'
import { hasSeenHelp, markHelpSeen } from '@/config/helpContent'
import { Spinner } from '@/components/ui/Spinner'
import { SimulationTypeToggle } from '@/components/ui/SimulationTypeToggle'
import { FormatBadge } from '@/components/ui/FormatBadge'
import { BackButton } from '@/components/ui/BackButton'
import { ConfirmRow } from '@/components/ui/ConfirmRow'
import { SquadEditor } from '@/components/SquadEditor'
import { sortTournamentNames } from '@/lib/sortTournamentNames'
import type { Tournament, Team, SwapEntry, SimHistoryNameCount, SimHistoryTeamBest } from '@/types'


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
  const [searchParams, setSearchParams] = useSearchParams()
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

  // Confirm
  const { clientId } = useAuth()
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  // Keeps the URL as the durable record of "where am I" (tournament + team +
  // step) so reload/back/forward/history land back in the right place instead
  // of resetting to step 1. Swaps deliberately excluded (kept out of the URL
  // by design) - retrySimId remains the durable path for those, since they
  // only exist once a sim has actually been run.
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

  // Shared by pickName(), the retry flow, and the URL-restore effect below -
  // previously the retry flow fetched underdogs on its own without fetching
  // teamBest, so going back to the pick_team_season step after a retry showed
  // no "best result" line for any entry, even with real history.
  function loadUnderdogs(name: string): Promise<UnderdogEntry[]> {
    setLoadingUnderdogs(true)
    setUnderdogError('')
    setTeamBest(new Map())
    return api.getUnderdogs(name)
      .then(data => {
        setUnderdogs(data)
        if (data.length === 0) {
          setUnderdogError('No underdog teams found - all teams win > 33% of matches in every season')
          return data
        }
        const uniqueTids = [...new Set(data.map(e => e.tournament_id))]
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

  // Try-again resume flow - driven by a URL query param (?retrySimId=) and a
  // fresh fetch of that session, rather than router state carried in memory,
  // so this also works when landing here from a historical sim (My
  // Simulations) or after a reload of this very page, not just immediately
  // after finishing a fresh run.
  useEffect(() => {
    if (!retrySimId) return
    api.getSimResult(retrySimId, clientId)
      .then(result => {
        if (!result?.source_tournament_id || !result?.user_team_name) return
        setSelectedName(result.tournament_name ?? '')
        setSelectedEntry({
          tournament_id: result.source_tournament_id,
          team_id: result.user_team_id ?? 0,
          team_name: result.user_team_name ?? '',
          season: result.season ?? '',
          wins: 0, total_matches: 0, win_pct: 0,
        })
        loadUnderdogs(result.tournament_name ?? '')
        return loadTeamForTournament(result.source_tournament_id, result.user_team_id ?? null)
          .then(team => {
            if (team) {
              setSwaps(result.swaps ?? [])
              setStep('squad')
              updateUrlParams({ tournament_id: String(result.source_tournament_id), team_id: String(team.team_id), step: 'squad' })
            }
          })
      })
      .catch(err => console.warn('Failed to restore previous run for Try Again', err))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // URL-driven restore for a fresh (not-yet-simulated) build - covers the case
  // retrySimId doesn't: reloading or navigating back mid-build, before any sim
  // has ever been created. Only fires when retrySimId isn't in play, since
  // that flow is authoritative (it also restores swaps, which this can't).
  useEffect(() => {
    if (retrySimId) return
    const urlTournamentId = searchParams.get('tournament_id')
    const urlTeamId = searchParams.get('team_id')
    if (!urlTournamentId || !urlTeamId) return
    const tid = Number(urlTournamentId)
    const teamId = Number(urlTeamId)
    const urlStep = searchParams.get('step')
    api.getTournaments().then(all => {
      const t = all.find(x => x.tournament_id === tid)
      if (!t) return
      setSelectedName(t.name)
      loadUnderdogs(t.name)
      return loadTeamForTournament(tid, teamId).then(team => {
        if (!team) return
        setSelectedEntry({
          tournament_id: tid, team_id: team.team_id, team_name: team.team_name,
          season: t.season, wins: 0, total_matches: 0, win_pct: 0,
        })
        setStep(urlStep === 'confirm' ? 'confirm' : 'squad')
      })
    }).catch(err => console.warn('Failed to restore build from URL context', err))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    setLoadingTournaments(true)
    api.getTournaments(search || undefined)
      .then(data => setAllTournaments(data))
      .catch(() => setAllTournaments([]))
      .finally(() => setLoadingTournaments(false))
  }, [search])

  useEffect(() => {
    api.getSimHistoryNameCounts(clientId, 'challenge')
      .then(data => setNameCounts(new Map(data.map(r => [r.name, r]))))
      .catch(err => console.warn('Sim-history name counts unavailable (non-critical)', err))
  }, [clientId])

  // Group by name for step 1 (same pattern as FunModePage)
  const grouped = allTournaments.reduce<Record<string, Tournament[]>>((acc, t) => {
    if (!acc[t.name]) acc[t.name] = []
    acc[t.name].push(t)
    return acc
  }, {})
  const uniqueNames = sortTournamentNames(Object.keys(grouped))

  function pickName(name: string) {
    setSelectedName(name)
    setSelectedEntry(null)
    setAllTeams([])
    setSelectedTeam(null)
    setSwaps([])
    setStep('pick_team_season')
    updateUrlParams({ tournament_id: undefined, team_id: undefined, step: 'pick_team_season' })
    loadUnderdogs(name)
  }

  function pickEntry(entry: UnderdogEntry) {
    setSelectedEntry(entry)
    setSwaps([])
    setSelectedTeam(null)
    setStep('squad')
    updateUrlParams({ tournament_id: String(entry.tournament_id), team_id: String(entry.team_id), step: 'squad' })
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
            <div className="flex flex-col gap-2 max-h-[420px] overflow-y-auto">
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
          <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>
            Pick your underdog
          </div>
          <div className="text-sm mb-1" style={{ color: 'var(--text-muted)' }}>{selectedName}</div>
          <div className="flex items-center gap-1.5 mb-5">
            <TrendingDown size={12} style={{ color: 'var(--loss)' }} />
            <span className="text-xs" style={{ color: 'var(--text-dim)' }}>
              Teams with historical win rate &lt; 33% - ordered newest season first
            </span>
          </div>

          {loadingUnderdogs ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : underdogError ? (
            <div className="card p-6 text-center text-sm" style={{ color: 'var(--text-dim)' }}>
              {underdogError}
            </div>
          ) : (
            <div className="flex flex-col gap-2 max-h-[420px] overflow-y-auto">
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
                      {entry.team_name}
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                      {entry.season} · {entry.wins}W / {entry.total_matches} matches
                    </div>
                    {(() => {
                      const best = teamBest.get(`${entry.team_name}-${entry.tournament_id}`)
                      if (best) return (
                        <div style={{ fontSize: 11 }}>
                          <span style={{ color: 'var(--text-dim)' }}>Best: </span>
                          <span style={{ color: 'var(--text-dim)', fontWeight: 500 }}>
                            {best.best_placement}
                          </span>
                          <span style={{ color: 'var(--text-dim)' }}>, {best.swap_count} trade{best.swap_count !== 1 ? 's' : ''}</span>
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
                    <div className="text-xs" style={{ color: 'var(--text-dim)' }}>win rate</div>
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
          <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>Edit your squad</div>
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

