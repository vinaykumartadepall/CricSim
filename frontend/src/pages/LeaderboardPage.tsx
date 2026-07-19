import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Globe } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { Spinner } from '@/components/ui/Spinner'
import { PlacementBadge, medalColor } from '@/components/ui/PlacementBadge'
import { BackButton } from '@/components/ui/BackButton'
import {
  LeaderboardEntries, LeaderboardHeaderText, PlayerTeamPanel,
} from '@/components/ChallengeLeaderboardModal'
import { useChallengeLeaderboardData } from '@/hooks/useChallengeLeaderboardData'
import type { ChallengeLeaderboardEntry, MyTeamRankItem, SimHistoryTeamBest } from '@/types'

// Full-page leaderboard browsing - reached from the "Leaderboard" button on
// Fun/Challenge mode's team pickers. A real route (not a modal) so browsing
// many teams and then drilling into one never reads as a popup stacked on a
// popup: /leaderboard?mode=challenge&name=X (browse many seasons of a
// tournament) or ?mode=fun&tournament_id=X (browse one season's teams), then
// picking a row pushes ?...&team=Y for the actual board. Back is just
// browser back - no extra state to keep in sync.

interface BrowseItem {
  key: string
  tournamentId: number
  teamName: string
  title: string
  placement?: string
  rank?: number
}

function useBrowseItems(mode: string, name: string | null, tournamentId: number | null, clientId: string) {
  const [items, setItems] = useState<BrowseItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!name && !tournamentId) { setLoading(false); return }
    let cancelled = false
    setLoading(true)
    setError('')

    async function run() {
      if (mode === 'challenge' && name) {
        const underdogs = await api.getUnderdogs(name)
        if (cancelled) return
        if (underdogs.length === 0) { setItems([]); return }
        const uniqueTids = [...new Set(underdogs.map(e => e.tournament_id))]
        const [bestLists, rankLists] = await Promise.all([
          Promise.all(uniqueTids.map(tid =>
            api.getSimHistoryBest(clientId, tid, 'challenge').then(rows => rows.map(r => ({ ...r, tournament_id: tid }))).catch(() => [] as (SimHistoryTeamBest & { tournament_id: number })[]))),
          Promise.all(uniqueTids.map(tid =>
            api.getMyChallengeRanks(clientId, tid, 'challenge').then(rows => rows.map(r => ({ ...r, tournament_id: tid }))).catch(() => [] as (MyTeamRankItem & { tournament_id: number })[]))),
        ])
        if (cancelled) return
        const bestMap = new Map(bestLists.flat().map(r => [`${r.team_name}-${r.tournament_id}`, r]))
        const rankMap = new Map(rankLists.flat().map(r => [`${r.team_name}-${r.tournament_id}`, r]))
        setItems(underdogs.map(e => ({
          key: `${e.tournament_id}-${e.team_id}`,
          tournamentId: e.tournament_id,
          teamName: e.team_name,
          title: `${e.team_name} · ${e.season}`,
          placement: bestMap.get(`${e.team_name}-${e.tournament_id}`)?.best_placement,
          rank: rankMap.get(`${e.team_name}-${e.tournament_id}`)?.rank,
        })))
      } else if (mode === 'fun' && tournamentId) {
        const [squads, bestRows, rankRows] = await Promise.all([
          api.getTournamentSquads(tournamentId),
          api.getSimHistoryBest(clientId, tournamentId, 'fun').catch(() => [] as SimHistoryTeamBest[]),
          api.getMyChallengeRanks(clientId, tournamentId, 'fun').catch(() => [] as MyTeamRankItem[]),
        ])
        if (cancelled) return
        const bestMap = new Map(bestRows.map(r => [r.team_name, r]))
        const rankMap = new Map(rankRows.map(r => [r.team_name, r]))
        setItems((squads.teams || []).map(t => ({
          key: String(t.team_id),
          tournamentId,
          teamName: t.team_name,
          title: t.team_name,
          placement: bestMap.get(t.team_name)?.best_placement,
          rank: rankMap.get(t.team_name)?.rank,
        })))
      }
    }

    run()
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load teams') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [mode, name, tournamentId, clientId])

  return { items, loading, error }
}

