import { useNavigate } from 'react-router-dom'
import type { SimSummary } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

export function simPath(sim: SimSummary): string {
  if (sim.simulation_type === 'match' && sim.match_id) {
    return `/results/${sim.sim_id}/matches/${sim.match_id}`
  }
  return `/results/${sim.sim_id}`
}

function simTitle(sim: SimSummary): string {
  if (!sim.tournament_name) return 'Simulation'
  return sim.season ? `${sim.tournament_name} ${sim.season}` : sim.tournament_name
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
    Test: { bg: 'rgba(168,85,247,0.12)', color: '#a855f7' },
    ODI:  { bg: 'rgba(34,197,94,0.10)',  color: 'var(--win)' },
    T20:  { bg: 'rgba(59,130,246,0.10)', color: 'var(--accent)' },
  }
  const s = styles[format] ?? { bg: 'rgba(255,255,255,0.06)', color: 'var(--text-dim)' }
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
    return <Badge bg="rgba(168,85,247,0.12)" color="#a855f7">{label}</Badge>
  }
  if (mode === 'challenge') return <Badge bg="rgba(245,158,11,0.12)" color="var(--score)">Challenge</Badge>
  if (mode === 'custom')    return <Badge bg="rgba(139,92,246,0.12)" color="#8B5CF6">Custom</Badge>
  return <Badge bg="rgba(59,130,246,0.1)" color="var(--accent)">Fun</Badge>
}

// ── Right-side chip: result OR spectator OR status ────────────────────────────

const PLACEMENT: Record<string, { bg: string; color: string; prefix?: string }> = {
  'Winner':      { bg: 'rgba(245,158,11,0.18)', color: 'var(--score)',    prefix: '🏆 ' },
  'Runner-up':   { bg: 'rgba(59,130,246,0.13)', color: 'var(--accent)'                  },
  'Loser':       { bg: 'rgba(255,255,255,0.06)', color: 'var(--text-dim)'                },
  'Playoffs':    { bg: 'rgba(34,197,94,0.1)',    color: 'var(--win)'                     },
  'Group stage': { bg: 'rgba(255,255,255,0.05)', color: 'var(--text-dim)'                },
}

function RightChip({ sim }: { sim: SimSummary }) {
  // Non-completed states
  if (sim.status === 'failed') {
    return <Chip bg="rgba(239,68,68,0.12)" color="var(--loss)">Failed</Chip>
  }
  if (sim.status !== 'completed') {
    return <Chip bg="rgba(245,158,11,0.12)" color="var(--score)">
      {sim.status === 'running' ? 'Running…' : 'Pending'}
    </Chip>
  }

  // Completed + placement
  if (sim.user_team_placement) {
    const s = PLACEMENT[sim.user_team_placement] ?? PLACEMENT['Group stage']
    return <Chip bg={s.bg} color={s.color}>{(s.prefix ?? '')}{sim.user_team_placement}</Chip>
  }

  // Completed + no user team = spectator
  if (sim.mode && !sim.user_team_name) {
    return <Chip bg="rgba(255,255,255,0.05)" color="var(--text-dim)">Spectator</Chip>
  }

  return null
}

// ── Card ──────────────────────────────────────────────────────────────────────

export function SimCard({ sim }: { sim: SimSummary }) {
  const navigate = useNavigate()
  const hasMetaRow = !!(sim.match_format || sim.mode || (sim.swap_count != null && sim.swap_count > 0))

  return (
    <button
      onClick={() => navigate(simPath(sim), sim.simulation_type === 'match' ? { state: { backPath: '/' } } : undefined)}
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
              {sim.swap_count != null && sim.swap_count > 0 && (
                <span style={{ fontSize: 12, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
                  · {sim.swap_count} trade{sim.swap_count !== 1 ? 's' : ''}
                </span>
              )}
            </div>
          )}

          {sim.user_team_name && (
            <div style={{ marginTop: hasMetaRow ? 3 : 4 }}>
              <span style={{
                fontSize: 12, color: 'var(--text-muted)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block',
              }}>
                {sim.user_team_name}
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
