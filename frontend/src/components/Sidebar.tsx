import { useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { X, Home, BarChart2, Clock, UserCircle } from 'lucide-react'
import { useSidebar } from '@/contexts/SidebarContext'
import { useBodyScrollLock } from '@/hooks/useBodyScrollLock'
import logoUrl from '@/assets/logo.png'

const SERIF = "'DM Serif Display', Georgia, 'Times New Roman', serif"
const SANS  = "'DM Sans', system-ui, sans-serif"

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
        </nav>

        {/* Attribution footer */}
        <div style={{
          marginTop: 'auto',
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
