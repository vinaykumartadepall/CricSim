import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, X } from 'lucide-react'
import { Spinner } from '@/components/ui/Spinner'
import { PlacementBadge, RankBadge } from '@/components/ui/PlacementBadge'
import { PlayerRosterRow, type RosterPlayer } from '@/components/ui/PlayerRosterRow'
import { api } from '@/api/client'
import { useBodyScrollLock } from '@/hooks/useBodyScrollLock'
import { useChallengeLeaderboardData, LEADERBOARD_ROW_CAP } from '@/hooks/useChallengeLeaderboardData'
import type { ChallengeLeaderboardEntry } from '@/types'

// Global, cross-user leaderboard for one tournament+team+mode combo - every
// row used the exact same team, so there's no per-row "team" column to show;
// what a row opens instead is the actual XI (with trades highlighted) that
// got that player their placement, styled like ResultsPage's own
// TeamPreviewPanel (points-table row click) for a consistent feel.
//
// Never more than one overlay layer: on a page (LeaderboardPage, not itself
// an overlay) a row opens PlayerTeamPanel as a normal popup. Inside this
// modal (already an overlay - ResultsPage's own "Leaderboard" button, or the
// squad-step button), a row swaps the modal's own content in place instead -
// a second popup stacked on the first one didn't read well, and neither did
// expanding a row inline.

function usePlayerTeam(simId: string, teamName: string) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [players, setPlayers] = useState<RosterPlayer[]>([])
  const [tradedInIds, setTradedInIds] = useState<Set<number>>(new Set())

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([api.getLineups(simId), api.getSimResult(simId)])
      .then(([lineups, result]) => {
        if (cancelled) return
        const team = lineups.teams.find(t => t.team_name === teamName)
        setPlayers(team?.players ?? [])
        setTradedInIds(new Set((result.swaps ?? []).map(s => s.player_in_id)))
      })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't load this squad.") })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [simId, teamName])

  return { loading, error, players, tradedInIds }
}

// ── Squad list content - shared by the popup (page context) and the
// in-place swap (modal context). No portal/backdrop of its own. ────────────

export function PlayerTeamList({ simId, teamName }: { simId: string; teamName: string }) {
  const { loading, error, players, tradedInIds } = usePlayerTeam(simId, teamName)

  if (loading) return <div className="flex justify-center py-10"><Spinner /></div>
  if (error) return <div className="px-4 py-6 text-center text-sm" style={{ color: 'var(--text-dim)' }}>{error}</div>
  if (players.length === 0) return <div className="px-4 py-6 text-center text-sm" style={{ color: 'var(--text-dim)' }}>No player data</div>

  return (
    <div className="flex-1 overflow-y-auto">
      {players.map((p, i) => (
        <PlayerRosterRow key={p.player_id} player={p} index={i} tradedIn={tradedInIds.has(p.player_id)} />
      ))}
    </div>
  )
}

// ── Squad popup - page context only (not already inside an overlay), styled
// to match ResultsPage's TeamPreviewPanel. ──────────────────────────────────

