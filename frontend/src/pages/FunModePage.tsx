import { useState, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { useHelp } from '@/contexts/HelpContext'
import { hasSeenHelp, markHelpSeen } from '@/config/helpContent'
import { Spinner } from '@/components/ui/Spinner'
import { SimulationTypeToggle } from '@/components/ui/SimulationTypeToggle'
import { SquadEditor } from '@/components/SquadEditor'
import { sortTournamentNames } from '@/lib/sortTournamentNames'
import type { Tournament, Team, SwapEntry, SimHistoryNameCount, SimHistorySeasonCount, SimHistoryTeamBest } from '@/types'

type Step = 'tournament' | 'season' | 'team' | 'squad' | 'confirm'

const FORMAT_BADGE_STYLES: Record<string, { bg: string; color: string }> = {
  T20:  { bg: 'rgba(59,130,246,0.1)',  color: 'var(--accent)' },
  ODI:  { bg: 'rgba(14,165,233,0.1)', color: '#0ea5e9' },
  Test: { bg: 'rgba(245,158,11,0.1)', color: 'var(--score)' },
}

function FormatBadge({ format }: { format?: string | null }) {
  if (!format) return null
  const s = FORMAT_BADGE_STYLES[format] ?? { bg: 'rgba(255,255,255,0.06)', color: 'var(--text-dim)' }
  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold self-start" style={{ background: s.bg, color: s.color }}>
      {format}
    </span>
  )
}


const FUN_STEP_SLIDE: Partial<Record<Step, number>> = {
  tournament: 0,
  season: 1,
  team: 2,
  squad: 3,
}

