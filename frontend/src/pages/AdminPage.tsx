import { useEffect, useState } from 'react'
import { ChevronLeft, Check } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import type { AdminSettings } from '@/types'

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
  const [settings, setSettings] = useState<AdminSettings | null>(null)
  const [loading, setLoading]   = useState(true)
  const [saving, setSaving]     = useState<FieldKey | null>(null)
  const [errors, setErrors]     = useState<Partial<Record<FieldKey, string>>>({})

  useEffect(() => {
    api.getAdminSettings().then(setSettings).finally(() => setLoading(false))
  }, [])

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
          Changes take effect immediately, for every simulation on this server. Not persisted — resets to defaults on the next restart/deploy.
        </div>

        {loading || !settings ? (
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Loading…</div>
        ) : (
          <>
            <Section
              title="Log level"
              description="Minimum level written to simulation.log. errors.log always stays at WARNING regardless of this setting."
              error={errors.log_level}
            >
              <OptionRow
                options={['DEBUG', 'INFO', 'WARNING', 'ERROR']}
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
              description="Used whenever a simulation request doesn't specify its own — which is every simulation today, since the frontend never overrides this."
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
              description="Used whenever a simulation request doesn't specify its own — which is every simulation today, since the frontend never overrides this."
              error={errors.bowling_strategy}
            >
              <OptionRow
                options={settings.available_bowling_strategies}
                active={settings.bowling_strategy}
                disabled={saving === 'bowling_strategy'}
                onSelect={updateBowlingStrategy}
              />
            </Section>
          </>
        )}
      </div>
    </div>
  )
}
