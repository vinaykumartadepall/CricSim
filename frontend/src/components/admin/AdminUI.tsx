// Shared building blocks for the /site-admin pages.
import { Check } from 'lucide-react'

export const ADMIN_SERIF = "'DM Serif Display', Georgia, 'Times New Roman', serif"
export const ADMIN_SANS  = "'DM Sans', system-ui, sans-serif"

// 401 = not signed in / token invalid, 403 = signed in but not an admin
export function isAuthError(err: unknown): boolean {
  const msg = String(err instanceof Error ? err.message : err)
  return msg.startsWith('401') || msg.startsWith('403') || msg === 'Forbidden'
}

export function AccessDenied() {
  return (
    <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.6 }}>
      Admin access required. Sign in with the admin account, then reload this page.
    </div>
  )
}

export function Section({
  title, description, children, error,
}: {
  title: string
  description: string
  children: React.ReactNode
  error?: string | null
}) {
  return (
    <div style={{
      padding: '18px 20px', borderRadius: 10,
      background: 'var(--surface)', border: '1px solid var(--border)',
      marginBottom: 14,
    }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 12, lineHeight: 1.5 }}>{description}</div>
      {children}
      {error && (
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--loss)' }}>{error}</div>
      )}
    </div>
  )
}

export function OptionRow({
  options, active, disabled, onSelect,
}: {
  options: string[]
  active: string
  disabled: boolean
  onSelect: (value: string) => void
}) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {options.map(opt => {
        const isActive = opt === active
        return (
          <button
            key={opt}
            disabled={disabled}
            onClick={() => onSelect(opt)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 7,
              background: isActive ? 'var(--accent-tint)' : 'var(--surface-2)',
              border: isActive ? '1px solid var(--accent)' : '1px solid var(--border)',
              color: isActive ? 'var(--accent)' : 'var(--text-muted)',
              fontSize: 13, fontWeight: isActive ? 600 : 400,
              cursor: disabled ? 'default' : 'pointer',
              opacity: disabled ? 0.6 : 1,
              transition: 'background 0.12s, color 0.12s',
            }}
          >
            {isActive && <Check size={12} />}
            {opt}
          </button>
        )
      })}
    </div>
  )
}

export const adminInputStyle: React.CSSProperties = {
  padding: '7px 10px', borderRadius: 7, fontSize: 13,
  background: 'var(--surface-2)', border: '1px solid var(--border)',
  color: 'var(--text)', outline: 'none', width: '100%',
}

export function SaveButton({ onClick, saving, dirty, label = 'Save' }: {
  onClick: () => void
  saving: boolean
  dirty: boolean
  label?: string
}) {
  return (
    <button
      onClick={onClick}
      disabled={saving || !dirty}
      style={{
        padding: '7px 16px', borderRadius: 7, fontSize: 13, fontWeight: 600,
        background: dirty ? 'var(--accent-tint)' : 'var(--surface-2)',
        border: dirty ? '1px solid var(--accent)' : '1px solid var(--border)',
        color: dirty ? 'var(--accent)' : 'var(--text-dim)',
        cursor: saving || !dirty ? 'default' : 'pointer',
      }}
    >
      {saving ? 'Saving…' : label}
    </button>
  )
}
