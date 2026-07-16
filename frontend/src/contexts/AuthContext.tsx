import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import type { User, Session } from '@supabase/supabase-js'
import { supabase } from '@/lib/supabase'

// ── Random cricket username ───────────────────────────────────────────────────

const ADJECTIVES = ['Swift', 'Deep', 'Quiet', 'Bold', 'Sharp', 'Wild', 'Clean', 'Spin', 'Fast', 'Raw', 'Calm', 'Late']
const CRICKET    = ['Yorker', 'Sixer', 'Midoff', 'Gully', 'Bouncer', 'Cover', 'Sweep', 'Googly', 'Keeper', 'Square', 'Point', 'Slip']

function generateAnonName(): string {
  const adj  = ADJECTIVES[Math.floor(Math.random() * ADJECTIVES.length)]
  const cric = CRICKET[Math.floor(Math.random() * CRICKET.length)]
  const num  = Math.floor(1000 + Math.random() * 9000)
  return `${adj}${cric}_${num}`
}

// ── Storage keys ──────────────────────────────────────────────────────────────

const CLIENT_ID_KEY = 'cricsim_client_id'
const ANON_ID_KEY   = 'cricsim_anon_id'    // preserves the original anon UUID
const ANON_NAME_KEY = 'cricsim_anon_name'
// Last username successfully returned by the server for a LOGGED-IN user - a
// fallback for when a /identity/link call fails for a reason that isn't a
// clean response (network blip, JWT mid-refresh), so the UI degrades to the
// last known-correct name instead of jumping to the Google/anon fallback name.
// Keyed per user id (not a single shared key) so switching accounts on the
// same browser can never show one user a fallback cached from another.
const LAST_KNOWN_NAME_PREFIX = 'cricsim_last_known_profile_name:'
function lastKnownNameKey(userId: string): string {
  return `${LAST_KNOWN_NAME_PREFIX}${userId}`
}

function getOrCreateAnonId(): string {
  let id = localStorage.getItem(ANON_ID_KEY)
  if (!id) {
    // Fall back to the UUID getClientId() may have already created
    id = localStorage.getItem(CLIENT_ID_KEY) || crypto.randomUUID()
    localStorage.setItem(ANON_ID_KEY, id)  // always persist so applySession can read it
  }
  return id
}

function getOrCreateAnonName(): string {
  let name = localStorage.getItem(ANON_NAME_KEY)
  if (!name) {
    name = generateAnonName()
    localStorage.setItem(ANON_NAME_KEY, name)
  }
  return name
}

// ── Context shape ─────────────────────────────────────────────────────────────

interface AuthContextValue {
  clientId: string
  displayName: string
  isLoggedIn: boolean
  authReady: boolean   // true once the initial session check + identity link has settled
  user: User | null
  signOut: () => Promise<void>
  updateDisplayName: (name: string) => Promise<void>
  openAuthModal: () => void
  authModalOpen: boolean
  setAuthModalOpen: (v: boolean) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

// ── Provider ──────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser]             = useState<User | null>(null)
  const [clientId, setClientId]     = useState<string>(() => {
    return localStorage.getItem(CLIENT_ID_KEY) || getOrCreateAnonId()
  })
  const [displayName, setDisplayName] = useState<string>(() => getOrCreateAnonName())
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [authReady, setAuthReady] = useState(!supabase)  // true immediately if no Supabase

  const syncAnonymous = useCallback(async (anonId: string, anonName: string) => {
    const { api } = await import('@/api/client')
    api.syncAnonymousIdentity(anonId, anonName).catch(err =>
      console.warn('Failed to sync anonymous identity', err))
  }, [])

  const applySession = useCallback(async (session: Session | null) => {
    if (!session?.user) {
      // Logged out → restore anon identity
      const anonId   = getOrCreateAnonId()
      const anonName = getOrCreateAnonName()
      localStorage.setItem(CLIENT_ID_KEY, anonId)
      setClientId(anonId)
      setUser(null)
      setDisplayName(anonName)
      syncAnonymous(anonId, anonName)
      return
    }

    const u = session.user
    const currentClientId = localStorage.getItem(CLIENT_ID_KEY) || getOrCreateAnonId()
    const googleName = (u.user_metadata?.full_name as string | undefined)
      || (u.user_metadata?.name as string | undefined)
    const fallbackUsername = googleName || localStorage.getItem(ANON_NAME_KEY) || generateAnonName()

    // Lazy-import api to avoid circular dep
    const { api } = await import('@/api/client')

    const doLink = () => api.linkIdentity(currentClientId, fallbackUsername)
    const applyLinked = (result: { canonical_id: string; username: string }) => {
      localStorage.setItem(CLIENT_ID_KEY, result.canonical_id)
      setClientId(result.canonical_id)
      setUser(u)
      setDisplayName(result.username)
      localStorage.setItem(lastKnownNameKey(u.id), result.username)
    }

    try {
      applyLinked(await doLink())
    } catch (err) {
      // The likely cause (JWT mid-refresh, a network blip) usually clears
      // within a second, so retry once before degrading.
      try {
        await new Promise(resolve => setTimeout(resolve, 800))
        applyLinked(await doLink())
      } catch (retryErr) {
        // Still failing - fall back to the last username we successfully
        // linked for this account (or the Google/anon name), and switch
        // client_id to the auth id as a best-effort guess so the session
        // still reads as logged-in rather than stuck mid-transition.
        console.warn('Failed to link identity after retry', retryErr)
        const cached = localStorage.getItem(lastKnownNameKey(u.id))
        localStorage.setItem(CLIENT_ID_KEY, u.id)
        setClientId(u.id)
        setUser(u)
        setDisplayName(cached || fallbackUsername)
      }
    }
  }, [syncAnonymous])

  useEffect(() => {
    // Ensure anon identity is seeded on first load
    const anonId   = getOrCreateAnonId()
    const anonName = getOrCreateAnonName()

    if (!supabase) {
      // Supabase not configured - stay anonymous, but still register this
      // identity so its username participates in the global uniqueness check.
      syncAnonymous(anonId, anonName)
      return
    }

    supabase.auth.getSession().then(async ({ data: { session } }) => {
      await applySession(session)
      setAuthReady(true)
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_, session) => {
      applySession(session)
    })

    return () => subscription.unsubscribe()
  }, [applySession, syncAnonymous])

  const signOut = async () => {
    await supabase?.auth.signOut()
    // Generate fresh anon identity after sign-out
    const newId   = crypto.randomUUID()
    const newName = generateAnonName()
    localStorage.setItem(ANON_ID_KEY, newId)
    localStorage.setItem(ANON_NAME_KEY, newName)
    localStorage.setItem(CLIENT_ID_KEY, newId)
    setClientId(newId)
    setUser(null)
    setDisplayName(newName)
    syncAnonymous(newId, newName)
  }

  const updateDisplayName = async (name: string) => {
    // Enforced server-side for both anonymous and signed-in identities -
    // usernames are globally unique (simulation.identity_links), so even an
    // anonymous rename has to round-trip to check for a collision.
    const { api } = await import('@/api/client')
    const result = await api.setUsername(clientId, name)
    if (user) {
      localStorage.setItem(lastKnownNameKey(user.id), result.username)
    } else {
      localStorage.setItem(ANON_NAME_KEY, result.username)
    }
    setDisplayName(result.username)
  }

  return (
    <AuthContext.Provider value={{
      clientId,
      displayName,
      isLoggedIn: !!user,
      authReady,
      user,
      signOut,
      updateDisplayName,
      openAuthModal: () => setAuthModalOpen(true),
      authModalOpen,
      setAuthModalOpen,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
