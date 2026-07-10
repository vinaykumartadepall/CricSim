import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { X } from 'lucide-react'
import { Spinner } from '@/components/ui/Spinner'
import { api } from '@/api/client'
import simulatingBg from '@/assets/simulating.png'
import teamsIcon from '@/assets/icon-teams.png'
import matchesIcon from '@/assets/icon-matches.png'
import deliveriesIcon from '@/assets/icon-deliveries.png'

const POLL_MS = 2500
const LIVE_UPDATES_PREVIEW_COUNT = 3

// Shared "glass" card treatment - translucent + backdrop-blurred rather than
// a solid fill, so cards read as sitting *in* the (blurred) stadium scene
// rather than pasted on top of a flat surface color.
const GLASS: CSSProperties = {
  background: 'rgba(20,20,20,0.82)',
  border: '1px solid rgba(255,255,255,0.08)',
  backdropFilter: 'blur(8px)',
  WebkitBackdropFilter: 'blur(8px)',
}

// Deterministic pseudo-random spread (seeded by index, not Math.random())
// so the particle field is stable across renders instead of jumping around.
const DUST_PARTICLES = Array.from({ length: 16 }, (_, i) => ({
  left: `${(i * 61.8) % 100}%`,
  size: 2 + (i % 3),
  duration: 16 + (i % 7) * 2,
  delay: -((i * 1.7) % 20),
  driftX: (i % 2 === 0 ? 1 : -1) * (10 + (i % 5) * 4),
  peakOpacity: 0.15 + (i % 4) * 0.06,
}))

type ResultEntry = { label: string; text: string; home: string; away: string }

type Progress = {
  completed: number
  total: number
  teams: number
  totalDeliveries: number
  results: ResultEntry[]
}

// Ring doubles as the page's loading indicator and its progress readout -
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

function StatCard({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <div className="flex-1 flex flex-col items-center gap-0.5 py-3 rounded-lg" style={GLASS}>
      <img src={icon} alt="" className="w-6 h-6 mb-0.5" style={{ objectFit: 'contain' }} />
      <div className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>{label}</div>
      <div className="text-base font-semibold tabular-nums" style={{ color: 'var(--text)' }}>{value}</div>
    </div>
  )
}

// Result text is built as "{home} vs {away} - {description}", where a
// decisive description reads "{winner} won by {margin}" (or, for a Super
// Over, "Match tied · {winner} won Super Over"; or, for a playoff match whose
// super over also tied, "Match tied · Super Over tied · {team} advanced due
// to better group stage finish"). Genuinely unresolved tie/no-result/draw
// descriptions match none of these, so this returns null for those -
// correctly falling through to the neutral style below rather than a false
// win/loss.
function parseWinner(text: string): string | null {
  const desc = text.split(' - ')[1] ?? ''
  const superOver = desc.match(/^Match tied · (.+) won Super Over$/)
  if (superOver) return superOver[1].trim()
  const tieAdvance = desc.match(/^Match tied · Super Over tied · (.+) advanced due to better group stage finish$/)
  if (tieAdvance) return tieAdvance[1].trim()
  const decisive = desc.match(/^(.+?)\s+won\s+by\s+/)
  return decisive ? decisive[1].trim() : null
}

