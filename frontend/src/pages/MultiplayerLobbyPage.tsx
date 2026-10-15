import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Dice5, Users, Swords, Link, ChevronLeft, Crown, Globe, Lock, ChevronRight, Settings, X, RotateCw } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { SimulationTypeToggle } from '@/components/ui/SimulationTypeToggle'
import { FormatBadge } from '@/components/ui/FormatBadge'
import { FilterDropdown } from '@/components/ui/FilterDropdown'
import { SingleSelectDropdown } from '@/components/ui/SingleSelectDropdown'
import { VenueSearchMultiSelect } from '@/components/ui/VenueSearchMultiSelect'
import { Spinner } from '@/components/ui/Spinner'
import { Modal } from '@/components/ui/Modal'
import { usePublicRooms } from '@/hooks/usePublicRooms'
import { SCHEDULE_OPTIONS, PLAYOFF_OPTIONS } from '@/lib/advancedRoomSettings'
import type { MatchFormat, PublicRoomSummary, VenueConfig, VenueCountry } from '@/types'

// ── Name randomizer ───────────────────────────────────────────────────────────

const ADJS  = ['Thunder', 'Lightning', 'Blaze', 'Storm', 'Iron', 'Royal', 'Mighty', 'Shadow', 'Golden', 'Neon', 'Crimson', 'Steel']
const NOUNS = ['Cup', 'League', 'Series', 'Open', 'Championship', 'Invitational', 'Masters', 'Classic', 'Trophy', 'Shield']
const YEAR  = new Date().getFullYear()

function randomName(mode: '1v1' | 'tournament'): string {
  const adj  = ADJS[Math.floor(Math.random() * ADJS.length)]
  const noun = mode === '1v1' ? 'Clash' : NOUNS[Math.floor(Math.random() * NOUNS.length)]
  return `${adj} ${noun} ${YEAR}`
}

// ── Create Room Modal ─────────────────────────────────────────────────────────

