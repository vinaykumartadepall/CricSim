const KEY = 'cricsim_client_id'
// Random per-browser secret that proves this browser owns its client_id. The
// server records it on first use and from then on accepts only this one
// (api/identity_auth.py), so a client_id seen elsewhere (leaderboards, rooms)
// is useless without it. Never shown to anyone and never put in a URL.
const SECRET_KEY = 'cricsim_client_secret'
const SECRET_LOCK = 'cricsim-client-secret'

export function getClientId(): string {
  let id = localStorage.getItem(KEY)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(KEY, id)
  }
  return id
}

function newSecret(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}

function createSecretIfMissing(): string {
  let secret = localStorage.getItem(SECRET_KEY)
  if (!secret) {
    secret = newSecret()
    localStorage.setItem(SECRET_KEY, secret)
  }
  return secret
}

/**
 * This browser's secret, creating it the first time. Creation runs under a
 * cross-tab lock: two tabs opened at the same moment must end up with the SAME
 * secret - if each made its own, the server would accept whichever arrived
 * first and permanently refuse the other.
 */
export async function getClientSecret(): Promise<string> {
  const existing = localStorage.getItem(SECRET_KEY)
  if (existing) return existing
  if (navigator.locks) {
    return navigator.locks.request(SECRET_LOCK, async () => createSecretIfMissing())
  }
  return createSecretIfMissing()   // browsers without Web Locks (very old)
}

const RESET_GUARD_KEY = 'cricsim_identity_reset_at'
const ANON_KEYS = [KEY, 'cricsim_anon_id', 'cricsim_anon_name']

/**
 * Start a fresh anonymous identity and reload. Used only when the server says
 * this browser's anonymous identity can't be used any more: it belongs to a
 * signed-in account (sign in to see it), or its secret no longer matches.
 * Guarded so a persistent server problem can't cause a reload loop.
 */
export function resetAnonymousIdentity(): boolean {
  const last = Number(sessionStorage.getItem(RESET_GUARD_KEY) || 0)
  if (Date.now() - last < 60_000) return false
  sessionStorage.setItem(RESET_GUARD_KEY, String(Date.now()))
  ANON_KEYS.forEach(k => localStorage.removeItem(k))
  window.location.reload()
  return true
}
