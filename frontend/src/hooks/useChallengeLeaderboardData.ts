import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import { getClientId } from '@/api/clientId'
import type { ChallengeLeaderboardEntry } from '@/types'

// Shared fetch/paginate logic behind a single tournament+team+mode
// leaderboard - used by both the modal (ResultsPage) and the full-page view
// (LeaderboardPage), so pagination/cap behavior only lives in one place.
export const LEADERBOARD_PAGE_SIZE = 10
export const LEADERBOARD_ROW_CAP = 100

export function useChallengeLeaderboardData(tournamentId: number, teamName: string, mode: string) {
  const [entries, setEntries] = useState<ChallengeLeaderboardEntry[]>([])
  const [you, setYou] = useState<ChallengeLeaderboardEntry | null>(null)
  const [totalEntrants, setTotalEntrants] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadPage = useCallback((offset: number) => {
    return api.getChallengeLeaderboard(getClientId(), tournamentId, teamName, mode, LEADERBOARD_PAGE_SIZE, offset)
  }, [tournamentId, teamName, mode])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    loadPage(0)
      .then(r => {
        if (cancelled) return
        setEntries(r.entries)
        setYou(r.you)
        setTotalEntrants(r.total_entrants)
      })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't load the leaderboard.") })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [loadPage])

  const canLoadMore = entries.length < Math.min(totalEntrants, LEADERBOARD_ROW_CAP)

  function loadMore() {
    if (loading || loadingMore || !canLoadMore) return
    setLoadingMore(true)
    loadPage(entries.length)
      .then(r => setEntries(prev => [...prev, ...r.entries]))
      .catch(() => {})
      .finally(() => setLoadingMore(false))
  }

  const youAlreadyListed = !!you && entries.some(e => e.client_id === you.client_id)

  return { entries, you, youAlreadyListed, totalEntrants, loading, loadingMore, error, canLoadMore, loadMore }
}