// Timeline row - a dot + connecting line down to the next entry, matching
// the provided reference styling. Dot/label read gold by default (matching
// the reference) and only flip to red when it's specifically a loss for the
// viewer's own team; a plain win stays the same gold as everything else.
function TimelineItem({ r, userTeam, isLast }: { r: ResultEntry; userTeam?: string | null; isLast: boolean }) {
  const isMine = !!userTeam && (r.home === userTeam || r.away === userTeam)
  const winner = isMine ? parseWinner(r.text) : null
  const lost = isMine && !!winner && winner.toLowerCase() !== userTeam!.toLowerCase()
  const won = isMine && !!winner && winner.toLowerCase() === userTeam!.toLowerCase()
  const accent = lost ? 'var(--loss)' : (won ? 'var(--win)' : 'var(--score)')

  return (
    <div className="relative pl-4" style={{ paddingBottom: isLast ? 0 : 14 }}>
      <span className="absolute rounded-full" style={{ left: 0, top: 4, width: 8, height: 8, background: accent }} />
      {!isLast && (
        <span className="absolute" style={{ left: 3, top: 13, bottom: -1, width: 1, background: accent, opacity: 0.35 }} />
      )}
      <div className="text-xs leading-snug">
        <span className="font-semibold" style={{ color: accent }}>{r.label}: </span>
        <span style={{ color: 'var(--text-muted)' }}>{r.text}</span>
      </div>
    </div>
  )
}

