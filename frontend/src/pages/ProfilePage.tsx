import { useState } from 'react'
import { ChevronLeft, LogIn, LogOut } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'

export function ProfilePage() {
  const navigate = useNavigate()
  const { displayName, isLoggedIn, updateDisplayName, signOut, openAuthModal } = useAuth()

  const [nameInput, setNameInput] = useState(displayName)
  const [saving, setSaving]       = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [saved, setSaved]         = useState(false)

  const MAX_NAME_LENGTH = 32
  const isDirty = nameInput.trim() !== displayName
  const trimmedLength = nameInput.trim().length
  const isEmpty = trimmedLength === 0

  async function save() {
    const trimmed = nameInput.trim()
    if (!isDirty) return
    if (!trimmed) {
      setError('Display name cannot be empty')
      return
    }
    setSaving(true); setError(null); setSaved(false)
    try {
      await updateDisplayName(trimmed)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      setError('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      <button
        className="flex items-center gap-1 text-sm mb-6"
        style={{ color: 'var(--text-muted)' }}
        onClick={() => navigate(-1)}
      >
        <ChevronLeft size={14} /> Back
      </button>

      {/* Page header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', marginBottom: 2 }}>
            Profile
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            {isLoggedIn ? 'Logged in' : 'Playing as guest'}
          </div>
        </div>

        <button
          onClick={save}
          disabled={!isDirty || isEmpty || saving}
          style={{
            background: (isDirty && !isEmpty) ? 'var(--accent)' : 'var(--surface-2)',
            border: 'none', borderRadius: 8,
            padding: '8px 18px', cursor: (isDirty && !isEmpty) ? 'pointer' : 'default',
            color: (isDirty && !isEmpty) ? 'var(--bg)' : 'var(--text-dim)',
            fontSize: 13, fontWeight: 600,
            opacity: saving ? 0.6 : 1,
            transition: 'background 0.15s, color 0.15s',
          }}
        >
          {saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save'}
        </button>
      </div>

      {/* Form */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-muted)', letterSpacing: '0.02em' }}>
            Display name
          </label>
          <span style={{ fontSize: 11, color: trimmedLength >= MAX_NAME_LENGTH ? 'var(--loss)' : 'var(--text-dim)' }}>
            {trimmedLength}/{MAX_NAME_LENGTH}
          </span>
        </div>
        <input
          className="input"
          value={nameInput}
          onChange={e => { setNameInput(e.target.value); setError(null); setSaved(false) }}
          onKeyDown={e => { if (e.key === 'Enter') save() }}
          maxLength={MAX_NAME_LENGTH}
          style={{ width: '100%', fontSize: 14 }}
        />
        {error && (
          <div style={{
            marginTop: 8, fontSize: 12, color: 'var(--loss)',
            padding: '6px 10px', borderRadius: 6,
            background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
          }}>
            {error}
          </div>
        )}
      </div>

      <div style={{ marginTop: 32, paddingTop: 20 }}>
        <button
          onClick={() => (isLoggedIn ? signOut() : openAuthModal())}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            background: isLoggedIn ? 'rgba(239,68,68,0.08)' : 'var(--accent-tint)',
            border: `1px solid ${isLoggedIn ? 'rgba(239,68,68,0.35)' : 'var(--accent)'}`,
            borderRadius: 8, padding: '9px 16px',
            cursor: 'pointer', color: isLoggedIn ? 'var(--loss)' : 'var(--accent)', fontSize: 13, fontWeight: 600,
          }}
        >
          {isLoggedIn ? <LogOut size={14} /> : <LogIn size={14} />}
          {isLoggedIn ? 'Sign out' : 'Sign in'}
        </button>
      </div>
    </div>
  )
}
