import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, ChevronDown, ChevronLeft, ChevronUp, Plus, Search, X } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '@/api/client'
import { Headshot } from '@/components/ui/Avatar'
import { RoleBadge } from '@/components/ui/RoleBadge'
import {
  ADMIN_SANS, ADMIN_SERIF, AccessDenied, OptionRow, SaveButton, Section, adminInputStyle, isAuthError,
} from '@/components/admin/AdminUI'
import type { AdminPlayer, AdminTeamDetail, AdminTournamentDetail, AdminVenue, Player } from '@/types'

type VenueDraft = { name: string; city: string; previous_name?: string }

function errText(err: unknown): string {
  return err instanceof Error ? err.message : 'Save failed'
}

// ── Tournament meta card ────────────────────────────────────────────────────────

function MetaCard({ detail, onSaved }: {
  detail: AdminTournamentDetail
  onSaved: (fields: { tournament_name?: string; format?: string; gender?: string }) => void
}) {
  const [name, setName]     = useState(detail.tournament_name ?? '')
  const [format, setFormat] = useState(detail.format ?? 'T20')
  const [gender, setGender] = useState(detail.gender ?? 'male')
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  const dirty = name !== (detail.tournament_name ?? '') || format !== (detail.format ?? 'T20')
    || gender !== (detail.gender ?? 'male')

  async function save() {
    if (format !== detail.format &&
        !window.confirm(`Change format ${detail.format} → ${format}? This switches the match engine for every new simulation of this tournament.`)) {
      return
    }
    setSaving(true); setError('')
    try {
      await api.putAdminTournamentMeta(detail.tournament_id, {
        tournament_name: name, format, gender,
      })
      onSaved({ tournament_name: name, format, gender })
    } catch (err) { setError(errText(err)) } finally { setSaving(false) }
  }

  return (
    <Section title="Tournament" description={`Season ${detail.season}. Renaming also updates the wizard listing for this season.`} error={error}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <input style={adminInputStyle} value={name} onChange={e => setName(e.target.value)} />
        <OptionRow options={['T20', 'ODI', 'Test']} active={format} disabled={saving} onSelect={setFormat} />
        <OptionRow options={['male', 'female']} active={gender} disabled={saving} onSelect={setGender} />
        <div><SaveButton onClick={save} saving={saving} dirty={dirty} /></div>
      </div>
    </Section>
  )
}

// ── Venues card ─────────────────────────────────────────────────────────────────