export function PlayerTeamPanel({
  entry, teamName, onClose,
}: {
  entry: ChallengeLeaderboardEntry
  teamName: string
  onClose: () => void
}) {
  useBodyScrollLock(true)

  return createPortal(
    <>
      <div onClick={onClose}
        style={{ position: 'fixed', inset: 0, zIndex: 150, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(3px)' }} />
      <div style={{
        position: 'fixed', left: '50%', top: '50%', transform: 'translate(-50%, -50%)',
        width: 'min(380px, 96vw)', maxHeight: '85vh',
        zIndex: 151, display: 'flex', flexDirection: 'column',
        background: 'var(--bg)', borderRadius: 12, border: '1px solid var(--border)',
        overflow: 'hidden', animation: 'fadeIn 160ms ease',
      }}>
        <div className="flex items-center gap-3 px-4 py-3 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>Squad</div>
            <div className="text-sm font-bold truncate" style={{ color: 'var(--text)' }}>{entry.username}</div>
            <div className="text-xs truncate" style={{ color: 'var(--text-dim)' }}>{teamName}</div>
          </div>
          <button onClick={onClose} style={{ color: 'var(--text-muted)' }}><X size={16} /></button>
        </div>
        <PlayerTeamList simId={entry.sim_id} teamName={teamName} />
      </div>
      <style>{`@keyframes fadeIn { from { opacity:0;transform:translate(-50%,-50%) scale(0.96) } to { opacity:1;transform:translate(-50%,-50%) scale(1) } }`}</style>
    </>,
    document.body
  )
}

// ── Row ───────────────────────────────────────────────────────────────────

export function LeaderboardRow({
  entry, onClick, highlight,
}: {
  entry: ChallengeLeaderboardEntry
  onClick: () => void
  highlight?: boolean
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2.5 px-2.5 py-2 w-full text-left cursor-pointer rounded-lg"
      style={{
        background: highlight ? 'rgba(59,130,246,0.07)' : 'transparent',
        boxShadow: highlight ? 'inset 2px 0 0 var(--accent)' : undefined,
      }}
    >
      <RankBadge rank={entry.rank} />
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium truncate flex items-center gap-1.5" style={{ color: highlight ? 'var(--accent)' : 'var(--text)' }}>
          {entry.username}
          {entry.is_you && (
            <span className="text-[10px] px-1.5 py-px rounded font-semibold shrink-0" style={{ background: 'rgba(59,130,246,0.12)', color: 'var(--accent)' }}>You</span>
          )}
        </div>
        <div className="text-[10px]" style={{ color: 'var(--text-dim)' }}>
          {entry.swap_count} trade{entry.swap_count !== 1 ? 's' : ''} &middot; {(entry.win_pct * 100).toFixed(0)}% wins
        </div>
      </div>
      <PlacementBadge placement={entry.best_placement} />
    </button>
  )
}

// ── List body (you-row + paginated rows) - shared by the modal and the page.
// Purely presentational: takes the hook's return value as a prop so a
// container only ever fetches once, whether it also needs the data (e.g. for
// a header count) or not. ──────────────────────────────────────────────────

export function LeaderboardEntries({
  data, onSelectEntry, scrollContainerClassName,
}: {
  data: ReturnType<typeof useChallengeLeaderboardData>
  onSelectEntry: (entry: ChallengeLeaderboardEntry) => void
  // Modal wants its own bounded inner-scroll region (overflow-y-auto); the
  // full page wants to scroll with the rest of the page instead - either
  // way the IntersectionObserver sentinel below correctly detects "near the
  // bottom" since it accounts for whatever clipping ancestor is actually
  // scrolling, not just the browser viewport.
  scrollContainerClassName: string
}) {
  const { entries, you, youAlreadyListed, totalEntrants, loading, loadingMore, error, canLoadMore, loadMore } = data
  const sentinelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = sentinelRef.current
    if (!el || !canLoadMore) return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) loadMore()
    }, { rootMargin: '80px' })
    observer.observe(el)
    return () => observer.disconnect()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canLoadMore, entries.length])

  if (loading) return <div className="flex justify-center py-10"><Spinner /></div>
  if (error) return <div className="px-4 py-6 text-center text-sm" style={{ color: 'var(--text-dim)' }}>{error}</div>
  if (entries.length === 0) return <div className="px-4 py-6 text-center text-sm" style={{ color: 'var(--text-dim)' }}>No players yet.</div>

  return (
    <>
      {you && !youAlreadyListed && (
        <div className="mx-3 mt-2 mb-1 rounded-lg flex-shrink-0" style={{ border: '1px solid var(--accent)' }}>
          <LeaderboardRow entry={you} highlight onClick={() => onSelectEntry(you)} />
        </div>
      )}
      <div className={scrollContainerClassName}>
        {entries.map(e => (
          <LeaderboardRow key={e.client_id} entry={e} highlight={e.is_you} onClick={() => onSelectEntry(e)} />
        ))}
        {canLoadMore && <div ref={sentinelRef} style={{ height: 1 }} />}
        {loadingMore && <div className="flex justify-center py-2"><Spinner size={14} /></div>}
        {!canLoadMore && totalEntrants > LEADERBOARD_ROW_CAP && (
          <div className="text-center text-[11px] py-2" style={{ color: 'var(--text-dim)' }}>
            You&rsquo;ve reached the top {LEADERBOARD_ROW_CAP} &middot; {totalEntrants - LEADERBOARD_ROW_CAP} more players not shown
          </div>
        )}
      </div>
    </>
  )
}

