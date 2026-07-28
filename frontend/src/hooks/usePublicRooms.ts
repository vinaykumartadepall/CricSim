import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { PublicRoomSummary } from '@/types'

// Rooms fill up or get reaped while someone's browsing, so a manual-refresh-
// only list would routinely show stale/dead rooms - poll while the page is
// open instead.
const POLL_INTERVAL_MS = 10_000

export function usePublicRooms(mode: string[], matchFormat: string[]) {
  const [rooms, setRooms] = useState<PublicRoomSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // mode/matchFormat are expected to be stable array references from the
  // caller's useState (a new array only on an actual filter change, not on
  // every render) - so depending on them directly here is safe and avoids
  // re-deriving a join(',') key just to compare them.
  const fetchRooms = useCallback((showLoading: boolean) => {
    if (showLoading) setLoading(true)
    return api.getPublicRooms({ mode, matchFormat })
      .then(rows => { setRooms(rows); setError(null) })
      .catch(err => setError(err instanceof Error ? err.message : "Couldn't load public rooms."))
      .finally(() => { if (showLoading) setLoading(false) })
  }, [mode, matchFormat])

  useEffect(() => {
    let cancelled = false
    fetchRooms(true)
    const interval = setInterval(() => { if (!cancelled) fetchRooms(false) }, POLL_INTERVAL_MS)
    return () => { cancelled = true; clearInterval(interval) }
  }, [fetchRooms])

  return { rooms, loading, error, refetch: () => fetchRooms(false) }
}
