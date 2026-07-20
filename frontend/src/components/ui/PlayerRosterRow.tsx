import { ArrowRightLeft } from 'lucide-react'
import { PlayerAvatar } from '@/components/ui/Avatar'
import { RoleBadge } from '@/components/ui/RoleBadge'

// Single source of truth for "one player in a roster list" - shared by the
// leaderboard's squad popup (ChallengeLeaderboardModal's PlayerTeamList) and
// ResultsPage's points-table team preview (TeamPreviewPanel), so the
// traded-in treatment only needs to be built once and looks identical in
// both. Do not add a third copy.

export interface RosterPlayer {
  player_id: number
  player_name: string
  player_role: string | null
  headshot_url?: string | null
  runs: number
  wickets: number
  mvp_points: number
}

// var(--accent) is yellow/gold in some themes - the traded-in tint needs to
// stay green (matching the arrow/border) regardless of the active accent
// color, so it's mixed off var(--win) directly rather than reusing
// --accent-tint.
const TRADED_IN_TINT = 'color-mix(in srgb, var(--win) 6%, transparent)'

export function PlayerRosterRow({ player, index, tradedIn }: { player: RosterPlayer; index: number; tradedIn?: boolean }) {
  return (
    <div
      className="flex items-center gap-3 px-4 py-3"
      style={{
        borderBottom: '1px solid var(--border)',
        borderLeft: `3px solid ${tradedIn ? 'var(--win)' : 'transparent'}`,
        background: tradedIn ? TRADED_IN_TINT : undefined,
      }}
    >
      <div className="text-xs w-5 text-right shrink-0 font-mono" style={{ color: 'var(--text-dim)' }}>{index + 1}</div>
      <PlayerAvatar name={player.player_name} url={player.headshot_url} size={32} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-sm font-medium truncate" style={{ color: 'var(--text)' }}>{player.player_name}</span>
          <RoleBadge role={player.player_role} compact />
          {tradedIn && (
            <ArrowRightLeft size={14} strokeWidth={2} style={{ color: 'var(--win)', flexShrink: 0 }} aria-label="Traded in" />
          )}
        </div>
        <div className="flex items-center gap-2 mt-0.5" style={{ fontSize: 11, color: 'var(--text-dim)' }}>
          <span>{player.runs} runs</span>
          {player.wickets > 0 && <span>&middot; {player.wickets} wkts</span>}
        </div>
      </div>
      {player.mvp_points > 0 && (
        <div className="text-right shrink-0">
          <div className="text-sm font-bold" style={{ color: 'var(--score)' }}>{player.mvp_points.toFixed(1)}</div>
          <div style={{ color: 'var(--text-dim)', fontSize: 10 }}>MVP</div>
        </div>
      )}
    </div>
  )
}
