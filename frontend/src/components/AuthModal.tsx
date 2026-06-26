import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { supabase } from '@/lib/supabase'
import { useAuth } from '@/contexts/AuthContext'

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
  )
}

export function AuthModal() {
  const { authModalOpen, setAuthModalOpen } = useAuth()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const overlayRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (authModalOpen) setError('')
  }, [authModalOpen])

  if (!authModalOpen) return null

  const close = () => setAuthModalOpen(false)

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) close()
  }

  const handleGoogle = async () => {
    if (!supabase) { setError('Auth not configured — add Supabase env vars.'); return }
    setLoading(true)
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.origin },
    })
    if (error) { setError(error.message); setLoading(false) }
  }

  return (
    <div
      ref={overlayRef}
      onClick={handleOverlayClick}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 16,
      }}
    >
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 12, width: '100%', maxWidth: 320,
        padding: 32, position: 'relative', textAlign: 'center',
      }}>
        <button
          onClick={close}
          style={{ position: 'absolute', top: 14, right: 14, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', padding: 4, borderRadius: 4 }}
        >
          <X size={16} />
        </button>

        <div style={{ fontSize: 28, marginBottom: 12 }}>◈</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>
          Sign in to CricSim
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 28, lineHeight: 1.6 }}>
          Your simulations and challenge results sync across devices
        </div>

        <button
          onClick={handleGoogle}
          disabled={loading}
          style={{
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
            padding: '12px 16px',
            background: 'var(--surface-2)', border: '1px solid var(--border)',
            borderRadius: 8, cursor: loading ? 'default' : 'pointer',
            fontSize: 14, fontWeight: 500, color: 'var(--text)',
            opacity: loading ? 0.6 : 1,
          }}
        >
          <GoogleIcon />
          {loading ? 'Redirecting…' : 'Continue with Google'}
        </button>

        {error && (
          <div style={{ marginTop: 14, fontSize: 12, color: 'var(--loss)', padding: '6px 10px', background: 'rgba(239,68,68,0.08)', borderRadius: 6 }}>
            {error}
          </div>
        )}

        <div style={{ marginTop: 20, fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.6 }}>
          You can also use the app without signing in —<br />your progress is saved locally.
        </div>
      </div>
    </div>
  )
}
