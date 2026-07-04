import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { Spinner } from '@/components/ui/Spinner'
import { api } from '@/api/client'

const POLL_MS = 2500

// Dedicated route for "simulation in progress" — kept separate from ResultsPage
// so ResultsPage only ever mounts once a simulation has actually completed.
// This has no registered help content, so HelpModal's auto-open logic can
// never race against a still-running simulation: there's nothing to open here.
export function SimulatingPage() {
  const { simId } = useParams<{ simId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const [status, setStatus] = useState<'pending' | 'running' | 'failed'>('pending')
  const [errorMsg, setErrorMsg] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!simId) return
    async function fetchStatus() {
      try {
        const s = await api.getSimStatus(simId!)
        if (s.status === 'completed') {
          clearInterval(pollRef.current!)
          navigate(`/results/${simId}`, { replace: true, state: location.state })
        } else if (s.status === 'failed') {
          clearInterval(pollRef.current!)
          setStatus('failed')
          setErrorMsg(s.error || 'Simulation failed')
        } else {
          setStatus(s.status as 'pending' | 'running')
        }
      } catch { /* keep polling */ }
    }
    fetchStatus()
    pollRef.current = setInterval(fetchStatus, POLL_MS)
    return () => clearInterval(pollRef.current!)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simId])

  if (status === 'failed') {
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center">
        <div className="text-4xl mb-4">⚠</div>
        <div className="text-base font-medium mb-2" style={{ color: 'var(--text)' }}>Simulation failed</div>
        <div className="text-sm mb-6" style={{ color: 'var(--text-muted)' }}>{errorMsg}</div>
        <button className="btn-outline" onClick={() => navigate('/')}>Back to home</button>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-64px)] gap-4">
      <div className="pulse-accent w-16 h-16 rounded-full flex items-center justify-center"
        style={{ border: '2px solid var(--accent)' }}>
        <Spinner size={28} />
      </div>
      <div className="text-base font-medium" style={{ color: 'var(--text)' }}>Simulating tournament…</div>
      <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Running ball-by-ball. Takes 10–30 seconds.</div>
    </div>
  )
}
