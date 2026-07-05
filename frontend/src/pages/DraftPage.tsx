import { createPortal } from 'react-dom'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Copy, Check, ArrowUp, ArrowDown, Search, Zap, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useHelp } from '@/contexts/HelpContext'
import { hasSeenHelp, markHelpSeen } from '@/config/helpContent'
import { FilterDropdown } from '@/components/ui/FilterDropdown'
import type { MultiplayerPlayer, PlayerFilterOptions, RoomState } from '@/types'

const DRAFT_HELP_KEY = '/multiplayer/draft'

// ── Constants ──────────────────────────────────────────────────────────────────

// Derived from the current origin, same as api/client.ts's relative '/cricsimapi' —
// a hardcoded 'ws://localhost:8000' here meant every production browser tried to
// open a websocket to its OWN localhost:8000 instead of the real server.
const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const WS_BASE = `${WS_PROTOCOL}//${window.location.host}/cricsimapi/multiplayer/ws`
const SEARCH_DEBOUNCE_MS = 300
const PICK_TIMER_TOTAL   = 60
const PING_INTERVAL_MS   = 30_000

// ── Avatar ────────────────────────────────────────────────────────────────────

const AVATAR_COLORS = ['#00E5CC', '#F59E0B', '#0EA5E9', '#8B5CF6', '#EF4444', '#22C55E']

function Headshot({ url, name, size = 32 }: { url: string | null | undefined; name: string | null | undefined; size?: number }) {
  const [errored, setErrored] = useState(false)
  const safeName = name || '?'
  const initials = safeName.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
  const color = AVATAR_COLORS[safeName.charCodeAt(0) % AVATAR_COLORS.length]
  if (url && !errored) {
    return (
      <img src={url} alt={safeName} width={size} height={size}
        className="rounded-full object-cover flex-shrink-0"
        style={{ width: size, height: size }}
        onError={() => setErrored(true)}
      />
    )
  }
  return (
    <div className="rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold"
      style={{ width: size, height: size, background: `${color}22`, color, border: `1px solid ${color}44` }}>
      {initials}
    </div>
  )
}

// ── Role badge ────────────────────────────────────────────────────────────────

function RoleBadge({ role }: { role: string | null | undefined }) {
  if (!role) return null
  const styles: Record<string, { bg: string; color: string }> = {
    'Batter':      { bg: 'rgba(59,130,246,0.12)',   color: 'var(--accent)' },
    'Bowler':      { bg: 'rgba(249,115,22,0.12)',  color: '#f97316' },
    'All-rounder': { bg: 'rgba(14,165,233,0.12)',  color: '#0ea5e9' },
    'Keeper':      { bg: 'rgba(245,158,11,0.12)',   color: 'var(--score)' },
  }
  const s = styles[role] ?? { bg: 'rgba(255,255,255,0.08)', color: 'var(--text-muted)' }
  return (
    <span className="text-xs px-1.5 py-0.5 rounded font-medium shrink-0" style={{ background: s.bg, color: s.color }}>
      {role}
    </span>
  )
}

// ── Copy button ───────────────────────────────────────────────────────────────

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard.writeText(text).catch(() => {})
    setCopied(true); setTimeout(() => setCopied(false), 1800)
  }
  return (
    <button onClick={copy}
      className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all"
      style={{
        background: copied ? 'rgba(34,197,94,0.12)' : 'var(--surface-2)',
        color: copied ? 'var(--win)' : 'var(--text-muted)',
        border: `1px solid ${copied ? 'rgba(34,197,94,0.3)' : 'var(--border)'}`,
      }}>
      {copied ? <Check size={11} /> : <Copy size={11} />}
      {label ?? (copied ? 'Copied!' : 'Copy')}
    </button>
  )
}

// ── Timer ring ─────────────────────────────────────────────────────────────────

function TimerRing({ seconds, total = PICK_TIMER_TOTAL, size = 56 }: { seconds: number; total?: number; size?: number }) {
  const r = size / 2 - 4
  const circumference = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(1, seconds / total))
  const urgent = seconds < 10
  const color = urgent ? 'var(--loss)' : 'var(--accent)'
  return (
    <div className="relative flex items-center justify-center flex-shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth={4} />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={4}
          strokeDasharray={`${circumference * pct} ${circumference}`} strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 1s linear, stroke 0.3s' }} />
      </svg>
      <span className="absolute text-sm font-bold" style={{ color: urgent ? 'var(--loss)' : 'var(--text)' }}>
        {seconds}
      </span>
    </div>
  )
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function Toast({ message, onDone }: { message: string; onDone: () => void }) {
  useEffect(() => { const t = setTimeout(onDone, 3500); return () => clearTimeout(t) }, [onDone])
  return (
    <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl text-sm font-medium shadow-lg fade-in"
      style={{ background: 'rgba(239,68,68,0.9)', color: '#fff', backdropFilter: 'blur(8px)' }}>
      {message}
    </div>
  )
}

// ── Pick notification banner ───────────────────────────────────────────────────

interface PickNotif { playerName: string; teamName: string; displayName: string; autoPicked: boolean }

const NOTIF_DURATION = 15_000
const NW = 360, NH = 52, NR = 12
// Perimeter of the rounded rect used for the SVG timer border
const NOTIF_PERIM = 2 * (NW - 2 * NR) + 2 * (NH - 2 * NR) + 2 * Math.PI * NR