function CreateRoomModal({ onClose }: { onClose: () => void }) {
  const { clientId, displayName } = useAuth()
  const navigate = useNavigate()

  const [mode, setMode]             = useState<'1v1' | 'tournament'>('1v1')
  const [name, setName]             = useState(() => randomName('1v1'))
  const [matchFormat, setMatchFormat] = useState<MatchFormat>('T20')
  const [playerCount, setPlayerCount] = useState<number>(4)
  const [isPublic, setIsPublic]     = useState(false)
  const [creating, setCreating]     = useState(false)
  const [error, setError]           = useState<string | null>(null)

  // Advanced Settings - all optional, all default to today's existing behavior.
  const [advancedOpen, setAdvancedOpen]   = useState(false)
  const [scheduleType, setScheduleType]   = useState<string | null>(null)
  const [playoffFormat, setPlayoffFormat] = useState<string | null>(null)
  const [venueMode, setVenueMode]         = useState<'default' | 'specific' | 'country'>('default')
  const [specificVenues, setSpecificVenues] = useState<string[]>([])
  const [countries, setCountries]         = useState<VenueCountry[]>([])
  const [countryIds, setCountryIds]       = useState<string[]>([])

  const playoffsEligible = mode === 'tournament' && playerCount >= 4

  useEffect(() => {
    if (venueMode !== 'country' || countries.length > 0) return
    api.getMultiplayerCountries().then(setCountries).catch(() => setCountries([]))
  }, [venueMode, countries.length])

  function buildVenueConfig(): VenueConfig | undefined {
    if (venueMode === 'specific' && specificVenues.length > 0) {
      return { mode: 'specific', venues: specificVenues }
    }
    if (venueMode === 'country' && countryIds.length > 0) {
      const selected = countries.filter(c => countryIds.includes(String(c.country_id)))
      return {
        mode: 'country',
        country_ids: selected.map(c => c.country_id),
        country_names: selected.map(c => c.name),
      }
    }
    return undefined
  }

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
        is_public: isPublic,
        schedule_type: mode === 'tournament' && scheduleType ? (scheduleType as 'round_robin' | 'double_round_robin') : undefined,
        playoff_format: playoffsEligible && playoffFormat ? (playoffFormat as 'semis_final' | 'ipl') : undefined,
        venue_config: buildVenueConfig(),
      })
      // Straight into the Waiting Room - the room code/link are shown there
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

      {/* Visibility */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
          Visibility
        </label>
        <div className="grid grid-cols-2 gap-1.5">
          <button
            type="button"
            onClick={() => setIsPublic(true)}
            className="flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-semibold transition-all"
            style={pill(isPublic)}
          >
            <Globe size={13} />
            Public
          </button>
          <button
            type="button"
            onClick={() => setIsPublic(false)}
            className="flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-semibold transition-all"
            style={pill(!isPublic)}
          >
            <Lock size={13} />
            Private
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

      <SimulationTypeToggle />

      {/* Advanced Settings - a plain, low-emphasis disclosure link, not a
          bordered/filled button like the rest of the form's controls. */}
      <div className="flex flex-col gap-3">
        <button
          type="button"
          onClick={() => setAdvancedOpen(o => !o)}
          className="flex items-center gap-1.5 text-xs w-fit font-medium transition-colors"
          style={{ color: 'var(--accent)' }}
          onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = 'var(--accent-dim)'}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = 'var(--accent)'}
        >
          <ChevronRight size={12} style={{ transform: advancedOpen ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s', flexShrink: 0 }} />
          <Settings size={12} style={{ flexShrink: 0 }} />
          Advanced settings
        </button>

        {advancedOpen && (
          <div className="flex flex-col gap-4">
            {mode === 'tournament' && (
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Schedule</label>
                <SingleSelectDropdown
                  placeholder="Double Round Robin (default)"
                  defaultLabel="Default"
                  value={scheduleType}
                  options={SCHEDULE_OPTIONS}
                  onChange={setScheduleType}
                />
              </div>
            )}

            {playoffsEligible && (
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Playoff Format</label>
                <SingleSelectDropdown
                  placeholder="IPL-style (default)"
                  defaultLabel="Default"
                  value={playoffFormat}
                  options={PLAYOFF_OPTIONS}
                  onChange={setPlayoffFormat}
                />
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Venues</label>
              <div className="grid grid-cols-3 gap-2">
                <button
                  type="button"
                  onClick={() => setVenueMode('default')}
                  className="flex items-center justify-center gap-1 py-2 rounded-lg text-xs font-semibold transition-all"
                  style={pill(venueMode === 'default')}
                >
                  🎲 Random
                </button>
                <button
                  type="button"
                  onClick={() => setVenueMode('specific')}
                  className="flex items-center justify-center gap-1 py-2 rounded-lg text-xs font-semibold transition-all"
                  style={pill(venueMode === 'specific')}
                >
                  📍 Specific
                </button>
                <button
                  type="button"
                  onClick={() => setVenueMode('country')}
                  className="flex items-center justify-center gap-1 py-2 rounded-lg text-xs font-semibold transition-all"
                  style={pill(venueMode === 'country')}
                >
                  🌍 Country
                </button>
              </div>

              {venueMode === 'specific' && (
                <div className="mt-1">
                  <VenueSearchMultiSelect values={specificVenues} onChange={setSpecificVenues} />
                </div>
              )}

              {venueMode === 'country' && (
                <div className="flex flex-col gap-2 mt-1">
                  {countryIds.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {countries.filter(c => countryIds.includes(String(c.country_id))).map(c => (
                        <span
                          key={c.country_id}
                          className="text-xs pl-2.5 pr-1.5 py-1 rounded-full flex items-center gap-1"
                          style={{ background: 'var(--accent-tint)', color: 'var(--accent)' }}
                        >
                          <span className="truncate" style={{ maxWidth: 160 }}>{c.name}</span>
                          <button
                            type="button"
                            onClick={() => setCountryIds(ids => ids.filter(id => id !== String(c.country_id)))}
                            className="flex items-center justify-center rounded-full"
                            style={{ width: 14, height: 14 }}
                          >
                            <X size={11} />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                  <FilterDropdown
                    placeholder="Choose countries"
                    searchable
                    values={countryIds}
                    options={countries.map(c => ({ value: String(c.country_id), label: `${c.name} (${c.venue_count})` }))}
                    onChange={setCountryIds}
                  />
                </div>
              )}
            </div>
          </div>
        )}
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

  // Path A: opened via share link - join immediately
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

// ── Public rooms (visible directly on the page, not behind a separate link) ────

const MODE_OPTIONS = [
  { value: '1v1', label: '1v1' },
  { value: 'tournament', label: 'Tournament' },
]
const FORMAT_OPTIONS = [
  { value: 'T20', label: 'T20' },
  { value: 'ODI', label: 'ODI' },
  { value: 'Test', label: 'Test' },
]

function ModeChip({ mode }: { mode: string }) {
  return (
    <span
      className="text-[10px] px-1.5 py-0.5 rounded font-semibold inline-flex items-center gap-1"
      style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}
    >
      {mode === '1v1' ? <Users size={10} /> : <Crown size={10} />}
      {mode === '1v1' ? '1v1' : 'Tournament'}
    </span>
  )
}

function RoomCard({ room, onJoin }: { room: PublicRoomSummary; onJoin: (roomId: string) => void }) {
  return (
    <button
      onClick={() => onJoin(room.room_id)}
      className="card p-4 cursor-pointer w-full text-left transition-all duration-200"
      onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'}
      onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'}
    >
      <div className="flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold truncate" style={{ color: 'var(--text)' }}>
            {room.tournament_name}
          </div>
          <div className="flex items-center gap-1.5 mt-1.5">
            <FormatBadge format={room.match_format} />
            <ModeChip mode={room.mode} />
          </div>
          <div className="text-xs mt-1.5" style={{ color: 'var(--text-dim)' }}>
            Hosted by {room.host_name}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-sm font-bold" style={{ color: 'var(--accent)' }}>
            {room.members_joined}/{room.player_count}
          </div>
          <div className="text-xs" style={{ color: 'var(--text-dim)' }}>
            {room.spots_remaining === 1 ? '1 spot left' : `${room.spots_remaining} spots left`}
          </div>
        </div>
      </div>
    </button>
  )
}

function PublicRoomsSection({ onJoin }: { onJoin: (roomId: string) => void }) {
  const [mode, setMode] = useState<string[]>([])
  const [matchFormat, setMatchFormat] = useState<string[]>([])
  const { rooms, loading, refreshing, error, refetch } = usePublicRooms(mode, matchFormat)

  return (
    <div style={{ maxWidth: 560, margin: '0 auto', padding: '0 24px 64px' }}>
      <div className="flex items-center justify-between gap-2 mb-4">
        <div className="text-sm font-semibold flex-shrink-0" style={{ color: 'var(--text)' }}>Public Rooms</div>
        <div className="flex items-center gap-1.5">
          <div className="w-27">
            <FilterDropdown placeholder="All formats" values={matchFormat} options={FORMAT_OPTIONS} onChange={setMatchFormat} />
          </div>
          <div className="w-27">
            <FilterDropdown placeholder="All modes" values={mode} options={MODE_OPTIONS} onChange={setMode} />
          </div>
          <button
            onClick={() => refetch()}
            disabled={loading || refreshing}
            title="Refresh"
            className="icon-btn"
          >
            <RotateCw size={13} className={refreshing ? 'spin' : ''} />
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-8"><Spinner /></div>
      ) : error ? (
        <div className="card p-6 text-center text-sm" style={{ color: 'var(--text-dim)' }}>{error}</div>
      ) : rooms.length === 0 ? (
        <div className="card p-6 text-center text-sm" style={{ color: 'var(--text-dim)' }}>
          No public rooms open right now.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {rooms.map(room => (
            <RoomCard key={room.room_id} room={room} onJoin={onJoin} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function MultiplayerLobbyPage() {
  const params = useParams<{ roomId?: string }>()
  const { authReady, clientId } = useAuth()
  const navigate = useNavigate()

  const [modal, setModal] = useState<'create' | 'join' | null>(null)
  // Set when joining directly from a public rooms card below (not via the
  // /join/:roomId share-link route) - takes over as the join modal's
  // initialCode alongside params.roomId.
  const [joinCode, setJoinCode] = useState<string | undefined>(undefined)

  // Active-hosted-room cap (backend enforces this for real on POST /rooms;
  // this is just so Create Room can be disabled upfront instead of only
  // failing with a 429 after the whole form is filled in).
  const [roomCap, setRoomCap] = useState<{ count: number; limit: number } | null>(null)
  const atRoomCap = !!roomCap && roomCap.count >= roomCap.limit

  useEffect(() => {
    if (!authReady) return
    api.getActiveHostedRoomCount(clientId).then(setRoomCap).catch(() => setRoomCap(null))
  }, [authReady, clientId, modal])

  // Auto-open Join modal only after auth has settled (so displayName is the real profile name)
  useEffect(() => {
    if (params.roomId && authReady) setModal('join')
  }, [params.roomId, authReady])

  function joinFromBrowse(roomId: string) {
    setJoinCode(roomId)
    setModal('join')
  }

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
      <div className="flex flex-col items-center text-center px-6 pt-5 pb-8">
        <div className="text-xs font-semibold tracking-widest uppercase mb-2" style={{ color: 'var(--accent)' }}>
          Real-time Draft
        </div>
        <h1
          className="text-3xl md:text-4xl font-bold mb-3"
          style={{ color: 'var(--text)', letterSpacing: '-0.5px', lineHeight: 1.15 }}
        >
          Multiplayer Draft
        </h1>
        <p className="text-base max-w-sm mb-6" style={{ color: 'var(--text-muted)' }}>
          Create a room, invite friends, and build the best XI in a live snake draft.
        </p>

        {/* Two CTA buttons side by side */}
        <div className="flex gap-4">
          <button
            onClick={() => !atRoomCap && setModal('create')}
            disabled={atRoomCap}
            title={atRoomCap ? 'Finish or leave an existing room before creating another' : undefined}
            className="flex items-center gap-2.5 px-7 py-3.5 rounded-xl font-semibold text-sm transition-all"
            style={{
              background: atRoomCap ? 'var(--surface-2)' : 'var(--accent)',
              color: atRoomCap ? 'var(--text-dim)' : 'var(--bg)',
              boxShadow: atRoomCap ? 'none' : '0 4px 20px var(--accent-glow)',
              cursor: atRoomCap ? 'not-allowed' : 'pointer',
            }}
            onMouseEnter={e => { if (!atRoomCap) (e.currentTarget as HTMLElement).style.background = 'var(--accent-dim)' }}
            onMouseLeave={e => { if (!atRoomCap) (e.currentTarget as HTMLElement).style.background = 'var(--accent)' }}
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
        {atRoomCap && (
          <div className="text-xs mt-3" style={{ color: 'var(--text-dim)' }}>
            You already have {roomCap!.limit} active rooms — finish or leave one before creating another.
          </div>
        )}
      </div>

      {/* How-it-works strip */}
      <div style={{ maxWidth: 480, margin: '0 auto', padding: '0 24px 40px' }}>
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

      {/* Public rooms - visible directly, not behind a separate link */}
      <PublicRoomsSection onJoin={joinFromBrowse} />

      {/* Modals */}
      {modal === 'create' && <CreateRoomModal onClose={() => setModal(null)} />}
      {modal === 'join'   && (
        <JoinRoomModal
          initialCode={params.roomId ?? joinCode}
          onClose={() => { setModal(null); setJoinCode(undefined) }}
        />
      )}
    </div>
  )
}
