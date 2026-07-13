const ROLE_STYLES: Record<string, { bg: string; color: string }> = {
  'Batter':      { bg: 'rgba(59,130,246,0.12)',  color: 'var(--accent)' },
  'Bowler':      { bg: 'rgba(249,115,22,0.12)', color: '#f97316' },
  'All-rounder': { bg: 'rgba(14,165,233,0.12)', color: '#0ea5e9' },
  'Keeper':      { bg: 'rgba(168,85,247,0.12)', color: '#a855f7' },
}

const COMPACT_LABELS: Record<string, string> = {
  'Batter': 'BAT', 'Bowler': 'BWL', 'All-rounder': 'AR', 'Keeper': 'WK',
}

export function RoleBadge({ role, compact }: { role: string | null | undefined; compact?: boolean }) {
  if (!role) return null

  if (compact) {
    const r = role.toLowerCase()
    const key =
      r.includes('bowl') ? 'Bowler' :
      r.includes('all')  ? 'All-rounder' :
      r.includes('keep') ? 'Keeper' : 'Batter'
    const s = ROLE_STYLES[key]
    return (
      <span className="text-[10px] px-1 py-px rounded font-semibold shrink-0"
        style={{ background: s.bg, color: s.color }}>
        {COMPACT_LABELS[key]}
      </span>
    )
  }

  const s = ROLE_STYLES[role] ?? { bg: 'rgba(255,255,255,0.08)', color: 'var(--text-muted)' }
  return (
    <span className="text-xs px-1.5 py-0.5 rounded font-medium shrink-0" style={{ background: s.bg, color: s.color }}>
      {role}
    </span>
  )
}
