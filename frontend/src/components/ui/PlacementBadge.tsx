// Single source of truth for the medal-ladder placement styling (gold/silver/
// bronze podium metaphor) and the leaderboard rank badge - shared by SimCard's
// RightChip and the challenge leaderboard. Do not add a third copy of either.

const GOLD = 'var(--score)'
const SILVER = '#C0C0C0'
const BRONZE = '#CD7F32'
const DIM = 'var(--text-dim)'
const NEUTRAL_BG = 'rgba(255,255,255,0.06)'

function darkTint(color: string, percent: number): string {
  return `color-mix(in srgb, ${color} ${percent}%, var(--surface-2))`
}

const PLACEMENT_STYLE: Record<string, { bg: string; color: string; prefix?: string }> = {
  'Winner':      { bg: darkTint(GOLD, 30),   color: GOLD,   prefix: '🏆 ' },
  'Runner-up':   { bg: darkTint(SILVER, 20), color: SILVER, prefix: '🥈 ' },
  'Playoffs':    { bg: darkTint(BRONZE, 22), color: BRONZE                },
  'Loser':       { bg: NEUTRAL_BG,           color: DIM                   },
  'Group stage': { bg: NEUTRAL_BG,           color: DIM                   },
}

export function PlacementBadge({ placement, className = '' }: { placement: string; className?: string }) {
  const s = PLACEMENT_STYLE[placement] ?? PLACEMENT_STYLE['Group stage']
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 font-medium whitespace-nowrap ${className}`}
      style={{ background: s.bg, color: s.color }}>
      {s.prefix ?? ''}{placement}
    </span>
  )
}

// Leaderboard *position* - a distinct concept from placement: two people can
// both finish "Winner" but differ in leaderboard rank (e.g. tiebroken by
// swaps/win%). Ranks 1-3 get the same medal colors as PlacementBadge; the
// rest are plain and muted. Single source of truth for that color rule -
// reused by both the RankBadge circle and any plain-text rank display.
const MEDAL_COLOR: Record<number, string> = { 1: GOLD, 2: SILVER, 3: BRONZE }

export function medalColor(rank: number): string {
  return MEDAL_COLOR[rank] ?? DIM
}

export function RankBadge({ rank, className = '' }: { rank: number; className?: string }) {
  const medal = MEDAL_COLOR[rank]
  return (
    <div className={`flex items-center justify-center rounded-full font-bold shrink-0 ${className}`}
      style={{
        // min-width (not a fixed width) so 3-digit ranks (up to 100, the
        // leaderboard's own display cap) widen into a rounded pill instead
        // of clipping - 1-2 digit ranks stay a true circle since the content
        // never exceeds the minimum.
        minWidth: 28, height: 28, padding: '0 6px', borderRadius: 999, fontSize: 13,
        background: medal ? darkTint(medal, 30) : NEUTRAL_BG,
        color: medal ?? DIM,
        border: `1px solid ${medal ? medal + '55' : 'var(--border)'}`,
      }}>
      {rank}
    </div>
  )
}
