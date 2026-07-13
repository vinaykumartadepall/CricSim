const FORMAT_BADGE_STYLES: Record<string, { bg: string; color: string }> = {
  T20:  { bg: 'rgba(59,130,246,0.1)',  color: 'var(--accent)' },
  ODI:  { bg: 'rgba(14,165,233,0.1)', color: '#0ea5e9' },
  Test: { bg: 'rgba(245,158,11,0.1)', color: 'var(--score)' },
}

export function FormatBadge({ format, className = '' }: { format?: string | null; className?: string }) {
  if (!format) return null
  const s = FORMAT_BADGE_STYLES[format] ?? { bg: 'rgba(255,255,255,0.06)', color: 'var(--text-dim)' }
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${className}`}
      style={{ background: s.bg, color: s.color }}
    >
      {format}
    </span>
  )
}