function BrowseView({ mode, name, tournamentId, title }: { mode: string; name: string | null; tournamentId: number | null; title: string }) {
  const navigate = useNavigate()
  const { clientId } = useAuth()
  const { items, loading, error } = useBrowseItems(mode, name, tournamentId, clientId)

  function openTeam(item: BrowseItem) {
    const params = new URLSearchParams({ mode, tournament_id: String(item.tournamentId), team: item.teamName })
    if (name) params.set('name', name)
    navigate(`/leaderboard?${params}`)
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <BackButton onClick={() => navigate(-1)} />
      <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>{title}</div>
      <div className="text-sm mb-5" style={{ color: 'var(--text-muted)' }}>Pick a team to see its global leaderboard</div>

      {loading ? (
        <div className="flex justify-center py-8"><Spinner /></div>
      ) : error ? (
        <div className="card p-6 text-center text-sm" style={{ color: 'var(--text-dim)' }}>{error}</div>
      ) : items.length === 0 ? (
        <div className="card p-6 text-center text-sm" style={{ color: 'var(--text-dim)' }}>Nothing to preview yet.</div>
      ) : (
        <div className="flex flex-col gap-2">
          {items.map(item => (
            <button
              key={item.key}
              onClick={() => openTeam(item)}
              className="card-sm flex items-center justify-between px-4 py-3 cursor-pointer w-full text-left transition-all"
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--score)'}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
            >
              <div className="min-w-0">
                <div className="text-sm font-medium truncate" style={{ color: 'var(--text)' }}>{item.title}</div>
                <div className="mt-1">
                  {item.placement ? (
                    <PlacementBadge placement={item.placement} />
                  ) : (
                    <span className="text-xs" style={{ color: 'var(--text-dim)' }}>Not played</span>
                  )}
                </div>
              </div>
              {item.rank && (
                <div className="text-xs font-medium flex items-center gap-1 shrink-0 ml-3" style={{ color: medalColor(item.rank) }}>
                  <Globe size={12} /> Global Rank #{item.rank}
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function ViewLeaderboard({ tournamentId, teamName, mode }: { tournamentId: number; teamName: string; mode: string }) {
  const navigate = useNavigate()
  const data = useChallengeLeaderboardData(tournamentId, teamName, mode)
  // Not itself an overlay, so a row can safely open a single popup (matches
  // ResultsPage's TeamPreviewPanel) instead of needing the modal's in-place
  // content swap.
  const [viewingEntry, setViewingEntry] = useState<ChallengeLeaderboardEntry | null>(null)

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <BackButton onClick={() => navigate(-1)} />
      <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>{teamName}</div>
      <div className="mb-5"><LeaderboardHeaderText totalEntrants={data.totalEntrants} mode={mode} /></div>
      <LeaderboardEntries data={data} onSelectEntry={setViewingEntry} scrollContainerClassName="flex flex-col gap-2" />
      {viewingEntry && (
        <PlayerTeamPanel entry={viewingEntry} teamName={teamName} onClose={() => setViewingEntry(null)} />
      )}
    </div>
  )
}

export function LeaderboardPage() {
  const [searchParams] = useSearchParams()
  const mode = searchParams.get('mode') === 'fun' ? 'fun' : 'challenge'
  const name = searchParams.get('name')
  const tournamentIdParam = searchParams.get('tournament_id')
  const tournamentId = tournamentIdParam ? Number(tournamentIdParam) : null
  const team = searchParams.get('team')

  if (team && tournamentId) {
    return <ViewLeaderboard tournamentId={tournamentId} teamName={team} mode={mode} />
  }
  return <BrowseView mode={mode} name={name} tournamentId={tournamentId} title={name ?? 'Preview a leaderboard'} />
}
