import { useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { X, Home, BarChart2, Clock, UserCircle, Mail } from 'lucide-react'
import { useSidebar } from '@/contexts/SidebarContext'
import { useBodyScrollLock } from '@/hooks/useBodyScrollLock'
import logoUrl from '@/assets/logo.png'

// lucide-react ships no X (formerly Twitter) brand mark - inlined from
// Simple Icons rather than reusing lucide's `X` (a generic close-glyph,
// already used elsewhere in this file for the drawer's close button).
function XLogo({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  )
}

const SANS      = "'DM Sans', system-ui, sans-serif"
const LOGO_SANS = "'DM Sans', system-ui, sans-serif"

const NAV_ITEMS = [
  { path: '/',            icon: Home,        label: 'Home'           },
  { path: '/stats',       icon: BarChart2,   label: 'My Stats'       },
  { path: '/simulations', icon: Clock,       label: 'My Simulations' },
  { path: '/profile',     icon: UserCircle,  label: 'Profile'        },
]

export function Sidebar() {
  const { open, closeSidebar } = useSidebar()
  const navigate  = useNavigate()
  const location  = useLocation()

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') closeSidebar() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, closeSidebar])

  useBodyScrollLock(open)

  if (!open) return null

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
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <img src={logoUrl} alt="" style={{ width: 29, height: 32, flexShrink: 0, objectFit: 'contain' }} />
            <span style={{ fontFamily: LOGO_SANS, fontSize: 15, fontWeight: 800, letterSpacing: 0, lineHeight: 1.05 }}>
              <div style={{ color: 'var(--text)' }}>Cric</div>
              <div style={{ color: 'var(--accent)' }}>Simulator</div>
            </span>
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
        </nav>

        {/* Bottom-anchored: contact links, then attribution fine print */}
        <div style={{ marginTop: 'auto', flexShrink: 0 }}>
          {/* Contact */}
          <div style={{
            borderTop: '1px solid var(--border)',
            padding: '12px 16px',
          }}>
            <div style={{
              fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
              color: 'var(--text-dim)', marginBottom: 8,
            }}>
              Contact
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <a
                href="mailto:tadepallivk1109@gmail.com"
                title="Email"
                aria-label="Email"
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  width: 34, height: 34, borderRadius: 8,
                  background: 'var(--surface-2)', border: '0.5px solid var(--border)',
                  color: 'var(--text-muted)',
                }}
                onMouseEnter={e => {
                  const el = e.currentTarget as HTMLElement
                  el.style.color = 'var(--accent)'; el.style.borderColor = 'var(--accent)'
                }}
                onMouseLeave={e => {
                  const el = e.currentTarget as HTMLElement
                  el.style.color = 'var(--text-muted)'; el.style.borderColor = 'var(--border)'
                }}
              >
                <Mail size={17} />
              </a>
              <a
                href="https://x.com/CricSimulator"
                target="_blank" rel="noopener noreferrer"
                title="X"
                aria-label="X"
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  width: 34, height: 34, borderRadius: 8,
                  background: 'var(--surface-2)', border: '0.5px solid var(--border)',
                  color: 'var(--text-muted)',
                }}
                onMouseEnter={e => {
                  const el = e.currentTarget as HTMLElement
                  el.style.color = 'var(--accent)'; el.style.borderColor = 'var(--accent)'
                }}
                onMouseLeave={e => {
                  const el = e.currentTarget as HTMLElement
                  el.style.color = 'var(--text-muted)'; el.style.borderColor = 'var(--border)'
                }}
              >
                <XLogo size={16} />
              </a>
            </div>
          </div>

          {/* Attribution footer */}
          <div style={{
            borderTop: '1px solid var(--border)',
            padding: '10px 16px',
            fontSize: 10, color: 'var(--text-dim)',
            lineHeight: 1.6,
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
      </div>
    </>
  )
}