export function FunModePage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const retrySimId = searchParams.get('retrySimId')
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

  const [swaps, setSwaps] = useState<SwapEntry[]>([])
  const [battingOrder, setBattingOrder] = useState<number[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  // ── Sim history state ──────────────────────────────────────────────────────
  const [nameCounts, setNameCounts] = useState<Map<string, SimHistoryNameCount>>(new Map())
  const [seasonCounts, setSeasonCounts] = useState<Map<number, SimHistorySeasonCount>>(new Map())
  const [teamBest, setTeamBest] = useState<Map<string, SimHistoryTeamBest>>(new Map())

  // Fetch name-level counts on mount
  useEffect(() => {
    api.getSimHistoryNameCounts(clientId)
      .then(data => setNameCounts(new Map(data.map(r => [r.name, r]))))
      .catch(() => {/* non-critical */})
  }, [clientId])

  // Keeps the URL as the durable record of "where am I" (season + team + step)
  // so reload/back/forward/history land back in the right place instead of
  // resetting to step 1 - the same recurring bug class as retrySimId/room_id
  // elsewhere in the app. Swaps are deliberately NOT included here (kept out
  // of the URL by design) - retrySimId remains the durable path for those,
  // since they only exist once a sim has actually been run.
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

  // Shared by selectSeason(), the retry flow, and the URL-restore effect below
  // - previously the retry flow fetched squads on its own without this, so
  // teamBest never got populated and going back to the team step after a
  // retry showed no "best result" badges for any team, even with real history.
  function loadSeasonData(tournamentId: number): Promise<Team[]> {
    setLoadingTeams(true)
    setAllTeams([])
    setTeamBest(new Map())
    return Promise.all([
      api.getTournamentSquads(tournamentId),
      api.getSimHistoryBest(clientId, tournamentId, 'fun').catch(() => [] as SimHistoryTeamBest[]),
    ]).then(([squadsData, bestData]) => {
      const teams = squadsData.teams || []
      setAllTeams(teams)
      setTeamBest(new Map(bestData.map(r => [r.team_name, r])))
      return teams
    }).catch(() => {
      setAllTeams([])
      return [] as Team[]
    }).finally(() => setLoadingTeams(false))
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
        if (!result?.source_tournament_id) return
        setTournamentName(result.tournament_name ?? '')
        setSelectedSeason({
          tournament_id: result.source_tournament_id,
          name: result.tournament_name ?? '',
          season: result.season ?? '',
          team_count: 0, gender: '',
        })
        return loadSeasonData(result.source_tournament_id)
          .then(teams => {
            const team = result.user_team_name
              ? teams.find((t: any) => t.team_name === result.user_team_name) ?? null
              : null
            if (team) {
              setSelectedTeam(team)
              setBattingOrder(team.players.map((p: any) => p.player_id))
              setSwaps(result.swaps ?? [])
              setStep('squad')
              updateUrlParams({ tournament_id: String(result.source_tournament_id), team_id: String(team.team_id), step: 'squad' })
            } else {
              setStep('team')
              updateUrlParams({ tournament_id: String(result.source_tournament_id), team_id: undefined, step: 'team' })
            }
          })
      })
      .catch(() => {})
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // URL-driven restore for a fresh (not-yet-simulated) build - covers the case
  // retrySimId doesn't: reloading or navigating back mid-build, before any sim
  // has ever been created. Only fires when retrySimId isn't in play, since
  // that flow is authoritative (it also restores swaps, which this can't).
  useEffect(() => {
    if (retrySimId) return
    const urlTournamentId = searchParams.get('tournament_id')
    if (!urlTournamentId) return
    const tid = Number(urlTournamentId)
    const urlTeamId = searchParams.get('team_id')
    const urlStep = searchParams.get('step')
    api.getTournaments().then(all => {
      const t = all.find(x => x.tournament_id === tid)
      if (!t) return
      setTournamentName(t.name)
      setSelectedSeason(t)
      return loadSeasonData(tid).then(teams => {
        const team = urlTeamId ? teams.find(tm => tm.team_id === Number(urlTeamId)) ?? null : null
        if (team) {
          setSelectedTeam(team)
          setBattingOrder(team.players.map(p => p.player_id))
        }
        // Honor step=confirm even with no team (the "no preference" skipTeam
        // path) - only fall back to 'team' when there's not enough restored
        // context for either 'squad' or 'confirm' to make sense.
        if (urlStep === 'confirm') setStep('confirm')
        else if (team) setStep('squad')
        else setStep('team')
      })
    }).catch(() => {})
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    setLoadingTournaments(true)
    api.getTournaments(search || undefined)
      .then(data => setTournaments(data))
      .catch(() => setTournaments([]))
      .finally(() => setLoadingTournaments(false))
  }, [search])

  // Neither the retry flow nor the URL-restore effect above go through
  // selectTournamentName(), so `seasons` (the season-step's own list) is never
  // populated by either shortcut - backing up to the season step would show
  // an empty list. Fill it in once tournaments load, but only if nothing has
  // set it yet (normal selectTournamentName() calls always take precedence
  // once the user actually interacts with the flow).
  useEffect(() => {
    if (!tournamentName || seasons.length > 0 || tournaments.length === 0) return
    const nameSeasons = tournaments
      .filter(t => t.name === tournamentName)
      .sort((a, b) => b.season.localeCompare(a.season))
    setSeasons(nameSeasons)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournaments, tournamentName])

  const grouped = tournaments.reduce<Record<string, Tournament[]>>((acc, t) => {
    if (!acc[t.name]) acc[t.name] = []
    acc[t.name].push(t)
    return acc
  }, {})
  const uniqueNames = sortTournamentNames(Object.keys(grouped))

  function selectTournamentName(name: string) {
    setTournamentName(name)
    const nameSeasons = (grouped[name] || []).sort((a, b) => b.season.localeCompare(a.season))
    setSeasons(nameSeasons)
    setSelectedSeason(null)
    setSeasonCounts(new Map())
    setStep('season')
    // A different tournament name invalidates any previously-selected season/team.
    updateUrlParams({ tournament_id: undefined, team_id: undefined, step: 'season' })

    // Fetch season-level counts using IDs from the already-known nameCounts
    const nameRow = nameCounts.get(name)
    const ids = nameRow?.tournament_ids ?? nameSeasons.map(s => s.tournament_id)
    if (ids.length > 0) {
      api.getSimHistorySeasonCounts(clientId, ids)
        .then(data => setSeasonCounts(new Map(data.map(r => [r.tournament_id, r]))))
        .catch(() => {/* non-critical */})
    }
  }

  function selectSeason(t: Tournament) {
    setSelectedSeason(t)
    setSelectedTeam(null)
    setSwaps([])
    setStep('team')
    updateUrlParams({ tournament_id: String(t.tournament_id), team_id: undefined, step: 'team' })
    loadSeasonData(t.tournament_id)
  }

  function selectTeam(team: Team) {
    setSelectedTeam(team)
    setSwaps([])
    setBattingOrder(team.players.map(p => p.player_id))
    setStep('squad')
    updateUrlParams({ team_id: String(team.team_id), step: 'squad' })
  }

  function skipTeam() {
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
                        <FormatBadge format={grouped[name][0]?.format} />
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
                      <FormatBadge format={s.format} />
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
          <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>
            {tournamentName} {selectedSeason?.season}
          </div>
          <div className="text-sm mb-5" style={{ color: 'var(--text-muted)' }}>
            Pick a team to follow - or simulate all equally
          </div>
          {loadingTeams ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2 mb-3">
                {allTeams.map(team => {
                  const best = teamBest.get(team.team_name)
                  return (
                    <button
                      key={team.team_id}
                      onClick={() => selectTeam(team)}
                      className="card-sm px-3 py-3 cursor-pointer text-left transition-all"
                      onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
                      onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
                    >
                      <div className="text-sm font-medium truncate" style={{ color: 'var(--text)' }}>{team.team_name}</div>
                      {best ? (
                        <div style={{ fontSize: 11, marginTop: 3 }}>
                          <span style={{ color: 'var(--text-dim)' }}>Best: </span>
                          <span style={{ color: 'var(--text-dim)', fontWeight: 500 }}>
                            {best.best_placement}
                          </span>
                          <span style={{ color: 'var(--text-dim)' }}>, {best.swap_count} trade{best.swap_count !== 1 ? 's' : ''}</span>
                        </div>
                      ) : (
                        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 3 }}>Not played</div>
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
          <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>
            Edit your squad
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

      {/* Step: Confirm */}
      {step === 'confirm' && (
        <div className="fade-in">
          <BackButton onClick={() => goToStep(selectedTeam ? 'squad' : 'team')} />
          <div className="text-xl font-semibold mb-5" style={{ color: 'var(--text)' }}>Ready to simulate</div>

          <div className="card p-5 mb-6 space-y-3">
            <Row label="Tournament" value={`${tournamentName} ${selectedSeason?.season}`} />
            <Row label="Team" value={selectedTeam?.team_name ?? 'No preference'} />
            {selectedTeam && (
              <Row
                label="Trades"
                value={swaps.length === 0 ? 'None' : `${swaps.length} trade${swaps.length !== 1 ? 's' : ''}`}
              />
            )}
            <Row label="Mode" value="Fun Mode" accent />
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

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      className="flex items-center gap-1 text-sm mb-5"
      style={{ color: 'var(--text-muted)' }}
      onClick={onClick}
    >
      <ChevronLeft size={14} /> Back
    </button>
  )
}

function Row({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="text-sm font-medium" style={{ color: accent ? 'var(--accent)' : 'var(--text)' }}>
        {value}
      </span>
    </div>
  )
}
