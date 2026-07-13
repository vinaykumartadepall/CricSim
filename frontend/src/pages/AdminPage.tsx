import { useEffect, useState } from 'react'
import { ChevronLeft, Check } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import type { AdminSettings, AdminSimRow } from '@/types'

const SERIF = "'DM Serif Display', Georgia, 'Times New Roman', serif"
const SANS  = "'DM Sans', system-ui, sans-serif"

type FieldKey = 'log_level' | 'cache_strategy' | 'outcome_strategy' | 'bowling_strategy'

function OptionRow({
  options, active, disabled, onSelect,
}: {
  options: string[]
  active: string
  disabled: boolean
  onSelect: (value: string) => void
}) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {options.map(opt => {
        const isActive = opt === active
        return (
          <button
            key={opt}
            disabled={disabled}
            onClick={() => onSelect(opt)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 7,
              background: isActive ? 'var(--accent-tint)' : 'var(--surface-2)',
              border: isActive ? '1px solid var(--accent)' : '1px solid var(--border)',
              color: isActive ? 'var(--accent)' : 'var(--text-muted)',
              fontSize: 13, fontWeight: isActive ? 600 : 400,
              cursor: disabled ? 'default' : 'pointer',
              opacity: disabled ? 0.6 : 1,
              transition: 'background 0.12s, color 0.12s',
            }}
          >
            {isActive && <Check size={12} />}
            {opt}
          </button>
        )
      })}
    </div>
  )
}

function Section({
  title, description, children, error,
}: {
  title: string
  description: string
  children: React.ReactNode
  error?: string | null
}) {
  return (
    <div style={{
      padding: '18px 20px', borderRadius: 10,
      background: 'var(--surface)', border: '1px solid var(--border)',
      marginBottom: 14,
    }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 12, lineHeight: 1.5 }}>{description}</div>
      {children}
      {error && (
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--loss)' }}>{error}</div>
      )}
    </div>
  )
}

