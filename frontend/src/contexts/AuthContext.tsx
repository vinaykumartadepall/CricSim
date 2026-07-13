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
  authReady: boolean   // true once the initial session check + profile fetch has settled
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

  const applySession = useCallback(async (session: Session | null) => {
    if (!session?.user) {
      // Logged out → restore anon identity
      const anonId   = getOrCreateAnonId()
      const anonName = getOrCreateAnonName()
      localStorage.setItem(CLIENT_ID_KEY, anonId)
      setClientId(anonId)
      setUser(null)
      setDisplayName(anonName)
      return
    }

    const u = session.user
    setUser(u)

    // Switch client_id to user's stable ID
    const prevAnonId = localStorage.getItem(ANON_ID_KEY)
    localStorage.setItem(CLIENT_ID_KEY, u.id)
    setClientId(u.id)

    // Lazy-import api to avoid circular dep
    const { api } = await import('@/api/client')

    try {
      const profile = await api.getAuthProfile()
      setDisplayName(profile.display_name)
    } catch {
      // New user - create profile from Google name or existing anon name
      const googleName = (u.user_metadata?.full_name as string | undefined)
        || (u.user_metadata?.name as string | undefined)
      const nameToUse  = googleName || localStorage.getItem(ANON_NAME_KEY) || generateAnonName()

      try {
        await api.upsertAuthProfile(nameToUse)
        setDisplayName(nameToUse)
        // Migrate anonymous history in the background
        if (prevAnonId && prevAnonId !== u.id) {
          api.linkAnonymous(prevAnonId).catch(err =>
            console.warn('Failed to link anonymous simulations to signed-in account', err))
        }
      } catch (err) {
        console.warn('Failed to upsert auth profile (display name kept locally)', err)
        setDisplayName(nameToUse)
      }
    }
  }, [])

  useEffect(() => {
    // Ensure anon identity is seeded on first load
    getOrCreateAnonId()
    getOrCreateAnonName()

    if (!supabase) return  // Supabase not configured - stay anonymous

    supabase.auth.getSession().then(async ({ data: { session } }) => {
      await applySession(session)
      setAuthReady(true)
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_, session) => {
      applySession(session)
    })

    return () => subscription.unsubscribe()
  }, [applySession])

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
  }

  const updateDisplayName = async (name: string) => {
    if (user) {
      // Logged in - persisted server-side, keyed by the Supabase user id.
      const { api } = await import('@/api/client')
      await api.upsertAuthProfile(name)
    } else {
      // Guest - no auth session to attach, so /auth/profile would 401.
      // Persisted the same way the anon UUID is: localStorage only.
      localStorage.setItem(ANON_NAME_KEY, name)
    }
    setDisplayName(name)
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
