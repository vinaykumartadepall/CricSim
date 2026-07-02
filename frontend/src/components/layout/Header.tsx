import { useState, useRef, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronDown, LogOut, UserCircle, CircleHelp, Menu, LogIn } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useHelp } from '@/contexts/HelpContext'
import { useSidebar } from '@/contexts/SidebarContext'
import logoUrl from '@/assets/logo.png'

const SERIF = "'DM Serif Display', Georgia, 'Times New Roman', serif"

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
        <Link to="/" className="flex items-center gap-1 no-underline" style={{ whiteSpace: 'nowrap' }}>
          <img src={logoUrl} alt="" style={{ width: 24, height: 26, flexShrink: 0, objectFit: 'contain' }} />
          <span style={{ fontFamily: SERIF, fontSize: 24, fontWeight: 400, letterSpacing: '0.01em' }}>
            Cric<span style={{ color: 'var(--accent)' }}>Sim</span>
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
