import { useState, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { ArrowUpDown, X, ArrowUp, ArrowDown, ChevronLeft } from 'lucide-react'
import type { Player, Team, SwapEntry } from '@/types'

const COMPATIBLE: Record<string, string[]> = {
  'Batter':      ['Batter', 'All-rounder', 'Keeper'],
  'Keeper':      ['Keeper', 'Batter', 'All-rounder'],
  'All-rounder': ['Batter', 'Keeper', 'All-rounder', 'Bowler'],
  'Bowler':      ['Bowler', 'All-rounder'],
}

function isCompatible(fromRole: string | null, toRole: string | null): boolean {
  if (!fromRole || !toRole) return true
  return (COMPATIBLE[fromRole] || []).includes(toRole)
}

function Headshot({ url, name, size = 32 }: { url: string | null; name: string; size?: number }) {
  const [errored, setErrored] = useState(false)
  const initials = name.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
  const colors = ['#00E5CC', '#F59E0B', '#0EA5E9', '#8B5CF6', '#EF4444', '#22C55E']
  const color = colors[name.charCodeAt(0) % colors.length]

  if (url && !errored) {
    return (
      <img
        src={url}
        alt={name}
        width={size}
        height={size}
        className="rounded-full object-cover flex-shrink-0"
        style={{ width: size, height: size }}
        onError={() => setErrored(true)}
      />
    )
  }
  return (
    <div
      className="rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold"
      style={{ width: size, height: size, background: color + '22', color, border: `1px solid ${color}44` }}
    >
      {initials}
    </div>
  )
}

function RoleBadge({ role }: { role: string | null }) {
  if (!role) return null
  const styles: Record<string, string> = {
    'Batter':      'bg-blue-500/15 text-blue-400 border-blue-500/25',
    'Keeper':      'bg-purple-500/15 text-purple-400 border-purple-500/25',
    'All-rounder': 'bg-teal-500/15 text-teal-400 border-teal-500/25',
    'Bowler':      'bg-orange-500/15 text-orange-400 border-orange-500/25',
  }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded border ${styles[role] || 'bg-gray-500/15 text-gray-400'}`}>
      {role}
    </span>
  )
}

interface Props {
  squad: Player[]
  allTeams: Team[]
  userTeamId: number
  maxSwaps?: number
  swaps: SwapEntry[]
  onSwapsChange: (swaps: SwapEntry[]) => void
  onOrderChange?: (playerIds: number[]) => void
}

export function SquadEditor({ squad, allTeams, userTeamId, maxSwaps, swaps, onSwapsChange, onOrderChange }: Props) {
  const [selectingFor, setSelectingFor] = useState<Player | null>(null)
  const [activeTeamId, setActiveTeamId] = useState<number | null>(null)
  const [reorderMode, setReorderMode] = useState(false)
  const [order, setOrder] = useState<number[]>(() => squad.map(p => p.player_id))

  const currentSquad = useMemo(() => {
    const byId = Object.fromEntries(squad.map(p => [p.player_id, p]))
    const swapMap = Object.fromEntries(swaps.map(s => [s.player_out_id, s]))
    return order
      .map(pid => byId[pid])
      .filter(Boolean)
      .map((p, idx) => {
        const swap = swapMap[p.player_id]
        if (swap) {
          const inPlayer = allTeams.flatMap(t => t.players).find(pl => pl.player_id === swap.player_in_id)
          return { ...p, _swapped: true, _swapIn: inPlayer || null, _position: idx + 1 }
        }
        return { ...p, _swapped: false, _swapIn: null, _position: idx + 1 }
      })
  }, [squad, swaps, order, allTeams])

  const swappedOutIds = new Set(swaps.map(s => s.player_out_id))
  const opponents = allTeams.filter(t => t.team_id !== userTeamId)
  const teamsWithSwap = new Set(swaps.map(s => s.from_team_id))

  const activeTeam = opponents.find(t => t.team_id === activeTeamId) ?? opponents[0] ?? null

  function openDrawer(player: Player) {
    if (reorderMode) return
    if (swappedOutIds.has(player.player_id)) return
    if (maxSwaps && swaps.length >= maxSwaps) return
    setSelectingFor(player)
    setActiveTeamId(opponents[0]?.team_id ?? null)
  }

  function closeDrawer() {
    setSelectingFor(null)
    setActiveTeamId(null)
  }

  function handleSwapIn(inPlayer: Player, fromTeam: Team) {
    if (!selectingFor) return
    const filtered = swaps.filter(
      s => s.player_out_id !== selectingFor.player_id && s.from_team_id !== fromTeam.team_id
    )
    onSwapsChange([...filtered, {
      player_out_id: selectingFor.player_id,
      player_in_id: inPlayer.player_id,
      from_team_id: fromTeam.team_id,
      player_out_name: selectingFor.player_name,
      player_in_name: inPlayer.player_name,
    }])
    closeDrawer()
  }

  function removeSwap(outId: number) {
    onSwapsChange(swaps.filter(s => s.player_out_id !== outId))
  }

  function moveUp(idx: number) {
    if (idx === 0) return
    const newOrder = [...order]
    ;[newOrder[idx - 1], newOrder[idx]] = [newOrder[idx], newOrder[idx - 1]]
    setOrder(newOrder)
    onOrderChange?.(newOrder)
  }

  function moveDown(idx: number) {
    if (idx === order.length - 1) return
    const newOrder = [...order]
    ;[newOrder[idx], newOrder[idx + 1]] = [newOrder[idx + 1], newOrder[idx]]
    setOrder(newOrder)
    onOrderChange?.(newOrder)
  }

  const canSwapMore = maxSwaps === undefined || swaps.length < maxSwaps

  // Drawer rendered via portal so it overlays everything regardless of parent stacking context
  const drawer = selectingFor ? createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={closeDrawer}
        style={{
          position: 'fixed', inset: 0, zIndex: 40,
          background: 'rgba(0,0,0,0.6)',
          backdropFilter: 'blur(2px)',
          animation: 'fadeIn 150ms ease',
        }}
      />

      {/* Drawer panel */}
      <div
        style={{
          position: 'fixed', top: 0, right: 0, bottom: 0, zIndex: 50,
          width: 'min(360px, 92vw)',
          background: 'var(--bg)',
          borderLeft: '1px solid var(--border)',
          display: 'flex', flexDirection: 'column',
          animation: 'slideInRight 200ms cubic-bezier(0.16,1,0.3,1)',
        }}
      >
        {/* Drawer header */}
        <div
          className="flex items-center gap-3 px-4 py-4 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}
        >
          <button
            onClick={closeDrawer}
            className="p-1.5 rounded-lg transition-all"
            style={{ color: 'var(--text-muted)', background: 'var(--surface-2)' }}
          >
            <ChevronLeft size={16} />
          </button>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-medium uppercase tracking-wider mb-0.5" style={{ color: 'var(--text-dim)' }}>
              Replace with
            </div>
            <div className="text-sm font-semibold truncate" style={{ color: 'var(--score)' }}>
              {selectingFor.player_name}
            </div>
          </div>
          <RoleBadge role={selectingFor.player_role} />
        </div>

        {/* Team tabs — horizontal scroll */}
        <div
          className="flex gap-2 px-3 py-2.5 overflow-x-auto flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}
        >
          {opponents.map(team => {
            const hasSwap = teamsWithSwap.has(team.team_id)
            const isActive = team.team_id === (activeTeamId ?? opponents[0]?.team_id)
            const shortName = team.team_name.split(' ').slice(-1)[0]
            return (
              <button
                key={team.team_id}
                onClick={() => setActiveTeamId(team.team_id)}
                className="shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-all whitespace-nowrap"
                style={{
                  background: isActive
                    ? hasSwap ? 'rgba(245,158,11,0.2)' : 'var(--accent)'
                    : hasSwap ? 'rgba(245,158,11,0.06)' : 'var(--surface-2)',
                  color: isActive
                    ? hasSwap ? 'var(--score)' : 'var(--bg)'
                    : hasSwap ? 'var(--score)' : 'var(--text-muted)',
                  border: `1px solid ${
                    isActive
                      ? hasSwap ? 'rgba(245,158,11,0.5)' : 'var(--accent)'
                      : hasSwap ? 'rgba(245,158,11,0.3)' : 'var(--border)'
                  }`,
                  opacity: hasSwap && !isActive ? 0.7 : 1,
                }}
              >
                {shortName}{hasSwap && ' ✓'}
              </button>
            )
          })}
        </div>

        {/* Player list — scrollable */}
        <div className="flex-1 overflow-y-auto">
          {/* Banner when this team's swap slot is used */}
          {activeTeam && teamsWithSwap.has(activeTeam.team_id) && (
            <div className="px-4 py-2.5 flex items-center gap-2"
              style={{ background: 'rgba(245,158,11,0.08)', borderBottom: '1px solid var(--border)' }}>
              <span className="text-xs" style={{ color: 'var(--score)' }}>
                Already using one player from {activeTeam.team_name.split(' ').slice(-1)[0]}.
                Remove that trade to pick a different player.
              </span>
            </div>
          )}

          {activeTeam?.players.map(p => {
            const compat = isCompatible(selectingFor.player_role, p.player_role)
            const teamUsed = teamsWithSwap.has(activeTeam.team_id)
            const disabled = !compat || teamUsed

            if (disabled) {
              return (
                <div
                  key={p.player_id}
                  className="flex items-center gap-3 px-4 py-3"
                  style={{ borderBottom: '1px solid var(--border)', opacity: teamUsed ? 0.35 : 0.3 }}
                >
                  <Headshot url={p.headshot_url} name={p.player_name} size={32} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm truncate" style={{ color: 'var(--text-muted)' }}>{p.player_name}</div>
                  </div>
                  <span className="text-xs shrink-0" style={{ color: 'var(--text-dim)' }}>
                    {teamUsed ? 'Team used' : 'Role mismatch'}
                  </span>
                </div>
              )
            }

            return (
              <button
                key={p.player_id}
                onClick={() => handleSwapIn(p, activeTeam)}
                className="flex items-center gap-3 px-4 py-3 w-full text-left transition-all"
                style={{ borderBottom: '1px solid var(--border)' }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'rgba(0,229,204,0.06)'}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'transparent'}
              >
                <Headshot url={p.headshot_url} name={p.player_name} size={32} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate" style={{ color: 'var(--text)' }}>{p.player_name}</div>
                  {(p.batting_style || p.bowling_style) && (
                    <div className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                      {p.batting_style}{p.bowling_style ? ` · ${p.bowling_style}` : ''}
                    </div>
                  )}
                </div>
                <RoleBadge role={p.player_role} />
              </button>
            )
          })}
        </div>
      </div>

      <style>{`
        @keyframes fadeIn { from { opacity: 0 } to { opacity: 1 } }
        @keyframes slideInRight { from { transform: translateX(100%) } to { transform: translateX(0) } }
      `}</style>
    </>,
    document.body
  ) : null

  return (
    <>
      {drawer}

      <div className="flex flex-col gap-3">
        {/* Header controls */}
        <div className="flex items-center justify-between">
          <div className="text-sm" style={{ color: 'var(--text-muted)' }}>
            {maxSwaps !== undefined
              ? `${swaps.length} / ${maxSwaps} trades used`
              : `${swaps.length} trade${swaps.length !== 1 ? 's' : ''} made`}
          </div>
          <button
            onClick={() => setReorderMode(r => !r)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg transition-all"
            style={{
              background: reorderMode ? 'rgba(0,229,204,0.1)' : 'var(--surface)',
              color: reorderMode ? 'var(--accent)' : 'var(--text-muted)',
              border: `1px solid ${reorderMode ? 'var(--accent)' : 'var(--border)'}`,
            }}
          >
            <ArrowUpDown size={12} />
            {reorderMode ? 'Done reordering' : 'Reorder batting'}
          </button>
        </div>

        {/* Squad list */}
        <div className="flex flex-col gap-1.5">
          {currentSquad.map((p, idx) => {
            const isSwappedOut = p._swapped
            const canSwap = !isSwappedOut && canSwapMore

            return (
              <div
                key={p.player_id}
                className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg transition-all"
                style={{
                  background: isSwappedOut ? 'rgba(34,197,94,0.06)' : 'var(--surface)',
                  border: `1px solid ${isSwappedOut ? 'rgba(34,197,94,0.3)' : 'var(--border)'}`,
                }}
              >
                {/* Position */}
                <span className="text-xs font-mono w-4 text-right flex-shrink-0" style={{ color: 'var(--text-dim)' }}>
                  {p._position}
                </span>

                {/* Headshot */}
                <div className="hidden md:block flex-shrink-0">
                  {isSwappedOut && p._swapIn ? (
                    <Headshot url={p._swapIn.headshot_url} name={p._swapIn.player_name} size={32} />
                  ) : (
                    <Headshot url={p.headshot_url} name={p.player_name} size={32} />
                  )}
                </div>

                {/* Name + style */}
                <div className="flex-1 min-w-0">
                  {isSwappedOut && p._swapIn ? (
                    <>
                      <div className="text-sm font-medium truncate" style={{ color: 'var(--win)' }}>
                        {p._swapIn.player_name}
                        <span className="ml-1.5 text-xs px-1 rounded"
                          style={{ background: 'rgba(34,197,94,0.15)', color: 'var(--win)' }}>NEW</span>
                      </div>
                      <div className="text-xs line-through truncate" style={{ color: 'var(--text-dim)' }}>
                        {p.player_name}
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="text-sm font-medium truncate" style={{ color: 'var(--text)' }}>
                        {p.player_name}
                      </div>
                      {(p.batting_style || p.player_role) && (
                        <div className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                          {p.batting_style}{p.bowling_style ? ` · ${p.bowling_style}` : ''}
                        </div>
                      )}
                    </>
                  )}
                </div>

                {/* Role badge */}
                <div className="hidden sm:block flex-shrink-0">
                  <RoleBadge role={isSwappedOut && p._swapIn ? p._swapIn.player_role : p.player_role} />
                </div>

                {/* Actions */}
                {reorderMode ? (
                  <div className="flex gap-1">
                    <button onClick={() => moveUp(idx)} disabled={idx === 0}
                      className="p-1 rounded" style={{ color: idx === 0 ? 'var(--text-dim)' : 'var(--text-muted)' }}>
                      <ArrowUp size={14} />
                    </button>
                    <button onClick={() => moveDown(idx)} disabled={idx === currentSquad.length - 1}
                      className="p-1 rounded" style={{ color: idx === currentSquad.length - 1 ? 'var(--text-dim)' : 'var(--text-muted)' }}>
                      <ArrowDown size={14} />
                    </button>
                  </div>
                ) : isSwappedOut ? (
                  <button
                    onClick={() => removeSwap(p.player_id)}
                    className="p-1 rounded-full flex-shrink-0"
                    style={{ color: 'var(--text-muted)', background: 'var(--surface-2)' }}
                    title="Undo trade"
                  >
                    <X size={12} />
                  </button>
                ) : (
                  <button
                    onClick={() => openDrawer(p)}
                    disabled={!canSwap}
                    className="text-xs px-2.5 py-1 rounded flex-shrink-0 font-semibold tracking-wide transition-all"
                    style={{
                      background: canSwap ? 'rgba(0,229,204,0.12)' : 'transparent',
                      color: canSwap ? 'var(--accent)' : 'var(--text-dim)',
                      border: `1px solid ${canSwap ? 'rgba(0,229,204,0.35)' : 'transparent'}`,
                      cursor: canSwap ? 'pointer' : 'not-allowed',
                    }}
                    onMouseEnter={e => canSwap && ((e.currentTarget as HTMLElement).style.background = 'rgba(0,229,204,0.22)')}
                    onMouseLeave={e => canSwap && ((e.currentTarget as HTMLElement).style.background = 'rgba(0,229,204,0.12)')}
                  >
                    TRADE
                  </button>
                )}
              </div>
            )
          })}
        </div>

        {/* Applied swaps chips */}
        {swaps.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {swaps.map(s => (
              <div
                key={s.player_out_id}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs"
                style={{ background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.2)' }}
              >
                <span style={{ color: 'var(--loss)' }}>{s.player_out_name}</span>
                <span style={{ color: 'var(--text-dim)' }}>→</span>
                <span style={{ color: 'var(--win)' }}>{s.player_in_name}</span>
                <button onClick={() => removeSwap(s.player_out_id)} style={{ color: 'var(--text-dim)' }}>
                  <X size={10} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Max swaps warning */}
        {maxSwaps !== undefined && swaps.length >= maxSwaps && (
          <div className="text-xs px-3 py-2 rounded-lg"
            style={{ background: 'rgba(245,158,11,0.08)', color: 'var(--score)', border: '1px solid rgba(245,158,11,0.2)' }}>
            Maximum {maxSwaps} trades reached. Remove a trade to make changes.
          </div>
        )}
      </div>
    </>
  )
}