export function AdminPage() {
  const navigate = useNavigate()
  const SIMS_PAGE_SIZE = 50

  const [settings, setSettings] = useState<AdminSettings | null>(null)
  const [loading, setLoading]   = useState(true)
  const [denied, setDenied]     = useState(false)
  const [saving, setSaving]     = useState<FieldKey | null>(null)
  const [errors, setErrors]     = useState<Partial<Record<FieldKey, string>>>({})

  const [sims, setSims]             = useState<AdminSimRow[]>([])
  const [simsTotal, setSimsTotal]   = useState(0)
  const [loadingSims, setLoadingSims] = useState(false)

  async function loadSims(offset: number) {
    setLoadingSims(true)
    try {
      const res = await api.getAdminSimulations(SIMS_PAGE_SIZE, offset)
      setSims(prev => (offset === 0 ? res.simulations : [...prev, ...res.simulations]))
      setSimsTotal(res.total)
    } catch (err) {
      console.warn('Failed to load admin simulations list', err)
    } finally {
      setLoadingSims(false)
    }
  }

  useEffect(() => {
    api.getAdminSettings()
      .then(s => {
        setSettings(s)
        loadSims(0)
      })
      .catch(err => {
        const msg = String(err instanceof Error ? err.message : err)
        // 401 = not signed in / token invalid, 403 = signed in but not an admin
        if (msg.startsWith('401') || msg.startsWith('403') || msg === 'Forbidden') setDenied(true)
        else console.warn('Failed to load admin settings', err)
      })
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function simLink(s: AdminSimRow): string {
    return s.simulation_type === 'match' && s.match_id
      ? `/results/${s.sim_id}/matches/${s.match_id}`
      : `/results/${s.sim_id}`
  }

  function statusColor(status: string): string {
    if (status === 'completed') return 'var(--win)'
    if (status === 'failed') return 'var(--loss)'
    return 'var(--score)'
  }

  async function updateLogLevel(level: string) {
    setSaving('log_level'); setErrors(e => ({ ...e, log_level: undefined }))
    try {
      const res = await api.setLogLevel(level)
      setSettings(s => s && { ...s, log_level: res.level })
    } catch {
      setErrors(e => ({ ...e, log_level: 'Failed to update log level' }))
    } finally {
      setSaving(null)
    }
  }

  async function updateCacheStrategy(strategy: string) {
    setSaving('cache_strategy'); setErrors(e => ({ ...e, cache_strategy: undefined }))
    try {
      const res = await api.setCacheStrategy(strategy)
      setSettings(s => s && { ...s, cache_strategy: res.strategy })
    } catch {
      setErrors(e => ({ ...e, cache_strategy: 'Failed to update cache strategy' }))
    } finally {
      setSaving(null)
    }
  }

  async function updateOutcomeStrategy(outcome_strategy: string) {
    setSaving('outcome_strategy'); setErrors(e => ({ ...e, outcome_strategy: undefined }))
    try {
      const res = await api.setSimulationDefaults({ outcome_strategy })
      setSettings(s => s && { ...s, outcome_strategy: res.outcome_strategy })
    } catch {
      setErrors(e => ({ ...e, outcome_strategy: 'Failed to update outcome strategy' }))
    } finally {
      setSaving(null)
    }
  }

  async function updateBowlingStrategy(bowling_strategy: string) {
    setSaving('bowling_strategy'); setErrors(e => ({ ...e, bowling_strategy: undefined }))
    try {
      const res = await api.setSimulationDefaults({ bowling_strategy })
      setSettings(s => s && { ...s, bowling_strategy: res.bowling_strategy })
    } catch {
      setErrors(e => ({ ...e, bowling_strategy: 'Failed to update bowling strategy' }))
    } finally {
      setSaving(null)
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: SANS }}>
      <div style={{ maxWidth: 560, margin: '0 auto', padding: '48px 24px' }}>
        <button
          className="flex items-center gap-1 text-sm mb-6"
          style={{ color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
          onClick={() => navigate(-1)}
        >
          <ChevronLeft size={14} /> Back
        </button>

        <div style={{ fontFamily: SERIF, fontSize: 22, color: 'var(--text)', fontWeight: 400, marginBottom: 4 }}>
          Admin Settings
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 28 }}>
          Changes take effect immediately, for every simulation on this server. Not persisted - resets to defaults on the next restart/deploy.
        </div>

        {denied ? (
          <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.6 }}>
            Admin access required. Sign in with the admin account, then reload this page.
          </div>
        ) : loading || !settings ? (
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Loading…</div>
        ) : (
          <>
            <Section
              title="Log level"
              description="Minimum level written to simulation.log. errors.log always stays at WARNING regardless of this setting. TRACE enables extremely high-volume per-ball/per-over strategy dumps - use only for a short, targeted window, not an extended test."
              error={errors.log_level}
            >
              <OptionRow
                options={['TRACE', 'DEBUG', 'INFO', 'WARNING', 'ERROR']}
                active={settings.log_level}
                disabled={saving === 'log_level'}
                onSelect={updateLogLevel}
              />
            </Section>

            <Section
              title="Stats cache strategy"
              description="persistent keeps precomputed player stats cached for the whole process lifetime (until a low-RAM eviction). per_job clears the cache at the end of every simulation job, trading cross-simulation reuse for a bounded memory footprint."
              error={errors.cache_strategy}
            >
              <OptionRow
                options={settings.available_cache_strategies}
                active={settings.cache_strategy}
                disabled={saving === 'cache_strategy'}
                onSelect={updateCacheStrategy}
              />
            </Section>

            <Section
              title="Default ball outcome strategy"
              description="Used whenever a simulation request doesn't specify its own - which is every simulation today, since the frontend never overrides this."
              error={errors.outcome_strategy}
            >
              <OptionRow
                options={settings.available_outcome_strategies}
                active={settings.outcome_strategy}
                disabled={saving === 'outcome_strategy'}
                onSelect={updateOutcomeStrategy}
              />
            </Section>

            <Section
              title="Default bowling selection strategy"
              description="Used whenever a simulation request doesn't specify its own - which is every simulation today, since the frontend never overrides this."
              error={errors.bowling_strategy}
            >
              <OptionRow
                options={settings.available_bowling_strategies}
                active={settings.bowling_strategy}
                disabled={saving === 'bowling_strategy'}
                onSelect={updateBowlingStrategy}
              />
            </Section>

            <Section
              title="All simulations"
              description={`Every user's simulations, newest first, failed runs included${simsTotal ? ` - ${simsTotal} total` : ''}.`}
            >
              {sims.length === 0 ? (
                <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                  {loadingSims ? 'Loading…' : 'No simulations yet.'}
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  {sims.map(s => (
                    <div
                      key={s.sim_id}
                      onClick={() => navigate(simLink(s))}
                      title={s.error_message ?? undefined}
                      style={{
                        display: 'flex', alignItems: 'baseline', gap: 10,
                        padding: '8px 2px', cursor: 'pointer',
                        borderBottom: '1px solid var(--border)', fontSize: 12,
                      }}
                    >
                      <span style={{ color: 'var(--text-dim)', whiteSpace: 'nowrap', flexShrink: 0 }}>
                        {new Date(s.created_at).toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                      </span>
                      <span style={{ color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, flex: 1 }}>
                        {s.tournament_name ?? s.simulation_type}
                        {s.season ? ` ${s.season}` : ''}
                        {s.user_team_name && (
                          <span style={{ color: 'var(--text-muted)' }}> · {s.user_team_name}</span>
                        )}
                      </span>
                      <span style={{ fontFamily: 'monospace', color: 'var(--text-dim)', flexShrink: 0 }}>
                        {s.client_id ? s.client_id.slice(0, 8) : 'anon'}
                      </span>
                      <span style={{ color: statusColor(s.status), flexShrink: 0, fontWeight: 600 }}>
                        {s.status}
                      </span>
                    </div>
                  ))}
                  {sims.length < simsTotal && (
                    <button
                      disabled={loadingSims}
                      onClick={() => loadSims(sims.length)}
                      style={{
                        marginTop: 10, alignSelf: 'flex-start', padding: '6px 14px',
                        borderRadius: 7, background: 'var(--surface-2)',
                        border: '1px solid var(--border)', color: 'var(--text-muted)',
                        fontSize: 12, cursor: loadingSims ? 'default' : 'pointer',
                      }}
                    >
                      {loadingSims ? 'Loading…' : `Load more (${sims.length}/${simsTotal})`}
                    </button>
                  )}
                </div>
              )}
            </Section>
          </>
        )}
      </div>
    </div>
  )
}
