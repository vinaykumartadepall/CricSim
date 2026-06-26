import type { ReactNode } from 'react'

interface Props {
  children: ReactNode
  variant?: 'accent' | 'muted' | 'win' | 'loss'
}

const styles = {
  accent: { background: 'var(--accent)', color: 'var(--bg)' },
  muted:  { background: 'var(--surface-2)', color: 'var(--text-muted)', border: '1px solid var(--border)' },
  win:    { background: 'rgba(34,197,94,0.15)', color: 'var(--win)', border: '1px solid rgba(34,197,94,0.3)' },
  loss:   { background: 'rgba(239,68,68,0.12)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.25)' },
}

export function Badge({ children, variant = 'muted' }: Props) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
      style={styles[variant]}
    >
      {children}
    </span>
  )
}
