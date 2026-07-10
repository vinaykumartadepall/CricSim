import { useNavigate } from 'react-router-dom'
import type { SimSummary } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

export function simPath(sim: SimSummary): string {
  if (sim.status === 'running' || sim.status === 'pending') {
    return `/simulating/${sim.sim_id}`
  }
  if (sim.simulation_type === 'match' && sim.match_id) {
    return `/results/${sim.sim_id}/matches/${sim.match_id}`
  }
  return `/results/${sim.sim_id}`
}

function simTitle(sim: SimSummary): string {
  if (!sim.tournament_name) return 'Simulation'
  return sim.season ? `${sim.tournament_name} ${sim.season}` : sim.tournament_name
}

// ── Color tokens ──────────────────────────────────────────────────────────────
// Single source of truth for every badge/chip color in this file - no more raw
// hex/rgba scattered through each component. Backgrounds are derived from the
// same value via tint() (CSS color-mix) rather than a separately hand-picked
// rgba, so a badge's background always matches its text color exactly -
// including staying correct across all 4 themes for CSS-variable colors like
// --accent, instead of a fixed rgba tint that never actually changed with theme.

const COLOR = {
  gold:   'var(--score)',
  accent: 'var(--accent)',
  win:    'var(--win)',
  loss:   'var(--loss)',
  dim:    'var(--text-dim)',
  silver: '#C0C0C0',
  bronze: '#CD7F32',
  purple: '#a855f7',
  violet: '#8B5CF6',
} as const

const NEUTRAL_BG = 'rgba(255,255,255,0.06)'

function tint(color: string, percent: number): string {
  return `color-mix(in srgb, ${color} ${percent}%, transparent)`
}

// Mixes toward the app's own dark surface color instead of transparent -
// gives the deep, near-opaque pill look (dark amber/navy/plum, not a light
// wash) used for the status chips specifically, per the provided reference
// mockups. Kept separate from tint() so FormatBadge/ModeBadge (not covered by
// those mockups) are untouched.
function darkTint(color: string, percent: number): string {
  return `color-mix(in srgb, ${color} ${percent}%, var(--surface-2))`
}

// ── Shared primitives ─────────────────────────────────────────────────────────

function Badge({ bg, color, children }: { bg: string; color: string; children: React.ReactNode }) {
  return (
    <span className="text-xs px-1.5 py-px rounded font-medium shrink-0"
      style={{ background: bg, color }}>
      {children}
    </span>
  )
}

function Chip({ bg, color, children }: { bg: string; color: string; children: React.ReactNode }) {
  return (
    <span className="text-xs px-2 py-0.5 rounded-full shrink-0 font-medium whitespace-nowrap"
      style={{ background: bg, color }}>
      {children}
    </span>
  )
}

// ── Format badge ──────────────────────────────────────────────────────────────

function FormatBadge({ format }: { format: string | null | undefined }) {
  if (!format) return null
  const styles: Record<string, { bg: string; color: string }> = {
    Test: { bg: tint(COLOR.purple, 12), color: COLOR.purple },
    ODI:  { bg: tint(COLOR.win, 10),    color: COLOR.win },
    T20:  { bg: tint(COLOR.accent, 10), color: COLOR.accent },
  }
  const s = styles[format] ?? { bg: NEUTRAL_BG, color: COLOR.dim }
  return <Badge bg={s.bg} color={s.color}>{format}</Badge>
}

// ── Mode badge (row 2) ────────────────────────────────────────────────────────

function ModeBadge({ mode, simulationType }: {
  mode: string | null | undefined
  simulationType?: string | null
}) {
  if (!mode) return null
  if (mode === 'multiplayer') {
    const label = simulationType === 'match' ? '1v1' : 'Multiplayer'
    return <Badge bg={tint(COLOR.purple, 12)} color={COLOR.purple}>{label}</Badge>
  }
  if (mode === 'challenge') return <Badge bg={tint(COLOR.gold, 12)} color={COLOR.gold}>Challenge</Badge>
  if (mode === 'custom')    return <Badge bg={tint(COLOR.violet, 12)} color={COLOR.violet}>Custom</Badge>
  return <Badge bg={tint(COLOR.accent, 10)} color={COLOR.accent}>Fun</Badge>
}

