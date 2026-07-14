import { useState } from 'react'

const AVATAR_COLORS = ['#00E5CC', '#F59E0B', '#0EA5E9', '#8B5CF6', '#EF4444', '#22C55E']

// Small list avatar (squad lists, draft picks): headshot image with initials fallback.
export function Headshot({ url, name, size = 32 }: {
  url?: string | null
  name?: string | null
  size?: number
}) {
  // Track WHICH url failed, not a boolean: rows keyed by a stable id (e.g. the
  // traded-out player) reuse this component instance with a new url prop, and
  // a stuck boolean would keep showing initials for the new player's valid
  // image (trade drawer bug: swapped-in player's photo never appeared).
  const [erroredUrl, setErroredUrl] = useState<string | null>(null)
  const safeName = name || '?'
  const initials = safeName.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
  const color = AVATAR_COLORS[safeName.charCodeAt(0) % AVATAR_COLORS.length]

  if (url && erroredUrl !== url) {
    return (
      <img
        src={url}
        alt={safeName}
        width={size}
        height={size}
        className="rounded-full object-cover flex-shrink-0"
        style={{ width: size, height: size }}
        onError={() => setErroredUrl(url)}
      />
    )
  }
  return (
    <div
      className="rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold"
      style={{ width: size, height: size, background: `${color}22`, color, border: `1px solid ${color}44` }}
    >
      {initials}
    </div>
  )
}

const PLAYER_AVATAR_COLORS = ['#0EA5E9', '#F97316', '#22C55E', '#F59E0B', '#8B5CF6', '#EF4444', '#EC4899', '#14B8A6']

// Larger featured avatar (leaderboards, POTM cards): initials-styled, optional headshot.
export function PlayerAvatar({ name, url, size = 44 }: {
  name: string
  url?: string | null
  size?: number
}) {
  // Same per-url error tracking as Headshot (see comment there).
  const [erroredUrl, setErroredUrl] = useState<string | null>(null)
  const initials = name.split(' ').filter(Boolean).map(w => w[0]).slice(0, 2).join('').toUpperCase()
  const color = PLAYER_AVATAR_COLORS[name.charCodeAt(0) % PLAYER_AVATAR_COLORS.length]

  if (url && erroredUrl !== url) {
    return (
      <img
        src={url}
        alt={name}
        onError={() => setErroredUrl(url)}
        style={{ width: size, height: size, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }}
      />
    )
  }
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: `${color}1A`, color, border: `1.5px solid ${color}55`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: Math.round(size * 0.36), fontWeight: 700, flexShrink: 0, letterSpacing: '-0.5px',
    }}>
      {initials}
    </div>
  )
}
