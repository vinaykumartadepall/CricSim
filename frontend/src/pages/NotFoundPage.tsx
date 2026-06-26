import { useNavigate } from 'react-router-dom'

export function NotFoundPage() {
  const navigate = useNavigate()
  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-64px)] px-4 text-center">
      <div
        className="text-8xl font-black mb-4 tabular-nums"
        style={{ color: 'var(--surface-2)', letterSpacing: '-0.05em' }}
      >
        404
      </div>
      <div className="text-lg font-semibold mb-2" style={{ color: 'var(--text)' }}>
        Page not found
      </div>
      <div className="text-sm mb-8" style={{ color: 'var(--text-muted)' }}>
        This page doesn't exist or the link is broken.
      </div>
      <button className="btn-accent" onClick={() => navigate('/')}>
        Back to home
      </button>
    </div>
  )
}