// ── Right-side chip: result OR spectator OR status ────────────────────────────

// Full medal ladder: gold (winner) > silver (runner-up) > bronze (playoffs)
// > muted gray (no notable result) - a warm-toned podium metaphor that fits
// the app's own dark warm surfaces, rather than an unrelated purple that
// doesn't tie into any theme color. All three medal tiers use the same dark,
// near-opaque background treatment (color mixed into the app's own surface
// tone) rather than a light wash, per the provided reference mockups.
const PLACEMENT: Record<string, { bg: string; color: string; prefix?: string }> = {
  'Winner':      { bg: darkTint(COLOR.gold, 30),   color: COLOR.gold,   prefix: '🏆 ' },
  'Runner-up':   { bg: darkTint(COLOR.silver, 20), color: COLOR.silver, prefix: '🥈 ' },
  'Playoffs':    { bg: darkTint(COLOR.bronze, 22), color: COLOR.bronze                },
  'Loser':       { bg: NEUTRAL_BG,                 color: COLOR.dim                   },
  'Group stage': { bg: NEUTRAL_BG,                 color: COLOR.dim                   },
}

function RightChip({ sim }: { sim: SimSummary }) {
  // Non-completed states.
  if (sim.status === 'failed') {
    return <Chip bg={tint(COLOR.loss, 12)} color={COLOR.loss}>Failed</Chip>
  }
  if (sim.status === 'running') {
    return <Chip bg={darkTint(COLOR.gold, 16)} color={COLOR.gold}>⏳ In progress</Chip>
  }
  if (sim.status !== 'completed') {
    return <Chip bg={NEUTRAL_BG} color={COLOR.dim}>🕐 Pending</Chip>
  }

  // Completed + placement
  if (sim.user_team_placement) {
    const s = PLACEMENT[sim.user_team_placement] ?? PLACEMENT['Group stage']
    return <Chip bg={s.bg} color={s.color}>{(s.prefix ?? '')}{sim.user_team_placement}</Chip>
  }

  // Completed + no user team = spectator
  if (sim.mode && !sim.user_team_name) {
    return <Chip bg={NEUTRAL_BG} color={COLOR.dim}>Spectator</Chip>
  }

  return null
}

// ── Card ──────────────────────────────────────────────────────────────────────

export function SimCard({ sim }: { sim: SimSummary }) {
  const navigate = useNavigate()
  const hasMetaRow = !!(sim.match_format || sim.mode || (sim.swap_count != null && sim.swap_count > 0))

  return (
    <button
      onClick={() => navigate(simPath(sim), sim.simulation_type === 'match' ? { state: { backPath: '/', userTeam: sim.user_team_name ?? null } } : undefined)}
      className="card p-5 cursor-pointer w-full text-left transition-all duration-200"
      onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
      onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>

        {/* Left: title · mode/trades · team name */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 14, fontWeight: 600, color: 'var(--text)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {simTitle(sim)}
          </div>

          {hasMetaRow && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
              <FormatBadge format={sim.match_format} />
              <ModeBadge mode={sim.mode} simulationType={sim.simulation_type} />
            </div>
          )}

          {sim.user_team_name && (
            <div style={{ marginTop: hasMetaRow ? 3 : 4 }}>
              <span style={{
                fontSize: 12, color: 'var(--text-muted)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block',
              }}>
                {sim.user_team_name}
                {sim.swap_count != null && sim.swap_count > 0 && (
                  <span style={{ fontSize: 12, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
                    {' ·'} {sim.swap_count} trade{sim.swap_count !== 1 ? 's' : ''}
                  </span>
                )}
              </span>
            </div>
          )}
        </div>

        {/* Right: result chip + date stacked */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, flexShrink: 0 }}>
          <RightChip sim={sim} />
          <span style={{ fontSize: 11, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
            {new Date(sim.created_at).toLocaleDateString()}
          </span>
        </div>
      </div>
    </button>
  )
}
