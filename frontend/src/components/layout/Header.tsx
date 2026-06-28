import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, LogOut, Pencil, Check, CircleHelp, Palette } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useHelp } from '@/contexts/HelpContext'
import { useTheme } from '@/hooks/useTheme'
import type { Theme } from '@/types'

const THEMES: { key: Theme; label: string; accent: string }[] = [
  { key: 'night-stadium',      label: 'Night Stadium',      accent: '#3B82F6' },
  { key: 'digital-scoreboard', label: 'Digital Scoreboard', accent: '#F97316' },
  { key: 'pitch-dark',         label: 'Pitch Dark',         accent: '#0EA5E9' },
  { key: 'slate-gold',         label: 'Slate Gold',         accent: '#EAB308' },
  { key: 'day-match',          label: 'Day Match',          accent: '#2563EB' },
]

function ThemeSwitcher() {
  const { theme, setTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const current = THEMES.find(t => t.key === theme) ?? THEMES[0]

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        title="Change theme"
        style={{
          display: 'flex', alignItems: 'center', gap: 5,
          background: 'none', border: '1px solid var(--border)',
          borderRadius: 8, padding: '5px 9px',
          cursor: 'pointer', color: 'var(--text-muted)',
        }}
        onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
        onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
      >
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: current.accent, flexShrink: 0 }} />
        <Palette size={13} />
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: '100%', right: 0, marginTop: 6,
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 8, minWidth: 180, zIndex: 100,
          boxShadow: '0 8px 24px rgba(0,0,0,0.3)', overflow: 'hidden',
        }}>
          <div style={{ padding: '6px 10px 4px', fontSize: 10, color: 'var(--text-dim)', letterSpacing: '0.06em', fontWeight: 600 }}>
            THEME
          </div>
          {THEMES.map(t => (
            <button
              key={t.key}
              onClick={() => { setTheme(t.key); setOpen(false) }}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                padding: '8px 12px', background: t.key === theme ? 'var(--surface-2)' : 'none',
                border: 'none', cursor: 'pointer', color: t.key === theme ? 'var(--text)' : 'var(--text-muted)',
                fontSize: 13, textAlign: 'left',
              }}
            >
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: t.accent, flexShrink: 0 }} />
              {t.label}
              {t.key === theme && <Check size={11} style={{ marginLeft: 'auto', color: 'var(--accent)' }} />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Avatar({ name }: { name: string }) {
  const initials = name.replace(/_\d+$/, '').slice(0, 2).toUpperCase()
  return (
    <div style={{
      width: 28, height: 28, borderRadius: '50%',
      background: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 11, fontWeight: 700, color: 'var(--bg)', flexShrink: 0,
    }}>
      {initials}
    </div>
  )
}

export function Header() {
  const { displayName, isLoggedIn, signOut, openAuthModal, updateDisplayName } = useAuth()
  const { openHelp } = useHelp()
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [editingName, setEditingName]   = useState(false)
  const [nameInput, setNameInput]       = useState('')
  const [saving, setSaving]             = useState(false)
  const dropdownRef                     = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
        setEditingName(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const startEdit = () => {
    setNameInput(displayName)
    setEditingName(true)
  }

  const saveName = async () => {
    const trimmed = nameInput.trim()
    if (!trimmed || trimmed === displayName) { setEditingName(false); return }
    setSaving(true)
    try {
      await updateDisplayName(trimmed)
    } finally {
      setSaving(false)
      setEditingName(false)
      setDropdownOpen(false)
    }
  }

  return (
    <header
      className="flex items-center justify-between px-6 py-4 border-b"
      style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
    >
      <Link to="/" className="flex items-center gap-2 no-underline">
        <span style={{ color: 'var(--accent)', fontSize: 22, fontWeight: 700, letterSpacing: '-0.5px' }}>
          ◈ CRICSIM
        </span>
      </Link>

      <div className="flex items-center gap-3">
        <ThemeSwitcher />

        <button
          onClick={() => openHelp(0, false)}
          title="Help"
          style={{ color: 'var(--text-dim)', padding: 4, borderRadius: 6, lineHeight: 0 }}
          onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = 'var(--accent)'}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = 'var(--text-dim)'}
        >
          <CircleHelp size={18} />
        </button>

        {isLoggedIn ? (
          <div ref={dropdownRef} style={{ position: 'relative' }}>
            <button
              onClick={() => setDropdownOpen(o => !o)}
              style={{
                display: 'flex', alignItems: 'center', gap: 7,
                background: 'none', border: '1px solid var(--border)',
                borderRadius: 20, padding: '4px 10px 4px 4px',
                cursor: 'pointer', color: 'var(--text)',
              }}
            >
              <Avatar name={displayName} />
              <span style={{ fontSize: 13, fontWeight: 500, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {displayName}
              </span>
              <ChevronDown size={12} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
            </button>

            {dropdownOpen && (
              <div style={{
                position: 'absolute', top: '100%', right: 0, marginTop: 6,
                background: 'var(--surface)', border: '1px solid var(--border)',
                borderRadius: 8, minWidth: 200, zIndex: 100,
                boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
                overflow: 'hidden',
              }}>
                {editingName ? (
                  <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 6 }}>Display name</div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input
                        className="input"
                        value={nameInput}
                        onChange={e => setNameInput(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') saveName(); if (e.key === 'Escape') setEditingName(false) }}
                        maxLength={32}
                        autoFocus
                        style={{ flex: 1, fontSize: 13, padding: '5px 8px' }}
                      />
                      <button
                        onClick={saveName}
                        disabled={saving}
                        style={{ background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '0 8px', cursor: 'pointer', color: 'var(--bg)', flexShrink: 0 }}
                      >
                        <Check size={13} />
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={startEdit}
                    style={{
                      width: '100%', display: 'flex', alignItems: 'center', gap: 8,
                      padding: '10px 14px', background: 'none', border: 'none',
                      borderBottom: '1px solid var(--border)',
                      cursor: 'pointer', color: 'var(--text)', fontSize: 13, textAlign: 'left',
                    }}
                  >
                    <Pencil size={13} style={{ color: 'var(--text-dim)' }} />
                    Change display name
                  </button>
                )}

                <button
                  onClick={() => { signOut(); setDropdownOpen(false) }}
                  style={{
                    width: '100%', display: 'flex', alignItems: 'center', gap: 8,
                    padding: '10px 14px', background: 'none', border: 'none',
                    cursor: 'pointer', color: 'var(--text-dim)', fontSize: 13, textAlign: 'left',
                  }}
                >
                  <LogOut size={13} />
                  Sign out
                </button>
              </div>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: 'var(--text-dim)', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {displayName}
            </span>
            <button className="btn-accent" onClick={openAuthModal} style={{ fontSize: 12, padding: '5px 12px' }}>
              Sign in
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