function PickNotification({ notif, onDone }: { notif: PickNotif; onDone: () => void }) {
  const [dx, setDx]           = useState(0)
  const [leaving, setLeaving] = useState(false)
  const dragStartX            = useRef<number | null>(null)
  const dragging              = useRef(false)

  const onDoneRef = useRef(onDone)
  useEffect(() => { onDoneRef.current = onDone })
  useEffect(() => {
    const t = setTimeout(() => onDoneRef.current(), NOTIF_DURATION)
    return () => clearTimeout(t)
  }, [])

  function startDrag(clientX: number) {
    dragStartX.current = clientX
    dragging.current   = true
  }
  function moveDrag(clientX: number) {
    if (!dragging.current || dragStartX.current === null) return
    setDx(clientX - dragStartX.current)
  }
  function endDrag() {
    if (!dragging.current) return
    dragging.current = false
    if (Math.abs(dx) > 80) {
      setLeaving(true)
      setTimeout(onDone, 200)
    } else {
      setDx(0)
    }
    dragStartX.current = null
  }

  const opacity    = leaving ? 0 : Math.max(0, 1 - Math.abs(dx) / 200)
  const translateX = leaving ? (dx >= 0 ? 440 : -440) : dx
  const isSpring   = !leaving && dx === 0

  return (
    <div className="fixed top-0 left-0 right-0 z-50 flex justify-center py-2 px-4 fade-in"
      style={{ pointerEvents: 'none' }}>
      <style>{`
        @keyframes pick-border-drain {
          from { stroke-dashoffset: 0; }
          to   { stroke-dashoffset: ${NOTIF_PERIM.toFixed(1)}; }
        }
      `}</style>
      <div
        style={{
          position: 'relative', width: NW,
          transform: `translateX(${translateX}px)`,
          opacity,
          transition: leaving
            ? 'transform 0.2s ease, opacity 0.2s ease'
            : isSpring ? 'transform 0.25s cubic-bezier(.22,1,.36,1)' : 'none',
          pointerEvents: 'auto',
          cursor: dragging.current ? 'grabbing' : 'grab',
          userSelect: 'none',
        }}
        onMouseDown={e => startDrag(e.clientX)}
        onMouseMove={e => moveDrag(e.clientX)}
        onMouseUp={endDrag}
        onMouseLeave={endDrag}
        onTouchStart={e => startDrag(e.touches[0].clientX)}
        onTouchMove={e => { e.preventDefault(); moveDrag(e.touches[0].clientX) }}
        onTouchEnd={endDrag}
      >
        {/* SVG timer border — drains over NOTIF_DURATION */}
        <svg width={NW} height={NH} style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none' }}>
          {/* dim base border */}
          <rect x={0.5} y={0.5} width={NW - 1} height={NH - 1} rx={NR} ry={NR}
            fill="none" stroke="var(--border)" strokeWidth={1} />
          {/* animated accent border */}
          <rect x={0.5} y={0.5} width={NW - 1} height={NH - 1} rx={NR} ry={NR}
            fill="none" stroke="var(--accent)" strokeWidth={1.5} strokeLinecap="round"
            strokeDasharray={NOTIF_PERIM.toFixed(1)}
            strokeDashoffset={0}
            style={{ animation: `pick-border-drain ${NOTIF_DURATION}ms linear forwards` }}
          />
        </svg>

        {/* Content */}
        <div style={{
          width: NW, height: NH, borderRadius: NR,
          background: 'var(--surface)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '0 16px',
        }}>
          <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text)', maxWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {notif.playerName}
          </span>
          <span style={{ opacity: 0.45, flexShrink: 0, fontSize: 13 }}>→</span>
          <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {notif.teamName}
          </span>
          {notif.autoPicked && (
            <span style={{ fontSize: 11, padding: '2px 6px', borderRadius: 4, flexShrink: 0,
              background: 'rgba(245,158,11,0.12)', color: 'var(--score)' }}>
              timer
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface PickedPlayer {
  player_id: number; name: string; role: string; headshot_url: string | null; is_keeper: boolean
}

interface FullRoomState extends RoomState {
  host_id?: string
  ready_members?: string[]
}

// ── Team chips ────────────────────────────────────────────────────────────────

function TeamChips({
  room, clientId, viewingId, onSelect, readyMembers,
}: {
  room: FullRoomState; clientId: string; viewingId: string; onSelect: (id: string) => void; readyMembers?: string[]
}) {
  return (
    <div className="flex gap-2 px-3 py-2 overflow-x-auto flex-shrink-0" style={{ borderBottom: '1px solid var(--border)' }}>
      {room.members.map(m => {
        const active   = viewingId === m.client_id
        const isMe     = m.client_id === clientId
        const isReady  = readyMembers?.includes(m.client_id)
        const isPicker = room.current_picker === m.client_id
        return (
          <button key={m.client_id}
            onClick={() => onSelect(m.client_id)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-all flex-shrink-0"
            style={{
              background: active ? 'var(--accent-tint)' : 'var(--surface-2)',
              color: active ? 'var(--accent)' : 'var(--text-muted)',
              border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
            }}>
            {isReady && <CheckCircle2 size={11} style={{ color: 'var(--win)' }} />}
            {isPicker && !isReady && <span className="pulse-accent inline-block w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: 'var(--accent)' }} />}
            {m.display_name}{isMe ? ' (you)' : ''}
            <span style={{ color: 'var(--text-dim)' }}>{m.squad.length}/11</span>
          </button>
        )
      })}
    </div>
  )
}

// ── Squad view ────────────────────────────────────────────────────────────────

function SquadView({
  squad, playerMap, isMyTeam, onMoveUp, onMoveDown,
}: {
  squad: number[]; playerMap: Map<number, PickedPlayer>; isMyTeam: boolean
  onMoveUp?: (i: number) => void; onMoveDown?: (i: number) => void
}) {
  return (
    <div className="flex flex-col gap-1.5 px-3 py-3 overflow-y-auto flex-1" style={{ minHeight: 0 }}>
      {Array.from({ length: 11 }).map((_, idx) => {
        const pid = squad[idx] ?? null
        const p   = pid != null ? playerMap.get(pid) : null
        if (!p) {
          return (
            <div key={idx} className="flex items-center gap-3 px-3 py-2 rounded-lg"
              style={{ border: '1px dashed var(--border)', opacity: 0.4 }}>
              <span className="text-xs font-mono w-4 text-right flex-shrink-0" style={{ color: 'var(--text-dim)' }}>{idx + 1}</span>
              <div className="w-7 h-7 rounded-full flex-shrink-0" style={{ background: 'var(--surface-2)' }} />
              <span className="text-xs" style={{ color: 'var(--text-dim)' }}>Empty slot</span>
            </div>
          )
        }
        return (
          <div key={pid} className="flex items-center gap-2.5 px-3 py-2 rounded-lg"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
            <span className="text-xs font-mono w-4 text-right flex-shrink-0" style={{ color: 'var(--text-dim)' }}>{idx + 1}</span>
            <Headshot url={p.headshot_url} name={p.name} size={28} />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium truncate" style={{ color: 'var(--text)' }}>{p.name}</div>
            </div>
            <RoleBadge role={p.role} />
            {isMyTeam && onMoveUp && onMoveDown && (
              <div className="flex gap-0.5 flex-shrink-0">
                <button onClick={() => onMoveUp(idx)} disabled={idx === 0}
                  className="p-1 rounded" style={{ color: idx === 0 ? 'var(--text-dim)' : 'var(--text-muted)' }}>
                  <ArrowUp size={12} />
                </button>
                <button onClick={() => onMoveDown(idx)} disabled={idx >= squad.length - 1}
                  className="p-1 rounded" style={{ color: idx >= squad.length - 1 ? 'var(--text-dim)' : 'var(--text-muted)' }}>
                  <ArrowDown size={12} />
                </button>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Player pick popup ─────────────────────────────────────────────────────────

function PickPanel({
  open, onClose, timer, draftedIds, pickedByName, onPick, needsKeeper, isMyTurn,
}: {
  open: boolean; onClose: () => void
  timer: number; draftedIds: Set<number>; pickedByName: Map<number, string>
  onPick: (id: number) => void; needsKeeper: boolean; isMyTurn: boolean
}) {
  const [query, setQuery]               = useState('')
  const [roles, setRoles]               = useState<string[]>([])
  const [countryIds, setCountryIds]     = useState<number[]>([])
  const [battingStyles, setBattingStyles] = useState<string[]>([])
  const [bowlingStyles, setBowlingStyles] = useState<string[]>([])
  const [filterOptions, setFilterOptions] = useState<PlayerFilterOptions | null>(null)
  const [results, setResults]           = useState<MultiplayerPlayer[]>([])
  const [loading, setLoading]           = useState(false)
  const debounceRef                     = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inputRef                        = useRef<HTMLInputElement>(null)

  const hasQuery  = query.trim().length > 0
  const hasFilter = roles.length > 0 || countryIds.length > 0 || battingStyles.length > 0 || bowlingStyles.length > 0

  // Last pick with no keeper yet forces the role filter to Keeper — same
  // enforcement as before, just expressed through the general role filter
  // instead of a dedicated "keepers only" toggle.
  useEffect(() => { if (needsKeeper && isMyTurn) setRoles(['Keeper']) }, [needsKeeper, isMyTurn])
  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 100) }, [open])

  useEffect(() => {
    import('@/api/client').then(({ api }) =>
      api.getPlayerFilters().then(setFilterOptions).catch(() => setFilterOptions(null))
    )
  }, [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!hasQuery && !hasFilter) { setResults([]); return }
    debounceRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const { api } = await import('@/api/client')
        setResults(await api.searchPlayers(query.trim(), { roles, countryIds, battingStyles, bowlingStyles }))
      } catch { setResults([]) } finally { setLoading(false) }
    }, SEARCH_DEBOUNCE_MS)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query, roles, countryIds, battingStyles, bowlingStyles, hasQuery, hasFilter])

  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-50 flex flex-col justify-end md:items-center md:justify-center"
      style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="w-full md:max-w-md rounded-t-2xl md:rounded-2xl flex flex-col overflow-hidden fade-in"
        style={{ background: 'var(--surface)', border: '1px solid var(--border)', maxHeight: '85vh', boxShadow: '0 -8px 32px rgba(0,0,0,0.4)' }}>

        {/* Handle bar (mobile) */}
        <div className="flex justify-center pt-3 pb-1 md:hidden">
          <div className="w-10 h-1 rounded-full" style={{ background: 'var(--border)' }} />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border)' }}>
          <div className="flex items-center gap-2">
            {isMyTurn ? (
              <>
                <span className="text-sm font-bold" style={{ color: 'var(--accent)' }}>YOUR TURN</span>
                <TimerRing seconds={timer} size={36} />
              </>
            ) : (
              <span className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>Player Search</span>
            )}
            {needsKeeper && isMyTurn && (
              <div className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg"
                style={{ background: 'rgba(239,68,68,0.08)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.2)' }}>
                <AlertTriangle size={11} />Last pick — need WK!
              </div>
            )}
          </div>
          <button onClick={onClose} className="text-xs px-2 py-1 rounded" style={{ color: 'var(--text-muted)' }}>✕</button>
        </div>

        {/* Search bar + filters */}
        <div className="px-4 py-3 flex-shrink-0 flex flex-col gap-2">
          <input ref={inputRef} className="input w-full" placeholder="Search players…"
            value={query} onChange={e => setQuery(e.target.value)} />
          <div className="grid grid-cols-2 gap-2">
            <FilterDropdown
              placeholder="All roles"
              values={roles}
              disabled={needsKeeper && isMyTurn}
              options={(filterOptions?.roles ?? []).map(r => ({ value: r, label: r }))}
              onChange={setRoles}
            />
            <FilterDropdown
              placeholder="All countries"
              values={countryIds.map(String)}
              searchable
              options={(filterOptions?.countries ?? []).map(c => ({ value: String(c.country_id), label: c.name }))}
              onChange={vals => setCountryIds(vals.map(Number))}
            />
            <FilterDropdown
              placeholder="Any bat type"
              values={battingStyles}
              options={(filterOptions?.batting_styles ?? []).map(b => ({ value: b, label: b }))}
              onChange={setBattingStyles}
            />
            <FilterDropdown
              placeholder="Any bowl type"
              values={bowlingStyles}
              options={(filterOptions?.bowling_styles ?? []).map(b => ({ value: b, label: b }))}
              onChange={setBowlingStyles}
            />
          </div>
        </div>

        {/* Results */}
        <div className="overflow-y-auto flex-1 px-2 pb-4" style={{ minHeight: 0 }}>
          {loading && (
            <div className="flex justify-center py-6">
              <span className="spin inline-block w-5 h-5 rounded-full border-2" style={{ borderColor: 'var(--accent-tint)', borderTopColor: 'var(--accent)' }} />
            </div>
          )}
          {!loading && results.length === 0 && (hasQuery || hasFilter) && (
            <div className="text-center py-6 text-sm" style={{ color: 'var(--text-dim)' }}>No players found</div>
          )}
          {!loading && results.length === 0 && !hasQuery && !hasFilter && (
            <div className="text-center py-6 text-sm" style={{ color: 'var(--text-dim)' }}>
              {isMyTurn ? 'Search for a player to draft' : 'Not your turn'}
            </div>
          )}
          {results.map(p => {
            const drafted = draftedIds.has(p.player_id)
            return (
              <button key={p.player_id}
                onClick={() => { if (!drafted && isMyTurn) { onPick(p.player_id); onClose() } }}
                disabled={drafted || !isMyTurn}
                className="flex items-center gap-3 px-3 py-2.5 rounded-xl w-full text-left transition-all"
                style={{ opacity: drafted ? 0.38 : 1, cursor: drafted || !isMyTurn ? 'not-allowed' : 'pointer' }}
                onMouseEnter={e => { if (!drafted && isMyTurn) (e.currentTarget as HTMLElement).style.background = 'var(--accent-tint)' }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}>
                <Headshot url={p.headshot_url} name={p.name} size={32} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate flex items-baseline gap-1.5" style={{ color: drafted ? 'var(--text-dim)' : 'var(--text)' }}>
                    <span className="truncate">{p.name}</span>
                    {p.country && (
                      <span className="text-xs font-normal flex-shrink-0" style={{ color: 'var(--text-dim)' }}>{p.country}</span>
                    )}
                  </div>
                  {drafted ? (
                    <div className="text-xs" style={{ color: 'var(--text-dim)' }}>
                      Already present in {pickedByName.get(p.player_id) ?? 'another team'}
                    </div>
                  ) : (p.batting_style || p.bowling_style) ? (
                    <div className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                      {p.batting_style}{p.bowling_style ? ` · ${p.bowling_style}` : ''}
                    </div>
                  ) : null}
                </div>
                <RoleBadge role={p.role} />
              </button>
            )
          })}
        </div>
      </div>
    </div>,
    document.body,
  )
}

// ── Waiting room ──────────────────────────────────────────────────────────────

function WaitingRoom({ room, clientId, onStart, starting, readyMembers, myReady, onReady, onKick }: {
  room: FullRoomState; clientId: string; onStart: () => void; starting: boolean
  readyMembers: string[]; myReady: boolean; onReady: () => void; onKick: (targetId: string) => void
}) {
  const shareUrl    = `${window.location.origin}/join/${room.room_id}`
  const isHost      = clientId === room.host_id
  const isTournament = room.mode === 'tournament'
  const minToStart  = isTournament ? 4 : 2
  const hasMinPlayers = room.members.length >= minToStart
  const allReady    = readyMembers.length >= room.members.length
  const canStart    = hasMinPlayers && allReady
  const allJoined   = room.members.length >= room.player_count
  const needed      = minToStart - room.members.length

  return (
    <div className="flex flex-col items-center px-6 pt-12 pb-8">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="text-xs font-medium tracking-widest uppercase mb-2" style={{ color: 'var(--accent)' }}>Waiting Room</div>
          <h2 className="text-2xl font-bold mb-1" style={{ color: 'var(--text)' }}>{room.tournament_name}</h2>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            {isTournament ? 'Tournament' : '1 vs 1 Match'} · {room.match_format ?? 'T20'} · {room.members.length}/{room.player_count} joined
          </p>
        </div>

        <div className="card p-4 mb-4">
          <div className="text-xs mb-2" style={{ color: 'var(--text-dim)' }}>Room Code</div>
          <div className="flex items-center gap-3">
            <div className="font-mono text-2xl font-bold tracking-[0.2em] px-4 py-2 rounded-lg flex-1 text-center"
              style={{ background: 'var(--surface-2)', color: 'var(--accent)', letterSpacing: '0.25em' }}>
              {room.room_id}
            </div>
            <CopyButton text={room.room_id} />
          </div>
          <div className="flex items-center gap-2 mt-3">
            <div className="flex-1 min-w-0 text-xs font-mono px-3 py-1.5 rounded-lg truncate"
              style={{ background: 'var(--surface-2)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>
              {shareUrl}
            </div>
            <CopyButton text={shareUrl}/>
          </div>
        </div>

        <div className="card p-4 mb-5">
          <div className="text-xs font-medium mb-3" style={{ color: 'var(--text-muted)' }}>
            Players · {room.members.length}/{room.player_count}
          </div>
          <div className="flex flex-col gap-2">
            {room.members.map(m => {
              const isReady = readyMembers.includes(m.client_id)
              return (
                <div key={m.client_id} className="flex items-center gap-2.5">
                  <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: m.connected ? 'var(--win)' : 'var(--text-dim)' }} />
                  <span className="text-sm flex-1" style={{ color: m.connected ? 'var(--text)' : 'var(--text-muted)' }}>
                    {m.display_name}
                    {m.client_id === clientId && <span className="ml-1 text-xs" style={{ color: 'var(--text-dim)' }}>(you)</span>}
                  </span>
                  {isReady && <CheckCircle2 size={13} style={{ color: 'var(--win)' }} />}
                  {m.client_id === room.host_id && (
                    <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'var(--accent-tint)', color: 'var(--accent)' }}>Host</span>
                  )}
                  {isHost && m.client_id !== clientId && (
                    <button
                      onClick={() => onKick(m.client_id)}
                      className="text-xs px-1.5 py-0.5 rounded transition-colors"
                      style={{ background: 'transparent', color: 'var(--text-dim)', border: '1px solid var(--border)' }}
                      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = 'var(--loss)'; (e.currentTarget as HTMLElement).style.borderColor = 'var(--loss)' }}
                      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = 'var(--text-dim)'; (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)' }}
                    >
                      Kick
                    </button>
                  )}
                </div>
              )
            })}
            {Array.from({ length: Math.max(0, room.player_count - room.members.length) }).map((_, i) => (
              <div key={`empty-${i}`} className="flex items-center gap-2.5">
                <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: 'var(--border)' }} />
                <span className="text-xs" style={{ color: 'var(--text-dim)' }}>Empty slot</span>
              </div>
            ))}
          </div>
        </div>

        <button
          onClick={onReady}
          disabled={myReady}
          className="w-full py-2.5 rounded-xl font-medium text-sm mb-2 flex items-center justify-center gap-2 transition-all"
          style={{
            background: myReady ? 'var(--accent-tint)' : 'var(--surface-2)',
            color: myReady ? 'var(--win)' : 'var(--text)',
            border: `1px solid ${myReady ? 'var(--win)' : 'var(--border)'}`,
            cursor: myReady ? 'default' : 'pointer',
          }}
        >
          {myReady ? <><CheckCircle2 size={15} /> You're ready</> : "I'm ready"}
        </button>
        <p className="text-xs text-center mb-4" style={{ color: 'var(--text-dim)' }}>
          {readyMembers.length}/{room.members.length} players ready
        </p>

        {isHost ? (
          <>
            <button onClick={onStart} disabled={starting || !canStart}
              className="w-full py-3 rounded-xl font-semibold text-base transition-all"
              style={{
                background: (starting || !canStart) ? 'var(--accent-tint)' : 'var(--accent)',
                color: (starting || !canStart) ? 'var(--text-dim)' : 'var(--bg)',
                cursor: (starting || !canStart) ? 'not-allowed' : 'pointer',
              }}
              onMouseEnter={e => canStart && !starting && ((e.currentTarget as HTMLElement).style.background = 'var(--accent-dim)')}
              onMouseLeave={e => canStart && !starting && ((e.currentTarget as HTMLElement).style.background = 'var(--accent)')}>
              {starting ? 'Starting…' : 'Start Draft'}
            </button>
            {isTournament && !hasMinPlayers && (
              <p className="text-xs text-center mt-2" style={{ color: 'var(--text-dim)' }}>
                Need {needed} more player{needed > 1 ? 's' : ''} to start ({minToStart} minimum)
              </p>
            )}
            {hasMinPlayers && !allReady && (
              <p className="text-xs text-center mt-2" style={{ color: 'var(--text-dim)' }}>
                Waiting for all players to be ready ({readyMembers.length}/{room.members.length})
              </p>
            )}
            {isTournament && canStart && !allJoined && (
              <p className="text-xs text-center mt-2" style={{ color: 'var(--text-dim)' }}>
                You can start now or wait for more players (up to {room.player_count})
              </p>
            )}
          </>
        ) : (
          <div className="w-full py-3 rounded-xl text-center text-sm font-medium"
            style={{ background: 'var(--surface)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>
            <span className="pulse-accent inline-block mr-2" style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)', verticalAlign: 'middle' }} />
            Waiting for host to start the draft…
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main DraftPage ─────────────────────────────────────────────────────────────

export function DraftPage() {
  const { roomId } = useParams<{ roomId: string }>()
  const navigate   = useNavigate()
  const { clientId, displayName } = useAuth()
  const { openHelp } = useHelp()

  // WebSocket refs
  const wsRef             = useRef<WebSocket | null>(null)
  const pingRef           = useRef<ReturnType<typeof setInterval> | null>(null)
  const reconnectRef      = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectCountRef = useRef(0)
  const mountedRef        = useRef(true)
  const MAX_RECONNECTS    = 6

  // Room state
  const [room, setRoom]         = useState<FullRoomState | null>(null)
  const [timer, setTimer]       = useState(PICK_TIMER_TOTAL)
  const [toast, setToast]       = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  // Connection status
  const [connStatus, setConnStatus] = useState<'connecting' | 'connected' | 'reconnecting' | 'dead'>('connecting')
  const [deadReason, setDeadReason] = useState<'not_found' | 'lost' | 'kicked' | null>(null)
  const [retryKey, setRetryKey]     = useState(0)

  // Draft state
  const [playerMap, setPlayerMap]     = useState<Map<number, PickedPlayer>>(new Map())
  const [mySquadOrder, setMySquadOrder] = useState<number[]>([])

  // UI state
  const [viewingId, setViewingId]       = useState<string>(clientId)
  const [pickPanelOpen, setPickPanelOpen] = useState(false)
  const autoOpenedForPickRef            = useRef(-1)
  const [pickNotif, setPickNotif]       = useState<PickNotif | null>(null)

  // Reorder phase state
  const [reorderTimer, setReorderTimer] = useState(60)
  const [readyMembers, setReadyMembers] = useState<string[]>([])
  const [myReady, setMyReady]           = useState(false)

  function addToPlayerMap(p: PickedPlayer) {
    setPlayerMap(prev => {
      if (prev.has(p.player_id)) return prev
      const next = new Map(prev)
      next.set(p.player_id, p)
      return next
    })
  }

  const handleMessage = useCallback((raw: string) => {
    let msg: { type: string; data?: unknown }
    try { msg = JSON.parse(raw) } catch { return }

    switch (msg.type) {
      case 'room_state': {
        const data = msg.data as FullRoomState & { player_details?: PickedPlayer[] }
        setRoom(data)
        const me = data.members.find(m => m.client_id === clientId)
        if (me) setMySquadOrder(me.squad)
        if (data.ready_members) setReadyMembers(data.ready_members)
        if (data.player_details?.length) {
          setPlayerMap(prev => {
            const next = new Map(prev)
            for (const p of data.player_details!) next.set(p.player_id, p)
            return next
          })
        }
        break
      }
      case 'member_connected': {
        const { client_id } = msg.data as { client_id: string }
        setRoom(prev => prev ? {
          ...prev,
          members: prev.members.map(m => m.client_id === client_id ? { ...m, connected: true } : m),
        } : prev)
        break
      }
      case 'member_disconnected': {
        const { client_id } = msg.data as { client_id: string }
        setRoom(prev => prev ? {
          ...prev,
          members: prev.members.map(m => m.client_id === client_id ? { ...m, connected: false } : m),
        } : prev)
        break
      }
      case 'draft_started': {
        const data = msg.data as FullRoomState
        setRoom(data)
        setReadyMembers(data.ready_members ?? [])
        setMyReady(false)
        const me = data.members.find(m => m.client_id === clientId)
        if (me) setMySquadOrder(me.squad)
        break
      }
      case 'pick_made': {
        interface PickMadeData {
          picker: string; player_id: number; player: PickedPlayer; auto_picked: boolean; room: FullRoomState
        }
        const data = msg.data as PickMadeData
        addToPlayerMap(data.player)
        setRoom(data.room)
        const me = data.room.members.find(m => m.client_id === clientId)
        if (me) setMySquadOrder(me.squad)
        // Show pick notification for everyone
        const picker = data.room.members.find(m => m.client_id === data.picker)
        if (picker) {
          setPickNotif({
            playerName: data.player.name,
            teamName: picker.display_name,
            displayName: picker.display_name,
            autoPicked: data.auto_picked,
          })
        }
        break
      }
      case 'squad_reordered': {
        const { client_id, squad } = msg.data as { client_id: string; squad: number[] }
        setRoom(prev => prev ? {
          ...prev, members: prev.members.map(m => m.client_id === client_id ? { ...m, squad } : m),
        } : prev)
        if (client_id === clientId) setMySquadOrder(squad)
        break
      }
      case 'timer_tick': {
        const { seconds_remaining } = msg.data as { seconds_remaining: number }
        setTimer(seconds_remaining)
        break
      }
      case 'reorder_phase': {
        const data = msg.data as FullRoomState
        setRoom(data)
        setReadyMembers(data.ready_members ?? [])
        setMyReady(false)
        setReorderTimer(60)
        setPickPanelOpen(false)
        break
      }
      case 'reorder_tick': {
        const { seconds_remaining } = msg.data as { seconds_remaining: number }
        setReorderTimer(seconds_remaining)
        break
      }
      case 'ready_update': {
        const { ready_members } = msg.data as { ready_members: string[]; total: number }
        setReadyMembers(ready_members)
        break
      }
      case 'sim_started': {
        setRoom(prev => prev ? { ...prev, status: 'simulating' } : prev)
        break
      }
      case 'sim_created': {
        // Hand off to the shared SimulatingPage as soon as the sim_id exists —
        // don't wait for the whole simulation (which can take 10-30s) to finish
        // just to show a bare spinner here in the meantime.
        const { sim_id } = msg.data as { sim_id: string }
        // teamName is read by SimulatingPage; userTeam/backPath are read by
        // MatchDetailPage once SimulatingPage hands off to it on completion
        // (only relevant for 1v1 — tournament results ignore these).
        navigate(`/simulating/${sim_id}`, { state: { teamName: displayName, userTeam: displayName, backPath: '/' } })
        break
      }
      case 'error': {
        const d = msg.data as { message: string }
        setToast(typeof d === 'string' ? d : d.message)
        setStarting(false)
        break
      }
    }
  }, [clientId, displayName, navigate])

  // Auto-open pick panel when it becomes my turn
  useEffect(() => {
    if (!room || room.status !== 'drafting') return
    const isMyTurn = room.current_picker === clientId
    if (isMyTurn && room.picks_made !== autoOpenedForPickRef.current) {
      autoOpenedForPickRef.current = room.picks_made
      setPickPanelOpen(true)
    }
  }, [room?.current_picker, room?.picks_made, room?.status, clientId])

  // Show the draft help once, only while still in the waiting room — never
  // once drafting has actually started (that's the whole point of excluding
  // this path from HelpModal's generic pathname-based auto-open: a browser's
  // first-ever visit here could otherwise land mid-draft, e.g. joining via a
  // link slightly after the host already clicked Start, popping the modal up
  // while that player's own pick timer is already running).
  useEffect(() => {
    if (room?.status !== 'waiting') return
    if (hasSeenHelp(DRAFT_HELP_KEY)) return
    markHelpSeen(DRAFT_HELP_KEY)
    openHelp(0, false)
  }, [room?.status, openHelp])

  // Default viewing to my team when first connected
  useEffect(() => {
    if (room && viewingId === clientId) return
    if (room && !room.members.find(m => m.client_id === viewingId)) {
      setViewingId(clientId)
    }
  }, [room, viewingId, clientId])

  // WebSocket connect with auto-reconnect
  useEffect(() => {
    if (!roomId) return
    mountedRef.current = true
    reconnectCountRef.current = 0
    setConnStatus('connecting')
    setDeadReason(null)

    function clearPing() { if (pingRef.current) { clearInterval(pingRef.current); pingRef.current = null } }
    function clearReconnect() { if (reconnectRef.current) { clearTimeout(reconnectRef.current); reconnectRef.current = null } }

    function connect() {
      if (!mountedRef.current) return
      clearPing()
      const ws = new WebSocket(`${WS_BASE}/${roomId}?client_id=${encodeURIComponent(clientId)}`)
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) return
        reconnectCountRef.current = 0
        setConnStatus('connected')
        pingRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
        }, PING_INTERVAL_MS)
      }
      ws.onmessage = e => handleMessage(e.data as string)
      ws.onerror   = () => { /* onclose handles it */ }
      ws.onclose   = e => {
        if (!mountedRef.current) return
        clearPing()
        if (e.code === 4004) { setConnStatus('dead'); setDeadReason('not_found'); return }
        if (e.code === 4001) { setConnStatus('dead'); setDeadReason('kicked'); return }
        if (e.code === 4003) { navigate(`/join/${roomId}`); return }
        if (e.code === 1000) return
        if (reconnectCountRef.current >= MAX_RECONNECTS) { setConnStatus('dead'); setDeadReason('lost'); return }
        const delay = Math.min(500 * 2 ** reconnectCountRef.current, 8000)
        reconnectCountRef.current++
        setConnStatus('reconnecting')
        reconnectRef.current = setTimeout(connect, delay)
      }
    }

    connect()
    return () => {
      mountedRef.current = false
      clearPing()
      clearReconnect()
      wsRef.current?.close()
    }
  // retryKey triggers manual retry
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, clientId, handleMessage, retryKey])

  function sendWs(payload: unknown) {
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify(payload))
  }

  function handleStartDraft() { setStarting(true); sendWs({ type: 'start_draft' }); setTimeout(() => setStarting(false), 5000) }
  function handlePick(id: number) { sendWs({ type: 'pick_player', player_id: id }) }
  function handleReorder(order: number[]) { setMySquadOrder(order); sendWs({ type: 'reorder_squad', order }) }
  function moveUp(idx: number) { if (idx === 0) return; const n = [...mySquadOrder]; [n[idx-1],n[idx]]=[n[idx],n[idx-1]]; handleReorder(n) }
  function moveDown(idx: number) { if (idx >= mySquadOrder.length-1) return; const n = [...mySquadOrder]; [n[idx],n[idx+1]]=[n[idx+1],n[idx]]; handleReorder(n) }
  function handleReady() { setMyReady(true); sendWs({ type: 'player_ready' }) }
  function handleKick(targetId: string) { sendWs({ type: 'kick_player', client_id: targetId }) }

  // Derived
  const isMyTurn   = !!room && room.current_picker === clientId && room.status === 'drafting'
  const draftedIds = new Set(room?.members.flatMap(m => m.squad) ?? [])
  const hasKeeper  = mySquadOrder.some(id => playerMap.get(id)?.is_keeper)
  const needsKeeper = isMyTurn && !hasKeeper && (11 - mySquadOrder.length) === 1

  // Map player_id → team name of who drafted them
  const pickedByName = useMemo(() => {
    const map = new Map<number, string>()
    if (room) {
      for (const m of room.members) {
        const label = m.display_name
        for (const pid of m.squad) map.set(pid, label)
      }
    }
    return map
  }, [room])

  const viewedMember  = room?.members.find(m => m.client_id === viewingId) ?? null
  const viewedSquad   = viewingId === clientId ? mySquadOrder : (viewedMember?.squad ?? [])
  const isViewingMyTeam = viewingId === clientId

  // ── Dead state ────────────────────────────────────────────────────────────────
  // 'kicked' shows this screen even with a (now stale) room already loaded —
  // every other dead reason means the client never had a room to show.
  if (connStatus === 'dead' && (!room || deadReason === 'kicked')) {
    const isNotFound = deadReason === 'not_found'
    const isKicked   = deadReason === 'kicked'
    const icon    = isNotFound ? '🚪' : isKicked ? '👋' : '⚠️'
    const heading = isNotFound ? 'Room not found' : isKicked ? 'Removed from room' : 'Connection failed'
    const detail  = isNotFound ? 'This room no longer exists or the server was restarted.'
                  : isKicked   ? 'The host removed you from this room.'
                  : 'Unable to connect after several attempts.'
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4 text-center px-6 max-w-xs">
          <div className="text-3xl">{icon}</div>
          <div className="text-base font-semibold" style={{ color: 'var(--text)' }}>{heading}</div>
          <div className="text-sm" style={{ color: 'var(--text-muted)' }}>{detail}</div>
          <div className="flex gap-3">
            <button onClick={() => navigate('/multiplayer')} className="btn-accent text-sm px-5 py-2 rounded-lg">Back to Lobby</button>
            {!isNotFound && !isKicked && (
              <button onClick={() => setRetryKey(k => k + 1)} className="btn-outline text-sm px-5 py-2 rounded-lg">Retry</button>
            )}
          </div>
        </div>
      </div>
    )
  }

  // ── Loading state ──────────────────────────────────────────────────────────────
  if (!room) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-3">
          <span className="spin inline-block w-8 h-8 rounded-full border-2" style={{ borderColor: 'var(--accent-tint)', borderTopColor: 'var(--accent)' }} />
          <span className="text-sm" style={{ color: 'var(--text-muted)' }}>
            {connStatus === 'reconnecting' ? 'Reconnecting…' : 'Connecting to draft room…'}
          </span>
        </div>
      </div>
    )
  }

  // ── Waiting state ──────────────────────────────────────────────────────────────
  if (room.status === 'waiting') {
    return (
      <>
        {toast && <Toast message={toast} onDone={() => setToast(null)} />}
        <WaitingRoom
          room={room} clientId={clientId} onStart={handleStartDraft} starting={starting}
          readyMembers={readyMembers} myReady={myReady} onReady={handleReady} onKick={handleKick}
        />
      </>
    )
  }

  // ── Simulating / Completed states ───────────────────────────────────────────────
  if (room.status === 'simulating' || room.status === 'completed') {
    return (
      <div className="fixed inset-0 flex flex-col items-center justify-center z-50" style={{ background: 'var(--bg)' }}>
        <div className="flex flex-col items-center gap-6 text-center px-6 max-w-sm">
          <div
            className="w-20 h-20 rounded-full flex items-center justify-center"
            style={{ background: 'var(--accent-tint)', border: '2px solid var(--accent)' }}
          >
            <span className="spin inline-block w-10 h-10 rounded-full border-4" style={{ borderColor: 'var(--accent-tint)', borderTopColor: 'var(--accent)' }} />
          </div>
          <div>
            <div className="text-xl font-bold mb-2" style={{ color: 'var(--text)' }}>Simulating…</div>
            <div className="text-sm" style={{ color: 'var(--text-muted)' }}>
              Running ball-by-ball. Takes 10–30 seconds.
            </div>
          </div>
        </div>
      </div>
    )
  }

  // ── Reordering state ────────────────────────────────────────────────────────────
  if (room.status === 'reordering') {
    return (
      <>
        {toast && <Toast message={toast} onDone={() => setToast(null)} />}

        <div className="flex flex-col" style={{ height: '100vh', background: 'var(--bg)' }}>
          {/* Header */}
          <div className="flex-shrink-0 px-4 py-3 flex items-center justify-between"
            style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
            <div>
              <div className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{room.tournament_name}</div>
              <div className="text-xs" style={{ color: 'var(--text-muted)' }}>Reorder your lineup</div>
            </div>
            <div className="flex items-center gap-2">
              <TimerRing seconds={reorderTimer} total={60} size={44} />
            </div>
          </div>

          {/* Team chips — ready state shown via CheckCircle2 in each chip */}
          <TeamChips room={room} clientId={clientId} viewingId={viewingId} onSelect={setViewingId} readyMembers={readyMembers} />

          {/* Squad view */}
          <SquadView
            squad={viewedSquad}
            playerMap={playerMap}
            isMyTeam={isViewingMyTeam && !myReady}
            onMoveUp={isViewingMyTeam && !myReady ? moveUp : undefined}
            onMoveDown={isViewingMyTeam && !myReady ? moveDown : undefined}
          />

          {/* Ready button */}
          {!myReady ? (
            <div className="flex-shrink-0 p-4" style={{ borderTop: '1px solid var(--border)' }}>
              <button onClick={handleReady}
                className="w-full py-3 rounded-xl font-semibold text-base transition-all flex items-center justify-center gap-2"
                style={{ background: 'var(--accent)', color: 'var(--bg)' }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'var(--accent-dim)'}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'var(--accent)'}>
                <CheckCircle2 size={18} /> I'm Ready
              </button>
              <div className="text-xs text-center mt-2" style={{ color: 'var(--text-dim)' }}>
                Simulation starts when all players are ready or the timer runs out
              </div>
            </div>
          ) : (
            <div className="flex-shrink-0 p-4" style={{ borderTop: '1px solid var(--border)' }}>
              <div className="w-full py-3 rounded-xl text-center font-semibold text-base"
                style={{ background: 'rgba(34,197,94,0.12)', color: 'var(--win)', border: '1px solid rgba(34,197,94,0.3)' }}>
                ✓ Ready — waiting for others ({readyMembers.length}/{room.members.length})
              </div>
            </div>
          )}
        </div>
      </>
    )
  }

  // ── Drafting state ──────────────────────────────────────────────────────────────
  const currentPickerMember = room.members.find(m => m.client_id === room.current_picker)

  return (
    <>
      {toast && <Toast message={toast} onDone={() => setToast(null)} />}
      {pickNotif && <PickNotification notif={pickNotif} onDone={() => setPickNotif(null)} />}

      {/* Reconnecting banner */}
      {connStatus === 'reconnecting' && (
        <div className="text-xs text-center px-4 py-2 font-medium" style={{ background: 'rgba(245,158,11,0.12)', color: 'var(--score)' }}>
          <span className="spin inline-block w-3 h-3 rounded-full border-2 mr-2 align-middle" style={{ borderColor: 'rgba(245,158,11,0.3)', borderTopColor: 'var(--score)' }} />
          Reconnecting…
        </div>
      )}

      <div className="flex flex-col" style={{ height: '100vh', background: 'var(--bg)' }}>

        {/* Sticky header */}
        <div className="flex-shrink-0 px-4 py-3 flex items-center justify-between"
          style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
          <div>
            <div className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{room.tournament_name}</div>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Pick {room.picks_made}/{room.total_picks} · {room.mode === '1v1' ? '1v1' : 'Tournament'} · {room.match_format ?? 'T20'}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {isMyTurn ? (
              <div className="flex items-center gap-2">
                <TimerRing seconds={timer} size={40} />
                <span className="text-xs px-2 py-1 rounded-full font-semibold"
                  style={{ background: 'var(--accent-tint)', color: 'var(--accent)' }}>
                  Your pick!
                </span>
              </div>
            ) : currentPickerMember ? (
              <div className="flex items-center gap-1.5">
                <TimerRing seconds={timer} size={36} />
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {currentPickerMember.display_name} picking
                </span>
              </div>
            ) : null}
          </div>
        </div>

        {/* Team chips */}
        <TeamChips room={room} clientId={clientId} viewingId={viewingId} onSelect={setViewingId} />

        {/* Keeper warning (my team only) — from the 6th pick onwards, not just once overdue */}
        {isViewingMyTeam && !hasKeeper && mySquadOrder.length >= 5 && (
          <div className="flex-shrink-0 mx-3 mt-2 px-3 py-2 rounded-lg text-xs flex items-center gap-2"
            style={{ background: 'rgba(245,158,11,0.08)', color: 'var(--score)', border: '1px solid rgba(245,158,11,0.2)' }}>
            <AlertTriangle size={12} />
            {11 - mySquadOrder.length === 1 && isMyTurn
              ? 'Last pick — must choose a keeper!'
              : "No keeper yet — don't forget one"}
          </div>
        )}

        {/* Squad view */}
        <SquadView
          squad={viewedSquad}
          playerMap={playerMap}
          isMyTeam={isViewingMyTeam}
          onMoveUp={isViewingMyTeam ? moveUp : undefined}
          onMoveDown={isViewingMyTeam ? moveDown : undefined}
        />

        {/* Bottom pick button */}
        <div className="flex-shrink-0 p-3" style={{ borderTop: '1px solid var(--border)' }}>
          {isMyTurn ? (
            <button onClick={() => setPickPanelOpen(true)}
              className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all"
              style={{ background: 'var(--accent)', color: 'var(--bg)', boxShadow: '0 4px 16px var(--accent-glow)' }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'var(--accent-dim)'}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'var(--accent)'}>
              <Zap size={16} />
              Pick a Player
            </button>
          ) : (
            <button onClick={() => setPickPanelOpen(true)}
              className="w-full py-2.5 rounded-xl font-medium text-sm flex items-center justify-center gap-2 transition-all"
              style={{ background: 'var(--surface)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>
              <Search size={14} />
              Browse Players
            </button>
          )}
        </div>
      </div>

      {/* Pick panel popup */}
      <PickPanel
        open={pickPanelOpen}
        onClose={() => setPickPanelOpen(false)}
        timer={timer}
        draftedIds={draftedIds}
        pickedByName={pickedByName}
        onPick={handlePick}
        needsKeeper={needsKeeper}
        isMyTurn={isMyTurn}
      />
    </>
  )
}