function LiveUpdates({ results, userTeam }: { results: ResultEntry[]; userTeam?: string | null }) {
  const [showAll, setShowAll] = useState(false)

  // Latest match first.
  const reversed = [...results].reverse()
  const preview = reversed.slice(0, LIVE_UPDATES_PREVIEW_COUNT)

  return (
    <>
      <div className="w-full max-w-xs rounded-lg" style={GLASS}>
        <div className="flex items-center justify-between px-3 pt-2.5 pb-1.5">
          <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--score)' }}>Live updates</span>
          {reversed.length > LIVE_UPDATES_PREVIEW_COUNT && (
            <button
              onClick={() => setShowAll(true)}
              className="text-[11px] font-medium"
              style={{ color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer' }}
            >
              View all
            </button>
          )}
        </div>
        <div className="px-3 pb-3">
          {preview.length === 0 ? (
            <div className="text-xs" style={{ color: 'var(--text-dim)' }}>No matches completed yet…</div>
          ) : (
            preview.map((r, i) => (
              <TimelineItem key={i} r={r} userTeam={userTeam} isLast={i === preview.length - 1} />
            ))
          )}
        </div>
      </div>

      {showAll && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
          onClick={e => { if (e.target === e.currentTarget) setShowAll(false) }}
        >
          <div
            className="w-full max-w-sm rounded-2xl overflow-hidden fade-in flex flex-col"
            style={{ ...GLASS, boxShadow: '0 16px 48px rgba(0,0,0,0.5)', maxHeight: '75vh' }}
          >
            <div className="flex-shrink-0 flex items-center justify-between px-5 pt-4 pb-3" style={{ borderBottom: '1px solid var(--border)' }}>
              <h2 className="text-base font-bold m-0" style={{ color: 'var(--text)' }}>Live updates</h2>
              <button onClick={() => setShowAll(false)} style={{ color: 'var(--text-dim)', lineHeight: 0 }}>
                <X size={16} />
              </button>
            </div>
            <div className="px-5 py-4 overflow-y-auto">
              {reversed.map((r, i) => (
                <TimelineItem key={i} r={r} userTeam={userTeam} isLast={i === reversed.length - 1} />
              ))}
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  )
}

// Dedicated route for "simulation in progress" - kept separate from ResultsPage
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
  const [queuePosition, setQueuePosition] = useState<number | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!simId) return
    async function fetchStatus() {
      try {
        const s = await api.getSimStatus(simId!)
        if (s.status === 'completed') {
          clearInterval(pollRef.current!)
          if (s.simulation_type === 'match' && s.match_id) {
            navigate(`/results/${simId}/matches/${s.match_id}`, { replace: true, state: location.state })
          } else {
            navigate(`/results/${simId}`, { replace: true, state: location.state })
          }
        } else if (s.status === 'failed') {
          clearInterval(pollRef.current!)
          setStatus('failed')
          setErrorMsg(s.error || 'Simulation failed')
        } else {
          setStatus(s.status as 'pending' | 'running')
          setQueuePosition(s.status === 'pending' ? s.queue_position ?? null : null)
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

  const percent = progress ? (progress.completed / progress.total) * 100 : 0

  return (
    <>
      {/* Full-page background - fixed so it always covers the viewport
          regardless of page scroll length. Non-negative z-index (rather than
          -z-10) is deliberate: App.tsx wraps every route in its own opaque
          `background: var(--bg)` div, which paints over a negative-z-index
          descendant since that wrapper never establishes its own stacking
          context - so a negative z-index here would render below it, not
          just below this page's content.
          Blurred + scaled up slightly (so the softened edges fall outside
          the viewport) - real stadium detail competes with the cards
          otherwise; blurred, it still reads as "a stadium" without pulling
          focus. The gradient scrim is heavier at top/bottom (title, buttons)
          and lighter through the middle (progress ring, stat cards), so the
          stadium bowl behind the content is felt rather than just covered. */}
      <div
        className="fixed inset-0"
        style={{
          zIndex: 0,
          backgroundImage: `url(${simulatingBg})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          transform: 'scale(1.08)',
        }}
      />
      <div
        className="fixed inset-0"
        style={{
          zIndex: 0,
          background: 'linear-gradient(to bottom, rgba(0,0,0,0.75) 0%, rgba(0,0,0,0.45) 50%, rgba(0,0,0,0.85) 100%)',
        }}
      />
      {/* Dust motes, faintly lit as if by the floodlights - subtle enough that
          the screen feels alive even while progress is between polls. */}
      <div className="fixed inset-0 overflow-hidden" style={{ zIndex: 0, pointerEvents: 'none' }}>
        {DUST_PARTICLES.map((p, i) => (
          <span
            key={i}
            className="dust-particle"
            style={{
              left: p.left,
              width: p.size,
              height: p.size,
              animationDuration: `${p.duration}s`,
              animationDelay: `${p.delay}s`,
              '--dust-drift-x': `${p.driftX}px`,
              '--dust-peak-opacity': p.peakOpacity,
            } as CSSProperties}
          />
        ))}
      </div>

      {status === 'failed' ? (
        <div className="relative max-w-md mx-auto px-4 py-16 text-center" style={{ zIndex: 1 }}>
          <div className="text-4xl mb-4">⚠</div>
          <div className="text-base font-medium mb-2" style={{ color: 'var(--text)' }}>Simulation failed</div>
          <div className="text-sm mb-6" style={{ color: 'var(--text-muted)' }}>{errorMsg}</div>
          <button className="btn-outline" onClick={() => navigate('/')}>Back to home</button>
        </div>
      ) : (
        <div className="relative flex flex-col items-center min-h-[calc(100vh-64px)] gap-3 px-4 py-10" style={{ zIndex: 1 }}>
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
                <StatCard icon={teamsIcon} label="Teams" value={String(progress.teams)} />
                <StatCard icon={matchesIcon} label="Matches" value={String(progress.total)} />
                <StatCard icon={deliveriesIcon} label="Deliveries" value={formatCount(progress.totalDeliveries)} />
              </div>

              <LiveUpdates results={progress.results} userTeam={userTeam} />
            </>
          ) : (
            <>
              <div className="pulse-accent w-16 h-16 rounded-full flex items-center justify-center mt-1"
                style={{ border: '2px solid var(--accent)' }}>
                <Spinner size={28} />
              </div>
              {queuePosition != null && queuePosition >= 1 ? (
                <>
                  <div className="text-sm font-medium" style={{ color: 'var(--accent)' }}>
                    Waiting in line - {queuePosition} simulation{queuePosition !== 1 ? 's' : ''} ahead of you
                  </div>
                  <div className="text-xs" style={{ color: 'var(--text-dim)' }}>Only one runs at a time, so results stay fast and predictable.</div>
                </>
              ) : (
                <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Running ball-by-ball. Takes 10–30 seconds.</div>
              )}
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
      )}
    </>
  )
}
