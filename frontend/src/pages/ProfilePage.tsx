import { useState } from 'react'
import { ChevronLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'

const SERIF = "'DM Serif Display', Georgia, 'Times New Roman', serif"
const SANS  = "'DM Sans', system-ui, sans-serif"

function initials(name: string): string {
  return name.split(/[\s_]+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('')
}

export function ProfilePage() {
  const navigate = useNavigate()
  const { displayName, isLoggedIn, updateDisplayName } = useAuth()

  const [nameInput, setNameInput] = useState(displayName)
  const [saving, setSaving]       = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [saved, setSaved]         = useState(false)

  const isDirty = nameInput.trim() !== displayName

  async function save() {
    const trimmed = nameInput.trim()
    if (!trimmed || !isDirty) return
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
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: SANS }}>
      <div style={{ maxWidth: 480, margin: '0 auto', padding: '48px 24px' }}>
        <button
          className="flex items-center gap-1 text-sm mb-6"
          style={{ color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
          onClick={() => navigate(-1)}
        >
          <ChevronLeft size={14} /> Back
        </button>

        {/* Page header row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 36 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{
              width: 48, height: 48, borderRadius: '50%',
              background: 'var(--accent)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 17, fontWeight: 700, color: 'var(--bg)', flexShrink: 0,
            }}>
              {initials(nameInput || displayName)}
            </div>
            <div>
              <div style={{ fontFamily: SERIF, fontSize: 20, color: 'var(--text)', fontWeight: 400, lineHeight: 1.2 }}>
                Profile
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 2 }}>
                {isLoggedIn ? 'Logged in' : 'Playing as guest'}
              </div>
            </div>
          </div>

          <button
            onClick={save}
            disabled={!isDirty || saving}
            style={{
              background: isDirty ? 'var(--accent)' : 'var(--surface-2)',
              border: 'none', borderRadius: 8,
              padding: '8px 18px', cursor: isDirty ? 'pointer' : 'default',
              color: isDirty ? 'var(--bg)' : 'var(--text-dim)',
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
          <label style={{
            display: 'block', fontSize: 12, fontWeight: 500,
            color: 'var(--text-muted)', marginBottom: 6, letterSpacing: '0.02em',
          }}>
            Display name
          </label>
          <input
            className="input"
            value={nameInput}
            onChange={e => { setNameInput(e.target.value); setError(null); setSaved(false) }}
            onKeyDown={e => { if (e.key === 'Enter') save() }}
            maxLength={32}
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

      </div>
    </div>
  )
}
