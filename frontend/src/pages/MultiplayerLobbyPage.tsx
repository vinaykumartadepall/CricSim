import { createPortal } from 'react-dom'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Copy, Check, Dice5, Users, Swords, Link, X, ChevronLeft } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import type { RoomResponse } from '@/types'

// ── Name randomizer ───────────────────────────────────────────────────────────

const ADJS  = ['Thunder', 'Lightning', 'Blaze', 'Storm', 'Iron', 'Royal', 'Mighty', 'Shadow', 'Golden', 'Neon', 'Crimson', 'Steel']
const NOUNS = ['Cup', 'League', 'Series', 'Open', 'Championship', 'Invitational', 'Masters', 'Classic', 'Trophy', 'Shield']
const YEAR  = new Date().getFullYear()

function randomName(mode: '1v1' | 'tournament'): string {
  const adj  = ADJS[Math.floor(Math.random() * ADJS.length)]
  const noun = mode === '1v1' ? 'Clash' : NOUNS[Math.floor(Math.random() * NOUNS.length)]
  return `${adj} ${noun} ${YEAR}`
}

// ── CopyButton ────────────────────────────────────────────────────────────────

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard.writeText(text).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }
  return (
    <button
      onClick={copy}
      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all flex-shrink-0"
      style={{
        background: copied ? 'rgba(34,197,94,0.12)' : 'var(--surface-2)',
        color: copied ? 'var(--win)' : 'var(--text-muted)',
        border: `1px solid ${copied ? 'rgba(34,197,94,0.3)' : 'var(--border)'}`,
      }}
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {label ? (copied ? 'Copied!' : label) : (copied ? 'Copied!' : 'Copy')}
    </button>
  )
}

// ── Modal wrapper ─────────────────────────────────────────────────────────────

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose])

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-md rounded-2xl flex flex-col overflow-hidden fade-in"
        style={{ background: 'var(--surface)', border: '1px solid var(--border)', boxShadow: '0 24px 48px rgba(0,0,0,0.5)' }}
      >
        {/* Modal header */}
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid var(--border)' }}>
          <span className="font-semibold text-base" style={{ color: 'var(--text)' }}>{title}</span>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg transition-all"
            style={{ color: 'var(--text-muted)', background: 'transparent' }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'var(--surface-2)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'transparent'}
          >
            <X size={16} />
          </button>
        </div>
        <div className="px-6 py-5 flex flex-col gap-4 overflow-y-auto" style={{ maxHeight: '80vh' }}>
          {children}
        </div>
      </div>
    </div>,
    document.body,
  )
}

// ── Room created panel ────────────────────────────────────────────────────────

