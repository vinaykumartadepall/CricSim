import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { Spinner } from '@/components/ui/Spinner'
import { api } from '@/api/client'

const POLL_MS = 2500

type ResultEntry = { label: string; text: string; home: string; away: string }

type Progress = {
  completed: number
  total: number
  teams: number
  totalDeliveries: number
  results: ResultEntry[]
}

// Ring doubles as the page's loading indicator and its progress readout —
// one focal element instead of a spinner stacked on top of a separate bar.
// Wrapped in the same pulse-glow beat the original loading badge used, so
// the "alive, still working" cue survives even though the border is now a
// real percentage arc instead of a plain static ring.
function ProgressRing({ percent }: { percent: number }) {
  const size = 136
  const stroke = 9
  const r = (size - stroke) / 2
  const circumference = 2 * Math.PI * r
  const clamped = Math.min(100, Math.max(0, percent))
  const offset = circumference * (1 - clamped / 100)

  return (
    <div className="pulse-accent relative flex items-center justify-center rounded-full" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-2)" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none"
          stroke="var(--accent)" strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={circumference} strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 0.6s ease-out', filter: 'drop-shadow(0 0 5px var(--accent-glow))' }}
        />
      </svg>
      <div className="absolute text-2xl font-bold tabular-nums" style={{ color: 'var(--text)' }}>
        {Math.round(clamped)}%
      </div>
    </div>
  )
}

function statusPhrase(percent: number): string {
  if (percent >= 100) return 'Wrapping up…'
  if (percent >= 75) return 'Almost there!'
  if (percent >= 25) return 'Simulating ball by ball…'
  return 'Just getting started…'
}

function formatCount(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n)
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex-1 flex flex-col items-center gap-0.5 py-3 rounded-lg"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
      <div className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>{label}</div>
      <div className="text-base font-semibold tabular-nums" style={{ color: 'var(--text)' }}>{value}</div>
    </div>
  )
}

const LIVE_UPDATES_MIN_HEIGHT = 60
const LIVE_UPDATES_MAX_HEIGHT = 320

function LiveUpdates({ results, userTeam }: { results: ResultEntry[]; userTeam?: string | null }) {
  const listRef = useRef<HTMLDivElement>(null)
  const [height, setHeight] = useState(88)
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null)

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [results.length])

  // Bottom-left drag handle, vertical resize only — width stays fixed at
  // max-w-xs regardless, this only ever adjusts the scrollable list's height.
  function onResizeStart(e: ReactPointerEvent<HTMLDivElement>) {
    e.preventDefault()
    dragRef.current = { startY: e.clientY, startHeight: height }
    function onMove(ev: PointerEvent) {
      if (!dragRef.current) return
      const delta = ev.clientY - dragRef.current.startY
      setHeight(Math.min(LIVE_UPDATES_MAX_HEIGHT, Math.max(LIVE_UPDATES_MIN_HEIGHT, dragRef.current.startHeight + delta)))
    }
    function onUp() {
      dragRef.current = null
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  if (results.length === 0) return null

  return (
    <div className="relative w-full max-w-xs rounded-lg" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
      <div className="px-3 pt-2.5 pb-1.5 text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>
        Live updates
      </div>
      <div ref={listRef} className="flex flex-col gap-1 px-3 pb-2.5 overflow-y-auto" style={{ maxHeight: height }}>
        {results.map((r, i) => {
          const isMine = !!userTeam && (r.home === userTeam || r.away === userTeam)
          return (
            <div
              key={i}
              className="text-xs leading-snug pl-2 -ml-2 rounded"
              style={{
                borderLeft: `2px solid ${isMine ? 'var(--accent)' : 'transparent'}`,
                background: isMine ? 'var(--accent-tint)' : 'transparent',
              }}
            >
              <span className="font-medium" style={{ color: 'var(--accent)' }}>{r.label}: </span>
              <span style={{ color: 'var(--text-muted)' }}>{r.text}</span>
            </div>
          )
        })}
      </div>
      <div
        onPointerDown={onResizeStart}
        title="Drag to resize"
        className="absolute left-0 bottom-0 flex items-end justify-start"
        style={{ width: 16, height: 16, cursor: 'ns-resize' }}
      >
        <div className="mb-1 ml-1" style={{ width: 10, height: 3, borderRadius: 2, background: 'var(--text-dim)' }} />
      </div>
    </div>
  )
}

// Dedicated route for "simulation in progress" — kept separate from ResultsPage
// so ResultsPage only ever mounts once a simulation has actually completed.
// This has no registered help content, so HelpModal's auto-open logic can
// never race against a still-running simulation: there's nothing to open here.
export function SimulatingPage() {
  const { simId } = useParams<{ simId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const userTeam = (location.state as { teamName?: string | null } | null)?.teamName ?? null
  const [status, setStatus] = useState<'pending' | 'running' | 'failed'>('pending')
  const [errorMsg, setErrorMsg] = useState('')
  const [progress, setProgress] = useState<Progress | null>(null)
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
          setProgress(
            s.matches_total
              ? {
                  completed: s.matches_completed ?? 0,
                  total: s.matches_total,
                  teams: s.teams ?? 0,
                  totalDeliveries: s.total_deliveries ?? 0,
                  results: s.results ?? [],
                }
              : null
          )
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

  const percent = progress ? (progress.completed / progress.total) * 100 : 0

  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-64px)] gap-3 px-4">
      <div className="text-base font-medium" style={{ color: 'var(--text)' }}>Simulating tournament…</div>
      <div className="text-xs -mt-2" style={{ color: 'var(--text-dim)' }}>Please wait while the action unfolds</div>

      {progress ? (
        <>
          <ProgressRing percent={percent} />
          <div className="text-sm font-medium" style={{ color: 'var(--accent)' }}>{statusPhrase(percent)}</div>
          <div className="text-sm mb-1" style={{ color: 'var(--text-muted)' }}>
            <span className="tabular-nums font-semibold" style={{ color: 'var(--text)' }}>{progress.completed}</span>
            <span className="tabular-nums"> / {progress.total} matches simulated</span>
          </div>

          <div className="flex gap-2 w-full max-w-xs">
            <StatCard label="Teams" value={String(progress.teams)} />
            <StatCard label="Matches" value={String(progress.total)} />
            <StatCard label="Deliveries" value={formatCount(progress.totalDeliveries)} />
          </div>

          <LiveUpdates results={progress.results} userTeam={userTeam} />
        </>
      ) : (
        <>
          <div className="pulse-accent w-16 h-16 rounded-full flex items-center justify-center mt-1"
            style={{ border: '2px solid var(--accent)' }}>
            <Spinner size={28} />
          </div>
          <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Running ball-by-ball. Takes 10–30 seconds.</div>
        </>
      )}

      <button
        className="text-sm mt-3 px-5 py-2 rounded-lg font-medium"
        style={{ background: 'var(--accent-tint)', color: 'var(--accent)', border: '1px solid var(--accent)' }}
        onClick={() => navigate('/')}
      >
        Back to home
      </button>
      <div className="text-xs" style={{ color: 'var(--text-dim)' }}>Keeps running in the background</div>
    </div>
  )
}
