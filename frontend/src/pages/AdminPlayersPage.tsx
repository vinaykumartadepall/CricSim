import { useEffect, useState } from 'react'
import { ChevronLeft, Search } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { Headshot } from '@/components/ui/Avatar'
import { RoleBadge } from '@/components/ui/RoleBadge'
import {
  ADMIN_SANS, ADMIN_SERIF, AccessDenied, OptionRow, SaveButton, adminInputStyle, isAuthError,
} from '@/components/admin/AdminUI'
import type { AdminPlayer, Country } from '@/types'

const ROLES = ['Batter', 'Bowler', 'All-rounder', 'Keeper']

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </span>
      {children}
    </div>
  )
}

export function AdminPlayersPage() {
  const navigate = useNavigate()
  const [q, setQ]                 = useState('')
  const [results, setResults]     = useState<AdminPlayer[]>([])
  const [countries, setCountries] = useState<Country[]>([])
  const [denied, setDenied]       = useState(false)
  const [searching, setSearching] = useState(false)

  const [selected, setSelected] = useState<AdminPlayer | null>(null)
  const [draft, setDraft]       = useState<AdminPlayer | null>(null)
  const [saving, setSaving]     = useState(false)
  const [saveError, setSaveError] = useState('')
  const [savedFlash, setSavedFlash] = useState(false)

  useEffect(() => {
    api.getAdminCountries()
      .then(setCountries)
      .catch(err => {
        if (isAuthError(err)) setDenied(true)
        else console.warn('Failed to load countries', err)
      })
  }, [])

  useEffect(() => {
    if (!q.trim()) { setResults([]); return }
    const t = setTimeout(() => {
      setSearching(true)
      api.searchAdminPlayers(q.trim())
        .then(setResults)
        .catch(err => {
          if (isAuthError(err)) setDenied(true)
          else console.warn('Player search failed', err)
        })
        .finally(() => setSearching(false))
    }, 300)
    return () => clearTimeout(t)
  }, [q])

  function select(p: AdminPlayer) {
    setSelected(p)
    setDraft({ ...p })
    setSaveError('')
    setSavedFlash(false)
  }

  const dirty = !!(selected && draft) && (
    draft.name !== selected.name ||
    draft.display_name !== selected.display_name ||
    draft.player_role !== selected.player_role ||
    draft.batting_style !== selected.batting_style ||
    draft.bowling_style !== selected.bowling_style ||
    draft.country_id !== selected.country_id ||
    draft.cricinfo_id !== selected.cricinfo_id ||
    draft.gender !== selected.gender
  )

  async function save() {
    if (!selected || !draft) return
    setSaving(true)
    setSaveError('')
    try {
      await api.putAdminPlayer(selected.player_id, {
        name: draft.name ?? undefined,
        display_name: draft.display_name ?? undefined,
        player_role: draft.player_role ?? undefined,
        batting_style: draft.batting_style ?? undefined,
        bowling_style: draft.bowling_style ?? undefined,
        country_id: draft.country_id ?? undefined,
        cricinfo_id: draft.cricinfo_id ?? undefined,
        gender: draft.gender ?? undefined,
      })
      const countryName = countries.find(c => c.country_id === draft.country_id)?.name ?? null
      const updated = { ...draft, country_name: countryName,
        headshot_url: draft.cricinfo_id ? `https://a.espncdn.com/i/headshots/cricket/players/full/${draft.cricinfo_id}.png` : null }
      setSelected(updated)
      setDraft({ ...updated })
      setResults(rs => rs.map(r => (r.player_id === updated.player_id ? updated : r)))
      setSavedFlash(true)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  function patch<K extends keyof AdminPlayer>(key: K, value: AdminPlayer[K]) {
    setDraft(d => (d ? { ...d, [key]: value } : d))
    setSavedFlash(false)
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: ADMIN_SANS }}>
      <div style={{ maxWidth: 880, margin: '0 auto', padding: '48px 24px' }}>
        <button
          className="flex items-center gap-1 text-sm mb-6"
          style={{ color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
          onClick={() => navigate('/site-admin')}
        >
          <ChevronLeft size={14} /> Admin Settings
        </button>

        <div style={{ fontFamily: ADMIN_SERIF, fontSize: 22, color: 'var(--text)', fontWeight: 400, marginBottom: 4 }}>
          Player Editor
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 24 }}>
          Edits history.players directly - name, role, country and styles apply everywhere,
          including future simulations. Stats are keyed by player id and are unaffected.
        </div>

        {denied ? <AccessDenied /> : (
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.2fr)', gap: 16 }}>
            {/* Search + results */}
            <div>
              <div style={{ position: 'relative', marginBottom: 10 }}>
                <Search size={14} style={{ position: 'absolute', left: 10, top: 10, color: 'var(--text-dim)' }} />
                <input
                  value={q}
                  onChange={e => setQ(e.target.value)}
                  placeholder="Search players…"
                  style={{ ...adminInputStyle, paddingLeft: 30 }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 520, overflowY: 'auto' }}>
                {searching && <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>Searching…</div>}
                {!searching && q.trim() && results.length === 0 && (
                  <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>No players found.</div>
                )}
                {results.map(p => (
                  <button
                    key={p.player_id}
                    onClick={() => select(p)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, textAlign: 'left',
                      padding: '7px 10px', borderRadius: 8, cursor: 'pointer',
                      background: selected?.player_id === p.player_id ? 'var(--accent-tint)' : 'var(--surface)',
                      border: `1px solid ${selected?.player_id === p.player_id ? 'var(--accent)' : 'var(--border)'}`,
                    }}
                  >
                    <Headshot url={p.headshot_url} name={p.display_name ?? p.name} size={28} />
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 13, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {p.display_name ?? p.name}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                        {p.country_name ?? '-'} · {p.matches_played ?? 0} matches
                      </div>
                    </div>
                    <RoleBadge role={p.player_role} />
                  </button>
                ))}
              </div>
            </div>

            {/* Edit form */}
            <div>
              {!draft ? (
                <div style={{ fontSize: 13, color: 'var(--text-dim)', paddingTop: 8 }}>
                  Search and select a player to edit.
                </div>
              ) : (
                <div style={{
                  padding: '18px 20px', borderRadius: 10,
                  background: 'var(--surface)', border: '1px solid var(--border)',
                  display: 'flex', flexDirection: 'column', gap: 14,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <Headshot url={draft.cricinfo_id ? `https://a.espncdn.com/i/headshots/cricket/players/full/${draft.cricinfo_id}.png` : null}
                      name={draft.display_name ?? draft.name} size={44} />
                    <div>
                      <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>{selected?.display_name ?? selected?.name}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-dim)', fontFamily: 'monospace' }}>id {draft.player_id}</div>
                    </div>
                  </div>

                  <Field label="Name">
                    <input style={adminInputStyle} value={draft.name ?? ''}
                      onChange={e => patch('name', e.target.value)} />
                  </Field>
                  <Field label="Display name">
                    <input style={adminInputStyle} value={draft.display_name ?? ''}
                      placeholder="(falls back to name)"
                      onChange={e => patch('display_name', e.target.value || null)} />
                  </Field>
                  <Field label="Role">
                    <OptionRow options={ROLES} active={draft.player_role ?? ''} disabled={saving}
                      onSelect={v => patch('player_role', v)} />
                  </Field>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    <Field label="Batting style">
                      <input style={adminInputStyle} value={draft.batting_style ?? ''}
                        onChange={e => patch('batting_style', e.target.value || null)} />
                    </Field>
                    <Field label="Bowling style">
                      <input style={adminInputStyle} value={draft.bowling_style ?? ''}
                        onChange={e => patch('bowling_style', e.target.value || null)} />
                    </Field>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    <Field label="Country">
                      <select style={adminInputStyle} value={draft.country_id ?? ''}
                        onChange={e => patch('country_id', e.target.value ? Number(e.target.value) : null)}>
                        <option value="">(none)</option>
                        {countries.map(c => (
                          <option key={c.country_id} value={c.country_id}>{c.name}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Cricinfo id (headshot)">
                      <input style={adminInputStyle} value={draft.cricinfo_id ?? ''}
                        onChange={e => patch('cricinfo_id', e.target.value ? Number(e.target.value) : null)} />
                    </Field>
                  </div>
                  <Field label="Gender">
                    <OptionRow options={['male', 'female']} active={draft.gender ?? ''} disabled={saving}
                      onSelect={v => patch('gender', v)} />
                  </Field>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <SaveButton onClick={save} saving={saving} dirty={dirty} />
                    {savedFlash && <span style={{ fontSize: 12, color: 'var(--win)' }}>Saved</span>}
                    {saveError && <span style={{ fontSize: 12, color: 'var(--loss)' }}>{saveError}</span>}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
