import { useState, useRef, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronDown, LogOut, UserCircle, CircleHelp, Palette, Menu, LogIn } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useHelp } from '@/contexts/HelpContext'
import { useTheme } from '@/hooks/useTheme'
import { useSidebar } from '@/contexts/SidebarContext'
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
  const { displayName, isLoggedIn, signOut, openAuthModal } = useAuth()
  const { openHelp } = useHelp()
  const { openSidebar } = useSidebar()
  const navigate = useNavigate()
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <header
      className="border-b"
      style={{
        background: 'var(--surface)', borderColor: 'var(--border)',
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
      }}
    >
      <div className="flex items-center justify-between px-6 py-4"
        style={{ maxWidth: 960, margin: '0 auto' }}
      >
      <div className="flex items-center gap-3">
        <button
          onClick={openSidebar}
          title="Menu"
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--text-dim)', padding: 4, lineHeight: 0, borderRadius: 6,
          }}
          onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = 'var(--text)'}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = 'var(--text-dim)'}
        >
          <Menu size={18} />
        </button>
        <Link to="/" className="flex items-center gap-2 no-underline" style={{ whiteSpace: 'nowrap' }}>
          <span style={{ color: 'var(--accent)', fontSize: 22, fontWeight: 700, letterSpacing: '-0.5px' }}>
            ◈ CRICSIM
          </span>
        </Link>
      </div>

      <div className="flex items-center gap-3">
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
                borderRadius: 8, minWidth: 160, zIndex: 100,
                boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
                overflow: 'hidden',
              }}>
                <button
                  onClick={() => { navigate('/profile'); setDropdownOpen(false) }}
                  style={{
                    width: '100%', display: 'flex', alignItems: 'center', gap: 8,
                    padding: '10px 14px', background: 'none', border: 'none',
                    borderBottom: '1px solid var(--border)',
                    cursor: 'pointer', color: 'var(--text)', fontSize: 13, textAlign: 'left',
                  }}
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'var(--surface-2)'}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'none'}
                >
                  <UserCircle size={13} style={{ color: 'var(--text-dim)' }} />
                  Profile
                </button>
                <button
                  onClick={() => { signOut(); setDropdownOpen(false) }}
                  style={{
                    width: '100%', display: 'flex', alignItems: 'center', gap: 8,
                    padding: '10px 14px', background: 'none', border: 'none',
                    cursor: 'pointer', color: 'var(--text-dim)', fontSize: 13, textAlign: 'left',
                  }}
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'var(--surface-2)'}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'none'}
                >
                  <LogOut size={13} />
                  Sign out
                </button>
              </div>
            )}
          </div>
        ) : (
          <button
            onClick={openAuthModal}
            style={{
              display: 'flex', alignItems: 'center', gap: 7,
              background: 'none', border: '1px solid var(--border)',
              borderRadius: 20, padding: '4px 10px 4px 4px',
              cursor: 'pointer', color: 'var(--text)',
            }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
          >
            <Avatar name={displayName} />
            <span style={{ fontSize: 13, fontWeight: 500, maxWidth: 90, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-muted)' }}>
              {displayName}
            </span>
            <LogIn size={12} style={{ color: 'var(--accent)', flexShrink: 0 }} />
          </button>
        )}
      </div>
      </div>
    </header>
  )
}