function VenuesCard({ detail, onSaved }: {
  detail: AdminTournamentDetail
  onSaved: () => void
}) {
  const original = detail.venues ?? []
  const [venues, setVenues] = useState<VenueDraft[]>(
    original.map(v => ({ name: v.name, city: v.city ?? '', previous_name: v.name })))
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  // Venue-name LOV: names must exist in history.venues (enforced server-side
  // too) or matches there would play with no venue context stats.
  const [lovIdx, setLovIdx] = useState<number | null>(null)
  const [lovResults, setLovResults] = useState<{ name: string; city: string | null; country: string | null }[]>([])

  useEffect(() => {
    if (lovIdx === null) { setLovResults([]); return }
    const q = venues[lovIdx]?.name ?? ''
    const t = setTimeout(() => {
      api.searchAdminVenues(q)
        .then(setLovResults)
        .catch(err => {
          console.warn('Venue search failed', err)
          setError(`Venue lookup failed: ${errText(err)}`)
        })
    }, 250)
    return () => clearTimeout(t)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lovIdx, lovIdx !== null ? venues[lovIdx]?.name : ''])

  const dirty = JSON.stringify(venues.map(v => [v.name, v.city])) !==
    JSON.stringify(original.map(v => [v.name, v.city ?? '']))

  function patch(i: number, field: 'name' | 'city', value: string) {
    setVenues(vs => vs.map((v, j) => (j === i ? { ...v, [field]: value } : v)))
  }

  function pickVenue(i: number, v: { name: string; city: string | null }) {
    setVenues(vs => vs.map((entry, j) => (j === i ? { ...entry, name: v.name, city: v.city ?? '' } : entry)))
    setLovIdx(null)
  }

  async function save() {
    setSaving(true); setError('')
    try {
      await api.putAdminVenues(detail.tournament_id, venues.map(v => ({
        name: v.name, city: v.city,
        // only meaningful for entries that existed before this save
        previous_name: v.previous_name,
      })))
      onSaved()
    } catch (err) { setError(errText(err)) } finally { setSaving(false) }
  }

  return (
    <Section title="Venues" description="Pick names from the list (they must match the historical venue registry for venue stats to apply). Renames cascade into team home grounds; removing a venue clears it from any team using it." error={error}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {venues.map((v, i) => (
          <div key={i}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input style={{ ...adminInputStyle, flex: 2 }} value={v.name} placeholder="Venue name"
                onFocus={() => setLovIdx(i)}
                onChange={e => { patch(i, 'name', e.target.value); setLovIdx(i) }} />
              <input style={{ ...adminInputStyle, flex: 1 }} value={v.city} placeholder="City"
                onChange={e => patch(i, 'city', e.target.value)} />
              <button onClick={() => { setVenues(vs => vs.filter((_, j) => j !== i)); setLovIdx(null) }}
                style={{ color: 'var(--text-dim)', flexShrink: 0 }} title="Remove venue">
                <X size={14} />
              </button>
            </div>
            {lovIdx === i && lovResults.length > 0 && (
              <div style={{
                margin: '4px 0 4px 0', padding: 4, borderRadius: 8,
                background: 'var(--surface-2)', border: '1px solid var(--border)',
              }}>
                {lovResults.map(r => (
                  <button key={r.name} onClick={() => pickVenue(i, r)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
                      padding: '5px 8px', borderRadius: 6, cursor: 'pointer', background: 'none', border: 'none',
                    }}>
                    <span style={{ fontSize: 12.5, color: 'var(--text)', flex: 1 }}>{r.name}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      {[r.city, r.country].filter(Boolean).join(', ')}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
          <button
            onClick={() => setVenues(vs => [...vs, { name: '', city: '' }])}
            style={{
              display: 'flex', alignItems: 'center', gap: 5, padding: '6px 12px', borderRadius: 7,
              background: 'var(--surface-2)', border: '1px solid var(--border)',
              color: 'var(--text-muted)', fontSize: 12, cursor: 'pointer',
            }}
          >
            <Plus size={12} /> Add venue
          </button>
          <SaveButton onClick={save} saving={saving} dirty={dirty} />
        </div>
      </div>
    </Section>
  )
}

// ── Schedule card ───────────────────────────────────────────────────────────────

function ScheduleCard({ detail, onSaved }: {
  detail: AdminTournamentDetail
  onSaved: () => void
}) {
  const [raw, setRaw] = useState(() => JSON.stringify(
    { schedule: detail.schedule, playoffs: detail.playoffs }, null, 2))
  const [initial]     = useState(raw)
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  async function save() {
    setSaving(true); setError('')
    try {
      const parsed = JSON.parse(raw)
      await api.putAdminSchedule(detail.tournament_id, {
        schedule: parsed.schedule, playoffs: parsed.playoffs,
      })
      onSaved()
    } catch (err) {
      setError(err instanceof SyntaxError ? `Invalid JSON: ${err.message}` : errText(err))
    } finally { setSaving(false) }
  }

  return (
    <Section title="Schedule & playoffs"
      description="Raw config sections, validated server-side before saving. schedule.type: round_robin | double_round_robin | two_group_hybrid; neutral_venues=false plays home fixtures at each team's home ground; playoffs.format: none | ipl | semis_final."
      error={error}>
      <textarea
        value={raw}
        onChange={e => setRaw(e.target.value)}
        spellCheck={false}
        style={{ ...adminInputStyle, fontFamily: 'monospace', fontSize: 12, minHeight: 160, resize: 'vertical' }}
      />
      <div style={{ marginTop: 8 }}>
        <SaveButton onClick={save} saving={saving} dirty={raw !== initial} />
      </div>
    </Section>
  )
}

// ── Team card (meta + squad) ────────────────────────────────────────────────────

function TeamCard({ detail, team, onChanged }: {
  detail: AdminTournamentDetail
  team: AdminTeamDetail
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)

  // meta
  const [name, setName]           = useState(team.team_name)
  const [shortName, setShortName] = useState(team.short_name ?? '')
  const [primary, setPrimary]     = useState(team.primary_color ?? '#1E88E5')
  const [secondary, setSecondary] = useState(team.secondary_color ?? '#FFFFFF')
  const [homeVenue, setHomeVenue] = useState(team.home_venue ?? '')
  const [savingMeta, setSavingMeta] = useState(false)
  const [metaError, setMetaError]   = useState('')

  const metaDirty = name !== team.team_name || shortName !== (team.short_name ?? '')
    || primary !== (team.primary_color ?? '#1E88E5') || secondary !== (team.secondary_color ?? '#FFFFFF')
    || homeVenue !== (team.home_venue ?? '')

  // squad
  const [squad, setSquad] = useState<Player[]>(team.players)
  const [squadDirty, setSquadDirty] = useState(false)
  const [savingSquad, setSavingSquad] = useState(false)
  const [squadError, setSquadError]   = useState('')
  const [replacingIdx, setReplacingIdx] = useState<number | null>(null)
  const [searchQ, setSearchQ] = useState('')
  const [searchResults, setSearchResults] = useState<AdminPlayer[]>([])

  useEffect(() => {
    if (replacingIdx === null || !searchQ.trim()) { setSearchResults([]); return }
    const t = setTimeout(() => {
      api.searchAdminPlayers(searchQ.trim(), 10)
        .then(setSearchResults)
        .catch(err => console.warn('Player search failed', err))
    }, 300)
    return () => clearTimeout(t)
  }, [searchQ, replacingIdx])

  async function saveMeta() {
    setSavingMeta(true); setMetaError('')
    try {
      await api.putAdminTeamMeta(detail.tournament_id, team.team_id, {
        name, short_name: shortName,
        primary_color: primary, secondary_color: secondary,
        ...(homeVenue ? { home_venue: homeVenue } : { clear_home_venue: true }),
      })
      onChanged()
    } catch (err) { setMetaError(errText(err)) } finally { setSavingMeta(false) }
  }

  function move(i: number, dir: -1 | 1) {
    const j = i + dir
    if (j < 0 || j >= squad.length) return
    setSquad(s => {
      const next = [...s]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
    setSquadDirty(true)
  }

  function replaceAt(i: number, p: AdminPlayer) {
    if (squad.some((sp, j) => j !== i && sp.player_id === p.player_id)) {
      setSquadError(`${p.display_name ?? p.name} is already in this squad`)
      return
    }
    setSquad(s => s.map((sp, j) => (j === i ? {
      player_id: p.player_id,
      player_name: p.display_name ?? p.name,
      player_role: p.player_role,
      batting_style: p.batting_style,
      bowling_style: p.bowling_style,
      cricinfo_id: p.cricinfo_id,
      headshot_url: p.headshot_url,
      country_name: p.country_name,
    } : sp)))
    setReplacingIdx(null)
    setSearchQ('')
    setSquadDirty(true)
    setSquadError('')
  }

  async function saveSquad() {
    setSavingSquad(true); setSquadError('')
    try {
      await api.putAdminSquad(detail.tournament_id, team.team_id,
        squad.map((p, i) => ({ player_id: p.player_id, batting_position: i + 1 })))
      setSquadDirty(false)
      onChanged()
    } catch (err) { setSquadError(errText(err)) } finally { setSavingSquad(false) }
  }

  return (
    <div style={{
      borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--border)',
      marginBottom: 10, overflow: 'hidden',
    }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 10, width: '100%', textAlign: 'left',
          padding: '12px 16px', cursor: 'pointer', background: 'none', border: 'none',
        }}
      >
        <span style={{ width: 14, height: 14, borderRadius: 4, background: team.primary_color ?? '#1E88E5', flexShrink: 0 }} />
        <span style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text)', flex: 1 }}>
          {team.team_name}
          <span style={{ color: 'var(--text-dim)', fontWeight: 400, marginLeft: 8 }}>{team.short_name}</span>
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{team.home_venue ?? 'no home ground'}</span>
        {open ? <ChevronUp size={14} style={{ color: 'var(--text-dim)' }} /> : <ChevronDown size={14} style={{ color: 'var(--text-dim)' }} />}
      </button>

      {open && (
        <div style={{ padding: '0 16px 16px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Meta */}
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8 }}>
            <input style={adminInputStyle} value={name} onChange={e => setName(e.target.value)} placeholder="Team name" />
            <input style={adminInputStyle} value={shortName} onChange={e => setShortName(e.target.value)} placeholder="Short" />
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-muted)' }}>
              Primary <input type="color" value={primary} onChange={e => setPrimary(e.target.value)} style={{ width: 34, height: 24, border: 'none', background: 'none', cursor: 'pointer' }} />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-muted)' }}>
              Secondary <input type="color" value={secondary} onChange={e => setSecondary(e.target.value)} style={{ width: 34, height: 24, border: 'none', background: 'none', cursor: 'pointer' }} />
            </label>
            <select style={{ ...adminInputStyle, width: 'auto', flex: 1, minWidth: 160 }} value={homeVenue}
              onChange={e => setHomeVenue(e.target.value)}>
              <option value="">No home ground</option>
              {(detail.venues ?? []).map((v: AdminVenue) => (
                <option key={v.name} value={v.name}>{v.name}</option>
              ))}
            </select>
            <SaveButton onClick={saveMeta} saving={savingMeta} dirty={metaDirty} label="Save team" />
          </div>
          {metaError && <div style={{ fontSize: 12, color: 'var(--loss)' }}>{metaError}</div>}

          {/* Squad */}
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12 }}>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
              Squad · batting order
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {squad.map((p, i) => (
                <div key={`${p.player_id}-${i}`}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text-dim)', width: 16, textAlign: 'right' }}>{i + 1}</span>
                    <Headshot url={p.headshot_url} name={p.player_name} size={24} />
                    <span style={{ fontSize: 13, color: 'var(--text)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {p.player_name}
                    </span>
                    <RoleBadge role={p.player_role} />
                    <button onClick={() => move(i, -1)} disabled={i === 0}
                      style={{ color: i === 0 ? 'var(--text-dim)' : 'var(--text-muted)', padding: 2 }}><ArrowUp size={13} /></button>
                    <button onClick={() => move(i, 1)} disabled={i === squad.length - 1}
                      style={{ color: i === squad.length - 1 ? 'var(--text-dim)' : 'var(--text-muted)', padding: 2 }}><ArrowDown size={13} /></button>
                    <button
                      onClick={() => { setReplacingIdx(replacingIdx === i ? null : i); setSearchQ(''); setSearchResults([]) }}
                      style={{
                        fontSize: 11, padding: '3px 8px', borderRadius: 6, cursor: 'pointer',
                        background: replacingIdx === i ? 'var(--accent-tint)' : 'var(--surface-2)',
                        border: `1px solid ${replacingIdx === i ? 'var(--accent)' : 'var(--border)'}`,
                        color: replacingIdx === i ? 'var(--accent)' : 'var(--text-muted)',
                      }}
                    >
                      Replace
                    </button>
                  </div>
                  {replacingIdx === i && (
                    <div style={{ margin: '6px 0 6px 24px', padding: 8, borderRadius: 8, background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
                      <div style={{ position: 'relative' }}>
                        <Search size={12} style={{ position: 'absolute', left: 8, top: 9, color: 'var(--text-dim)' }} />
                        <input autoFocus value={searchQ} onChange={e => setSearchQ(e.target.value)}
                          placeholder={`Replace ${p.player_name}…`}
                          style={{ ...adminInputStyle, paddingLeft: 26, fontSize: 12 }} />
                      </div>
                      {searchResults.map(r => (
                        <button key={r.player_id} onClick={() => replaceAt(i, r)}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
                            padding: '5px 6px', borderRadius: 6, cursor: 'pointer', background: 'none', border: 'none',
                          }}>
                          <Headshot url={r.headshot_url} name={r.display_name ?? r.name} size={20} />
                          <span style={{ fontSize: 12, color: 'var(--text)', flex: 1 }}>{r.display_name ?? r.name}</span>
                          <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{r.country_name ?? ''}</span>
                          <RoleBadge role={r.player_role} />
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10 }}>
              <SaveButton onClick={saveSquad} saving={savingSquad} dirty={squadDirty} label="Save squad" />
              {squadError && <span style={{ fontSize: 12, color: 'var(--loss)' }}>{squadError}</span>}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Page ────────────────────────────────────────────────────────────────────────

export function AdminTournamentEditorPage() {
  const navigate = useNavigate()
  const { tournamentId } = useParams()
  const [detail, setDetail]   = useState<AdminTournamentDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [denied, setDenied]   = useState(false)

  function load() {
    api.getAdminTournamentDetail(Number(tournamentId))
      .then(setDetail)
      .catch(err => {
        if (isAuthError(err)) setDenied(true)
        else console.warn('Failed to load tournament detail', err)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournamentId])

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: ADMIN_SANS }}>
      <div style={{ maxWidth: 760, margin: '0 auto', padding: '48px 24px' }}>
        <button
          className="flex items-center gap-1 text-sm mb-6"
          style={{ color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
          onClick={() => navigate('/site-admin/tournaments')}
        >
          <ChevronLeft size={14} /> Tournaments
        </button>

        {denied ? <AccessDenied /> : loading || !detail ? (
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Loading…</div>
        ) : (
          <>
            <div style={{ fontFamily: ADMIN_SERIF, fontSize: 22, color: 'var(--text)', fontWeight: 400, marginBottom: 4 }}>
              {detail.tournament_name} {detail.season}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 24 }}>
              Every edit is validated against the tournament engine's config parser and
              recorded in the admin edit log for cross-database replay.
            </div>

            <MetaCard key={`meta-${detail.tournament_name}-${detail.format}-${detail.gender}`}
              detail={detail} onSaved={load} />
            <VenuesCard key={`venues-${JSON.stringify(detail.venues)}`} detail={detail} onSaved={load} />
            <ScheduleCard key={`sched-${JSON.stringify(detail.schedule)}-${JSON.stringify(detail.playoffs)}`}
              detail={detail} onSaved={load} />

            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', margin: '20px 0 10px' }}>
              Teams
            </div>
            {detail.teams.map(team => (
              <TeamCard
                key={`${team.team_id}-${team.team_name}-${team.short_name}-${team.home_venue}-${team.primary_color}-${team.secondary_color}`}
                detail={detail} team={team} onChanged={load}
              />
            ))}
          </>
        )}
      </div>
    </div>
  )
}
