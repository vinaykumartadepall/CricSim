import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { X, Home, BarChart2, Clock, Check, UserCircle, Palette, ChevronRight } from 'lucide-react'
import { useSidebar } from '@/contexts/SidebarContext'
import { useTheme } from '@/hooks/useTheme'
import { useBodyScrollLock } from '@/hooks/useBodyScrollLock'
import { useAuth } from '@/contexts/AuthContext'
import logoUrl from '@/assets/logo.png'
import type { Theme } from '@/types'

const SERIF = "'DM Serif Display', Georgia, 'Times New Roman', serif"
const SANS  = "'DM Sans', system-ui, sans-serif"

const NAV_ITEMS = [
  { path: '/',            icon: Home,        label: 'Home'           },
  { path: '/stats',       icon: BarChart2,   label: 'My Stats'       },
  { path: '/simulations', icon: Clock,       label: 'My Simulations' },
  { path: '/profile',     icon: UserCircle,  label: 'Profile'        },
]

const THEMES: { key: Theme; label: string; dot: string }[] = [
  { key: 'ember-amber',   label: 'Amber',   dot: '#FFB700' },
  { key: 'ember-emerald', label: 'Emerald', dot: '#0ECB81' },
  { key: 'ember-crimson', label: 'Crimson', dot: '#E8364F' },
  { key: 'ember-ice',     label: 'Ice',     dot: '#4FACFF' },
]

function initials(name: string): string {
  return name
    .split(/[\s_]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join('')
}

export function Sidebar() {
  const { open, closeSidebar } = useSidebar()
  const { theme, setTheme }    = useTheme()
  const { displayName }        = useAuth()
  const navigate  = useNavigate()
  const location  = useLocation()
  const [themeOpen, setThemeOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') closeSidebar() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, closeSidebar])

  useBodyScrollLock(open)

  // Close theme panel when sidebar closes
  useEffect(() => { if (!open) setThemeOpen(false) }, [open])

  if (!open) return null

  const abbr = initials(displayName)
  const currentTheme = THEMES.find(t => t.key === theme)

  const navItemStyle = (active: boolean) => ({
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '11px 12px', borderRadius: 8,
    background: active ? 'var(--accent-tint)' : 'none',
    border: active ? '0.5px solid var(--accent)' : '0.5px solid transparent',
    cursor: 'pointer', width: '100%', textAlign: 'left' as const,
    color: active ? 'var(--accent)' : 'var(--text-muted)',
    fontSize: 14, fontWeight: active ? 600 : 400,
    transition: 'background 0.12s, color 0.12s',
  })

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={closeSidebar}
        style={{
          position: 'fixed', inset: 0, zIndex: 200,
          background: 'rgba(0,0,0,0.55)',
          backdropFilter: 'blur(2px)',
        }}
      />

      {/* Drawer */}
      <div
        style={{
          position: 'fixed', top: 0, left: 0, bottom: 0,
          width: 256, zIndex: 201,
          background: 'var(--surface)',
          borderRight: '1px solid var(--border)',
          display: 'flex', flexDirection: 'column',
          boxShadow: '4px 0 24px rgba(0,0,0,0.4)',
          overflowY: 'auto',
          fontFamily: SANS,
        }}
      >
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 16px',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: SERIF, fontSize: 19, letterSpacing: '0.01em' }}>
            <img src={logoUrl} alt="" style={{ width: 20, height: 22, flexShrink: 0, objectFit: 'contain' }} />
            <span>Cric<span style={{ color: 'var(--accent)' }}>Sim</span></span>
          </span>
          <button
            onClick={closeSidebar}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', padding: 4, lineHeight: 0 }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Nav items */}
        <nav style={{ padding: '10px 8px', display: 'flex', flexDirection: 'column', gap: 2 }}>
          {NAV_ITEMS.map(({ path, icon: Icon, label }) => {
            const active = location.pathname === path
            return (
              <button
                key={path}
                onClick={() => { navigate(path); closeSidebar() }}
                style={navItemStyle(active)}
                onMouseEnter={e => { if (!active) (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.04)' }}
                onMouseLeave={e => { if (!active) (e.currentTarget as HTMLElement).style.background = 'none' }}
              >
                <Icon size={16} />
                {label}
              </button>
            )
          })}

          {/* Theme — expandable nav item */}
          <button
            onClick={() => setThemeOpen(o => !o)}
            style={navItemStyle(false)}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.04)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'none'}
          >
            <Palette size={16} />
            <span style={{ flex: 1 }}>Theme</span>
            {currentTheme && !themeOpen && (
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: currentTheme.dot, flexShrink: 0 }} />
            )}
            <ChevronRight
              size={13}
              style={{
                color: 'var(--text-dim)', flexShrink: 0,
                transform: themeOpen ? 'rotate(90deg)' : 'none',
                transition: 'transform 0.18s',
              }}
            />
          </button>

          {/* Theme options — inline expansion */}
          {themeOpen && (
            <div style={{ paddingLeft: 10, paddingBottom: 4, display: 'flex', flexDirection: 'column', gap: 1 }}>
              {THEMES.map(t => (
                <button
                  key={t.key}
                  onClick={() => setTheme(t.key)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '9px 12px', borderRadius: 7,
                    background: t.key === theme ? 'var(--surface-2)' : 'none',
                    border: 'none', cursor: 'pointer', width: '100%', textAlign: 'left',
                    color: t.key === theme ? 'var(--text)' : 'var(--text-muted)',
                    fontSize: 13, transition: 'background 0.12s',
                  }}
                  onMouseEnter={e => { if (t.key !== theme) (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.04)' }}
                  onMouseLeave={e => { if (t.key !== theme) (e.currentTarget as HTMLElement).style.background = 'none' }}
                >
                  <span style={{ width: 9, height: 9, borderRadius: '50%', background: t.dot, flexShrink: 0 }} />
                  <span style={{ flex: 1 }}>{t.label}</span>
                  {t.key === theme && <Check size={12} style={{ color: 'var(--accent)', flexShrink: 0 }} />}
                </button>
              ))}
            </div>
          )}
        </nav>

        {/* User profile */}
        <div style={{
          marginTop: 'auto',
          borderTop: '1px solid var(--border)',
          padding: '16px 16px',
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 40, height: 40, borderRadius: '50%',
              background: 'var(--accent)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 14, fontWeight: 700, color: 'var(--bg)',
              flexShrink: 0,
            }}>
              {abbr}
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{
                fontSize: 14, fontWeight: 600, color: 'var(--text)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {displayName}
              </div>
            </div>
          </div>
        </div>

        {/* Attribution footer */}
        <div style={{
          borderTop: '1px solid var(--border)',
          padding: '10px 16px',
          fontSize: 10, color: 'var(--text-dim)',
          lineHeight: 1.6,
          flexShrink: 0,
        }}>
          Match data from{' '}
          <a href="https://cricsheet.org" target="_blank" rel="noopener noreferrer"
            style={{ color: 'var(--text-dim)', textDecoration: 'underline' }}>
            Cricsheet.org
          </a>
          <br />
          Open Data Commons Attribution License
        </div>
      </div>
    </>
  )
}