export function LeaderboardHeaderText({ totalEntrants, mode }: { totalEntrants: number; mode: string }) {
  return (
    <div className="text-[11px]" style={{ color: 'var(--text-dim)' }}>
      {totalEntrants} {totalEntrants === 1 ? 'player' : 'players'} &middot; {mode === 'challenge' ? 'Challenge' : 'Fun'} mode
      {totalEntrants > LEADERBOARD_ROW_CAP && <> &middot; top {LEADERBOARD_ROW_CAP}</>}
    </div>
  )
}

// ── Modal ────────────────────────────────────────────────────────────────

export function ChallengeLeaderboardModal({
  tournamentId, teamName, mode, onClose, onBack,
}: {
  tournamentId: number
  teamName: string
  mode: string
  onClose: () => void
  // Present only when this modal was opened from a browsing flow that has
  // somewhere to go back to - absent (e.g. from ResultsPage) means only the
  // X shows, since there's nothing else to return to.
  onBack?: () => void
}) {
  useBodyScrollLock(true)
  const data = useChallengeLeaderboardData(tournamentId, teamName, mode)
  // Viewing one entry's squad swaps this modal's own body in place (see file
  // header) rather than opening a second overlay.
  const [viewingEntry, setViewingEntry] = useState<ChallengeLeaderboardEntry | null>(null)

  return createPortal(
    <>
      <div onClick={onClose}
        style={{ position: 'fixed', inset: 0, zIndex: 160, background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(3px)' }} />
      <div style={{
        position: 'fixed', left: '50%', top: '6vh', transform: 'translateX(-50%)',
        width: 'min(360px, 94vw)', maxHeight: '88vh', zIndex: 161,
        display: 'flex', flexDirection: 'column',
        background: 'var(--bg)', borderRadius: 12, border: '1px solid var(--border)',
        overflow: 'hidden', animation: 'fadeIn 150ms ease',
      }}>
        <div className="flex items-center gap-2 px-3.5 py-2.5 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
          {(viewingEntry || onBack) && (
            <button onClick={() => (viewingEntry ? setViewingEntry(null) : onBack?.())} style={{ color: 'var(--text-muted)', flexShrink: 0 }}>
              <ChevronLeft size={17} />
            </button>
          )}
          {viewingEntry ? (
            <div className="flex-1 min-w-0">
              <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>Squad</div>
              <div className="text-sm font-semibold truncate" style={{ color: 'var(--text)' }}>{viewingEntry.username}</div>
            </div>
          ) : (
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold truncate" style={{ color: 'var(--text)' }}>{teamName}</div>
              <LeaderboardHeaderText totalEntrants={data.totalEntrants} mode={mode} />
            </div>
          )}
          <button onClick={onClose} style={{ color: 'var(--text-muted)', flexShrink: 0 }}><X size={15} /></button>
        </div>
        {viewingEntry ? (
          <PlayerTeamList simId={viewingEntry.sim_id} teamName={teamName} />
        ) : (
          <LeaderboardEntries data={data} onSelectEntry={setViewingEntry}
            scrollContainerClassName="flex-1 overflow-y-auto px-2.5 pb-2 pt-1" />
        )}
      </div>
    </>,
    document.body
  )
}
