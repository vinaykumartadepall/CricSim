import { createPortal } from 'react-dom'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Dice5, Users, Swords, Link, X, ChevronLeft } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'

// ── Name randomizer ───────────────────────────────────────────────────────────

const ADJS  = ['Thunder', 'Lightning', 'Blaze', 'Storm', 'Iron', 'Royal', 'Mighty', 'Shadow', 'Golden', 'Neon', 'Crimson', 'Steel']
const NOUNS = ['Cup', 'League', 'Series', 'Open', 'Championship', 'Invitational', 'Masters', 'Classic', 'Trophy', 'Shield']
const YEAR  = new Date().getFullYear()

function randomName(mode: '1v1' | 'tournament'): string {
  const adj  = ADJS[Math.floor(Math.random() * ADJS.length)]
  const noun = mode === '1v1' ? 'Clash' : NOUNS[Math.floor(Math.random() * NOUNS.length)]
  return `${adj} ${noun} ${YEAR}`
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

// ── Create Room Modal ─────────────────────────────────────────────────────────

function CreateRoomModal({ onClose }: { onClose: () => void }) {
  const { clientId, displayName } = useAuth()
  const navigate = useNavigate()

  const [mode, setMode]             = useState<'1v1' | 'tournament'>('1v1')
  const [name, setName]             = useState(() => randomName('1v1'))
  const [matchFormat, setMatchFormat] = useState<'T20' | 'ODI' | 'Test'>('T20')
  const [playerCount, setPlayerCount] = useState<number>(4)
  const [creating, setCreating]     = useState(false)
  const [error, setError]           = useState<string | null>(null)

  function switchMode(m: '1v1' | 'tournament') {
    setMode(m)
    setName(randomName(m))
  }

  async function handleCreate() {
    if (!name.trim()) { setError('Enter a name'); return }
    setCreating(true); setError(null)
    try {
      const room = await api.createRoom({
        client_id: clientId,
        display_name: displayName,
        mode,
        tournament_name: name.trim(),
        player_count: mode === '1v1' ? 2 : playerCount,
        match_format: matchFormat,
      })
      // Straight into the Waiting Room — the room code/link are shown there
      // too, so the old "Room Created" confirmation step was just an extra
      // click with nothing on it the Waiting Room doesn't already have.
      navigate(`/multiplayer/draft/${room.room_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create room')
      setCreating(false)
    }
  }

  const pill = (active: boolean) => ({
    background: active ? 'var(--accent-tint)' : 'var(--surface-2)',
    color: active ? 'var(--accent)' : 'var(--text-muted)',
    border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
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
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = 'var(--accent)'}
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

      {error && (
        <div className="text-xs px-3 py-2 rounded-lg" style={{ background: 'rgba(239,68,68,0.08)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.2)' }}>
          {error}
        </div>
      )}

      <button
        onClick={handleCreate}
        disabled={creating}
        className="w-full py-3 rounded-xl font-semibold text-sm transition-all"
        style={{ background: creating ? 'var(--accent-tint)' : 'var(--accent)', color: creating ? 'var(--text-dim)' : 'var(--bg)', cursor: creating ? 'not-allowed' : 'pointer' }}
        onMouseEnter={e => !creating && ((e.currentTarget as HTMLElement).style.background = 'var(--accent-dim)')}
        onMouseLeave={e => !creating && ((e.currentTarget as HTMLElement).style.background = 'var(--accent)')}
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

  // When initialCode is present we skip the room-code step entirely
  const hasCode = !!initialCode

  const [roomCode, setRoomCode] = useState(initialCode?.toUpperCase() ?? '')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)

  async function handleJoin(code: string) {
    setLoading(true); setError(null)
    try {
      await api.joinRoom(code, { client_id: clientId, display_name: displayName })
      navigate(`/multiplayer/draft/${code}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to join room')
      setLoading(false)
    }
  }

  async function handleFindRoom() {
    if (!roomCode.trim()) { setError('Enter a room code'); return }
    await handleJoin(roomCode.trim())
  }

  const errBox = error && (
    <div className="text-xs px-3 py-2 rounded-lg" style={{ background: 'rgba(239,68,68,0.08)', color: 'var(--loss)', border: '1px solid rgba(239,68,68,0.2)' }}>
      {error}
    </div>
  )

  const joinBtn = (onClick: () => void) => (
    <button
      onClick={onClick}
      disabled={loading}
      className="w-full py-3 rounded-xl font-semibold text-sm transition-all"
      style={{
        background: loading ? 'var(--accent-tint)' : 'var(--accent)',
        color: loading ? 'var(--text-dim)' : 'var(--bg)',
        cursor: loading ? 'not-allowed' : 'pointer',
      }}
      onMouseEnter={e => !loading && ((e.currentTarget as HTMLElement).style.background = 'var(--accent-dim)')}
      onMouseLeave={e => !loading && ((e.currentTarget as HTMLElement).style.background = 'var(--accent)')}
    >
      {loading
        ? <span className="flex items-center justify-center gap-2">
            <span className="spin inline-block w-4 h-4 rounded-full border-2" style={{ borderColor: 'rgba(255,255,255,0.3)', borderTopColor: '#fff' }} />
            Joining…
          </span>
        : 'Join Room'}
    </button>
  )

  // Path A: opened via share link — join immediately
  if (hasCode) {
    return (
      <Modal title="Join Room" onClose={onClose}>
        <div className="flex flex-col gap-4">
          <div className="text-center">
            <div className="font-mono text-xl font-bold tracking-[0.2em]" style={{ color: 'var(--accent)' }}>{roomCode}</div>
            <div className="text-xs mt-1" style={{ color: 'var(--text-dim)' }}>You'll join as <strong>{displayName}</strong></div>
          </div>
          {errBox}
          {joinBtn(() => handleJoin(roomCode))}
        </div>
      </Modal>
    )
  }

  // Path B, step 1: enter room code manually
  return (
    <Modal title="Join Room" onClose={onClose}>
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Room Code</label>
        <input
          className="input font-mono text-lg tracking-widest uppercase text-center"
          placeholder="ABC123"
          maxLength={8}
          value={roomCode}
          onChange={e => { setRoomCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8)); setError(null) }}
          style={{ letterSpacing: '0.2em' }}
          onKeyDown={e => { if (e.key === 'Enter') handleFindRoom() }}
          autoFocus
        />
      </div>
      {errBox}
      <button
        onClick={handleFindRoom}
        disabled={loading || !roomCode.trim()}
        className="w-full py-3 rounded-xl font-semibold text-sm transition-all"
        style={{
          background: loading || !roomCode.trim() ? 'var(--accent-tint)' : 'var(--accent)',
          color: loading || !roomCode.trim() ? 'var(--text-dim)' : 'var(--bg)',
          cursor: loading || !roomCode.trim() ? 'not-allowed' : 'pointer',
        }}
      >
        {loading
          ? <span className="flex items-center justify-center gap-2">
              <span className="spin inline-block w-4 h-4 rounded-full border-2" style={{ borderColor: 'rgba(255,255,255,0.3)', borderTopColor: '#fff' }} />
              Finding room…
            </span>
          : 'Join Room'}
      </button>
      <div className="text-xs text-center" style={{ color: 'var(--text-dim)' }}>
        Ask the room creator for their 6-character code.
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
        <div className="text-xs font-semibold tracking-widest uppercase mb-3" style={{ color: 'var(--accent)' }}>
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
            style={{ background: 'var(--accent)', color: 'var(--bg)', boxShadow: '0 4px 20px var(--accent-glow)' }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'var(--accent-dim)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'var(--accent)'}
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
              el.style.borderColor = 'var(--accent)'
              el.style.color = 'var(--accent)'
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
      <div style={{ maxWidth: 480, margin: '0 auto', padding: '0 24px 64px' }}>
        <div style={{ position: 'relative', display: 'flex', alignItems: 'flex-start' }}>
          {/* connector line */}
          <div style={{
            position: 'absolute', top: 13, left: '16%', right: '16%',
            height: 1, background: 'var(--border)', zIndex: 0,
          }} />
          {[
            { step: '1', label: 'Create or join', sub: 'Share a 6-char code' },
            { step: '2', label: 'Snake draft', sub: '60s per pick, in turns' },
            { step: '3', label: 'Simulate', sub: 'See whose XI wins' },
          ].map(({ step, label, sub }) => (
            <div key={step} style={{
              flex: 1, display: 'flex', flexDirection: 'column',
              alignItems: 'center', textAlign: 'center', gap: 8, position: 'relative', zIndex: 1,
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                background: 'var(--surface)', border: '1px solid var(--border)',
                color: 'var(--accent)', fontWeight: 700, fontSize: 13,
                display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
              }}>
                {step}
              </div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', lineHeight: 1.3 }}>{label}</div>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.45 }}>{sub}</div>
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