function RoomCreatedPanel({ room, clientId, onClose }: { room: RoomResponse; clientId: string; onClose: () => void }) {
  const navigate = useNavigate()
  const shareUrl = `${window.location.origin}/join/${room.room_id}`
  const [teamName, setTeamName] = useState('')
  const [saving, setSaving]     = useState(false)
  const [error, setError]       = useState<string | null>(null)

  async function handleEnter() {
    if (!teamName.trim()) { setError('Enter your team name'); return }
    setSaving(true); setError(null)
    try {
      await api.updateRoomMember(room.room_id, { client_id: clientId, team_name: teamName.trim() })
      navigate(`/multiplayer/draft/${room.room_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set team name')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="Room Created" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <div className="text-center">
          <div className="text-xs font-medium uppercase tracking-wider mb-1" style={{ color: '#a855f7' }}>Room Created!</div>
          <div className="text-sm" style={{ color: 'var(--text-muted)' }}>{room.tournament_name}</div>
        </div>

        <div>
          <div className="text-xs mb-1.5 font-medium" style={{ color: 'var(--text-dim)' }}>Room Code</div>
          <div className="flex items-center gap-2">
            <div
              className="font-mono text-2xl font-bold tracking-[0.2em] px-4 py-2 rounded-lg flex-1 text-center"
              style={{ background: 'var(--surface-2)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)' }}
            >
              {room.room_id}
            </div>
            <CopyButton text={room.room_id} />
          </div>
        </div>

        <div>
          <div className="text-xs mb-1.5 font-medium" style={{ color: 'var(--text-dim)' }}>Share Link</div>
          <div className="flex items-center gap-2">
            <div
              className="flex-1 min-w-0 text-xs font-mono px-3 py-2 rounded-lg truncate"
              style={{ background: 'var(--surface-2)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}
            >
              {shareUrl}
            </div>
            <CopyButton text={shareUrl} label="Copy link" />
          </div>
        </div>

        <div
          className="text-xs px-3 py-2 rounded-lg text-center"
          style={{ background: 'rgba(168,85,247,0.06)', color: 'var(--text-muted)', border: '1px solid rgba(168,85,247,0.15)' }}
        >
          Share the code with your opponent, then enter the draft room.
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Your Team Name</label>
          <input
            className="input"
            placeholder="e.g. Royal Strikers"
            value={teamName}
            onChange={e => { setTeamName(e.target.value); setError(null) }}
            onKeyDown={e => { if (e.key === 'Enter') handleEnter() }}
            autoFocus
          />
        </div>

        {error && (
          <div className="text-xs px-3 py-2 rounded-lg" style={{ background: 'rgba(239,68,68,0.08)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.2)' }}>
            {error}
          </div>
        )}

        <button
          onClick={handleEnter}
          disabled={saving}
          className="w-full py-2.5 rounded-xl font-semibold text-sm transition-all"
          style={{ background: saving ? 'rgba(168,85,247,0.4)' : '#a855f7', color: '#fff', cursor: saving ? 'not-allowed' : 'pointer' }}
          onMouseEnter={e => !saving && ((e.currentTarget as HTMLElement).style.background = '#9333ea')}
          onMouseLeave={e => !saving && ((e.currentTarget as HTMLElement).style.background = '#a855f7')}
        >
          {saving ? (
            <span className="flex items-center justify-center gap-2">
              <span className="spin inline-block w-4 h-4 rounded-full border-2" style={{ borderColor: 'rgba(255,255,255,0.3)', borderTopColor: '#fff' }} />
              Saving…
            </span>
          ) : 'Enter Draft Room →'}
        </button>
      </div>
    </Modal>
  )
}

// ── Create Room Modal ─────────────────────────────────────────────────────────

function CreateRoomModal({ onClose }: { onClose: () => void }) {
  const { clientId, displayName } = useAuth()

  const [mode, setMode]             = useState<'1v1' | 'tournament'>('1v1')
  const [name, setName]             = useState(() => randomName('1v1'))
  const [matchFormat, setMatchFormat] = useState<'T20' | 'ODI' | 'Test'>('T20')
  const [playerCount, setPlayerCount] = useState<number>(4)
  const [myName, setMyName]         = useState(displayName)
  const [creating, setCreating]     = useState(false)
  const [error, setError]           = useState<string | null>(null)
  const [created, setCreated]       = useState<RoomResponse | null>(null)

  const nameEdited = useRef(false)
  useEffect(() => {
    if (!nameEdited.current) setMyName(displayName)
  }, [displayName])

  function switchMode(m: '1v1' | 'tournament') {
    setMode(m)
    setName(randomName(m))
  }

  async function handleCreate() {
    if (!name.trim()) { setError('Enter a name'); return }
    if (!myName.trim()) { setError('Enter your display name'); return }
    setCreating(true); setError(null)
    try {
      const room = await api.createRoom({
        client_id: clientId,
        display_name: myName.trim(),
        mode,
        tournament_name: name.trim(),
        player_count: mode === '1v1' ? 2 : playerCount,
        match_format: matchFormat,
      })
      setCreated(room)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create room')
    } finally {
      setCreating(false)
    }
  }

  if (created) {
    return <RoomCreatedPanel room={created} clientId={clientId} onClose={onClose} />
  }

  const PURPLE = '#a855f7'
  const pill = (active: boolean) => ({
    background: active ? 'rgba(168,85,247,0.15)' : 'var(--surface-2)',
    color: active ? PURPLE : 'var(--text-muted)',
    border: `1px solid ${active ? 'rgba(168,85,247,0.4)' : 'var(--border)'}`,
  })

  return (
    <Modal title="Create Room" onClose={onClose}>
      {/* Mode */}
      <div className="flex flex-col gap-2">
        <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Mode</label>
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => switchMode('1v1')}
            className="flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-semibold transition-all"
            style={pill(mode === '1v1')}
          >
            <Swords size={15} />
            1v1 Match
          </button>
          <button
            onClick={() => switchMode('tournament')}
            className="flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-semibold transition-all"
            style={pill(mode === 'tournament')}
          >
            <Users size={15} />
            Tournament
          </button>
        </div>
      </div>

      {/* Name */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
          {mode === '1v1' ? 'Match Name' : 'Tournament Name'}
        </label>
        <div className="flex gap-2">
          <input
            className="input flex-1 min-w-0"
            placeholder={mode === '1v1' ? 'Thunder Clash 2026' : 'Thunder Cup 2026'}
            value={name}
            onChange={e => setName(e.target.value)}
          />
          <button
            onClick={() => setName(randomName(mode))}
            title="Randomize"
            className="px-2.5 rounded-lg transition-all flex-shrink-0"
            style={{ background: 'var(--surface-2)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = PURPLE}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = 'var(--text-muted)'}
          >
            <Dice5 size={16} />
          </button>
        </div>
      </div>

      {/* Format */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Format</label>
        <div className="flex gap-2">
          {(['T20', 'ODI', 'Test'] as const).map(fmt => (
            <button
              key={fmt}
              onClick={() => setMatchFormat(fmt)}
              className="flex-1 py-2 rounded-lg text-sm font-semibold transition-all"
              style={pill(matchFormat === fmt)}
            >
              {fmt}
            </button>
          ))}
        </div>
      </div>

      {/* Player count (tournament only) */}
      {mode === 'tournament' && (
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Max Players</label>
          <div className="flex gap-2">
            {[4, 6, 8, 10].map(n => (
              <button
                key={n}
                onClick={() => setPlayerCount(n)}
                className="flex-1 py-2 rounded-lg text-sm font-semibold transition-all"
                style={pill(playerCount === n)}
              >
                {n}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Display name */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Your Display Name</label>
        <input
          className="input"
          placeholder="CricketFan99"
          value={myName}
          onChange={e => { nameEdited.current = true; setMyName(e.target.value) }}
        />
      </div>

      {error && (
        <div className="text-xs px-3 py-2 rounded-lg" style={{ background: 'rgba(239,68,68,0.08)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.2)' }}>
          {error}
        </div>
      )}

      <button
        onClick={handleCreate}
        disabled={creating}
        className="w-full py-3 rounded-xl font-semibold text-sm transition-all"
        style={{ background: creating ? 'rgba(168,85,247,0.4)' : PURPLE, color: '#fff', cursor: creating ? 'not-allowed' : 'pointer' }}
        onMouseEnter={e => !creating && ((e.currentTarget as HTMLElement).style.background = '#9333ea')}
        onMouseLeave={e => !creating && ((e.currentTarget as HTMLElement).style.background = PURPLE)}
      >
        {creating ? (
          <span className="flex items-center justify-center gap-2">
            <span className="spin inline-block w-4 h-4 rounded-full border-2" style={{ borderColor: 'rgba(255,255,255,0.3)', borderTopColor: '#fff' }} />
            Creating…
          </span>
        ) : 'Create Room'}
      </button>
    </Modal>
  )
}

// ── Join Room Modal ───────────────────────────────────────────────────────────

function JoinRoomModal({ initialCode, onClose }: { initialCode?: string; onClose: () => void }) {
  const navigate = useNavigate()
  const { clientId, displayName } = useAuth()

  const [roomCode, setRoomCode]   = useState(initialCode?.toUpperCase() ?? '')
  const [myName, setMyName]       = useState(displayName)
  const [joining, setJoining]     = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [joinedCode, setJoinedCode] = useState<string | null>(null)  // set after successful join
  const [teamName, setTeamName]   = useState('')
  const [saving, setSaving]       = useState(false)

  const nameEdited = useRef(false)
  useEffect(() => {
    if (!nameEdited.current) setMyName(displayName)
  }, [displayName])

  async function handleJoin() {
    if (!roomCode.trim()) { setError('Enter a room code'); return }
    if (!myName.trim()) { setError('Enter your display name'); return }
    setJoining(true); setError(null)
    try {
      await api.joinRoom(roomCode.trim(), { client_id: clientId, display_name: myName.trim() })
      setJoinedCode(roomCode.trim())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to join room')
    } finally {
      setJoining(false)
    }
  }

  async function handleEnter() {
    if (!teamName.trim()) { setError('Enter your team name'); return }
    if (!joinedCode) return
    setSaving(true); setError(null)
    try {
      await api.updateRoomMember(joinedCode, { client_id: clientId, team_name: teamName.trim() })
      navigate(`/multiplayer/draft/${joinedCode}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set team name')
    } finally {
      setSaving(false)
    }
  }

  // Step 2: team name after joining
  if (joinedCode) {
    return (
      <Modal title="You're In!" onClose={onClose}>
        <div className="flex flex-col gap-4">
          <div
            className="text-xs px-3 py-2 rounded-lg text-center"
            style={{ background: 'rgba(59,130,246,0.06)', color: 'var(--text-muted)', border: '1px solid rgba(59,130,246,0.2)' }}
          >
            Joined room <span className="font-mono font-bold" style={{ color: 'var(--accent)' }}>{joinedCode}</span>. Enter a team name to continue.
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Your Team Name</label>
            <input
              className="input"
              placeholder="e.g. Royal Strikers"
              value={teamName}
              onChange={e => { setTeamName(e.target.value); setError(null) }}
              onKeyDown={e => { if (e.key === 'Enter') handleEnter() }}
              autoFocus
            />
          </div>

          {error && (
            <div className="text-xs px-3 py-2 rounded-lg" style={{ background: 'rgba(239,68,68,0.08)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.2)' }}>
              {error}
            </div>
          )}

          <button
            onClick={handleEnter}
            disabled={saving}
            className="w-full py-3 rounded-xl font-semibold text-sm transition-all"
            style={{
              background: saving ? 'rgba(59,130,246,0.25)' : 'var(--accent)',
              color: saving ? 'var(--text-dim)' : 'var(--bg)',
              cursor: saving ? 'not-allowed' : 'pointer',
            }}
          >
            {saving ? (
              <span className="flex items-center justify-center gap-2">
                <span className="spin inline-block w-4 h-4 rounded-full border-2" style={{ borderColor: 'rgba(59,130,246,0.3)', borderTopColor: 'var(--accent)' }} />
                Saving…
              </span>
            ) : 'Enter Draft Room →'}
          </button>
        </div>
      </Modal>
    )
  }

  // Step 1: room code + display name
  return (
    <Modal title="Join Room" onClose={onClose}>
      {/* Room code */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Room Code</label>
        <input
          className="input font-mono text-lg tracking-widest uppercase text-center"
          placeholder="ABC123"
          maxLength={8}
          value={roomCode}
          onChange={e => setRoomCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8))}
          style={{ letterSpacing: '0.2em' }}
          onKeyDown={e => { if (e.key === 'Enter') handleJoin() }}
        />
      </div>

      {/* Display name */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Your Display Name</label>
        <input
          className="input"
          placeholder="CricketFan99"
          value={myName}
          onChange={e => { nameEdited.current = true; setMyName(e.target.value) }}
          onKeyDown={e => { if (e.key === 'Enter') handleJoin() }}
        />
      </div>

      {error && (
        <div className="text-xs px-3 py-2 rounded-lg" style={{ background: 'rgba(239,68,68,0.08)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.2)' }}>
          {error}
        </div>
      )}

      <button
        onClick={handleJoin}
        disabled={joining || !roomCode.trim()}
        className="w-full py-3 rounded-xl font-semibold text-sm transition-all"
        style={{
          background: joining || !roomCode.trim() ? 'rgba(59,130,246,0.25)' : 'var(--accent)',
          color: joining || !roomCode.trim() ? 'var(--text-dim)' : 'var(--bg)',
          cursor: joining || !roomCode.trim() ? 'not-allowed' : 'pointer',
        }}
      >
        {joining ? (
          <span className="flex items-center justify-center gap-2">
            <span className="spin inline-block w-4 h-4 rounded-full border-2" style={{ borderColor: 'rgba(59,130,246,0.3)', borderTopColor: 'var(--accent)' }} />
            Joining…
          </span>
        ) : 'Join Room'}
      </button>

      <div className="text-xs text-center" style={{ color: 'var(--text-dim)' }}>
        Ask the room creator for the 6-character code or join via share link.
      </div>
    </Modal>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function MultiplayerLobbyPage() {
  const params = useParams<{ roomId?: string }>()
  const { authReady } = useAuth()
  const navigate = useNavigate()

  const [modal, setModal] = useState<'create' | 'join' | null>(null)

  // Auto-open Join modal only after auth has settled (so displayName is the real profile name)
  useEffect(() => {
    if (params.roomId && authReady) setModal('join')
  }, [params.roomId, authReady])

  return (
    <div className="min-h-screen" style={{ background: 'var(--bg)' }}>
      {/* Back button */}
      <div className="px-6 pt-5">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-1 text-sm"
          style={{ color: 'var(--text-muted)' }}
        >
          <ChevronLeft size={14} /> Home
        </button>
      </div>

      {/* Page header */}
      <div className="flex flex-col items-center text-center px-6 pt-10 pb-12">
        <div className="text-xs font-semibold tracking-widest uppercase mb-3" style={{ color: '#a855f7' }}>
          Real-time Draft
        </div>
        <h1
          className="text-3xl md:text-4xl font-bold mb-4"
          style={{ color: 'var(--text)', letterSpacing: '-0.5px', lineHeight: 1.15 }}
        >
          Multiplayer Draft
        </h1>
        <p className="text-base max-w-sm mb-10" style={{ color: 'var(--text-muted)' }}>
          Create a room, invite friends, and build the best XI in a live snake draft.
        </p>

        {/* Two CTA buttons side by side */}
        <div className="flex gap-4">
          <button
            onClick={() => setModal('create')}
            className="flex items-center gap-2.5 px-7 py-3.5 rounded-xl font-semibold text-sm transition-all"
            style={{ background: '#a855f7', color: '#fff', boxShadow: '0 4px 20px rgba(168,85,247,0.35)' }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = '#9333ea'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = '#a855f7'}
          >
            <Users size={16} />
            Create Room
          </button>
          <button
            onClick={() => setModal('join')}
            className="flex items-center gap-2.5 px-7 py-3.5 rounded-xl font-semibold text-sm transition-all"
            style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}
            onMouseEnter={e => {
              const el = e.currentTarget as HTMLElement
              el.style.borderColor = 'rgba(168,85,247,0.4)'
              el.style.color = '#a855f7'
            }}
            onMouseLeave={e => {
              const el = e.currentTarget as HTMLElement
              el.style.borderColor = 'var(--border)'
              el.style.color = 'var(--text)'
            }}
          >
            <Link size={16} />
            Join Room
          </button>
        </div>
      </div>

      {/* How-it-works strip */}
      <div className="max-w-2xl mx-auto px-6 pb-16">
        <div className="grid grid-cols-3 gap-4 text-center">
          {[
            { step: '1', label: 'Create or join', sub: 'Share a 6-char code with friends' },
            { step: '2', label: 'Snake draft', sub: 'Pick players in turns — 60s per pick' },
            { step: '3', label: 'Simulate', sub: 'See whose XI comes out on top' },
          ].map(({ step, label, sub }) => (
            <div
              key={step}
              className="rounded-xl p-4 flex flex-col items-center gap-2"
              style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
            >
              <div
                className="w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
                style={{ background: 'rgba(168,85,247,0.12)', color: '#a855f7' }}
              >
                {step}
              </div>
              <div className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{label}</div>
              <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{sub}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Modals */}
      {modal === 'create' && <CreateRoomModal onClose={() => setModal(null)} />}
      {modal === 'join'   && <JoinRoomModal initialCode={params.roomId} onClose={() => setModal(null)} />}
    </div>
  )
}
