import { useEffect, useState } from 'react'
import { ChevronLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import {
  ADMIN_SANS, ADMIN_SERIF, AccessDenied, OptionRow, Section, isAuthError,
} from '@/components/admin/AdminUI'
import type { AdminSettings } from '@/types'

const SERIF = ADMIN_SERIF
const SANS  = ADMIN_SANS

type FieldKey = 'log_level' | 'cache_strategy' | 'outcome_strategy' | 'bowling_strategy'

export function AdminPage() {
  const navigate = useNavigate()
  const [settings, setSettings] = useState<AdminSettings | null>(null)
  const [loading, setLoading]   = useState(true)
  const [denied, setDenied]     = useState(false)
  const [saving, setSaving]     = useState<FieldKey | null>(null)
  const [errors, setErrors]     = useState<Partial<Record<FieldKey, string>>>({})

  useEffect(() => {
    api.getAdminSettings()
      .then(setSettings)
      .catch(err => {
        if (isAuthError(err)) setDenied(true)
        else console.warn('Failed to load admin settings', err)
      })
      .finally(() => setLoading(false))
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
          Changes take effect immediately, for every simulation on this server. Not persisted - resets to defaults on the next restart/deploy.
        </div>

        {denied ? (
          <AccessDenied />
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
              title="Data"
              description="Cross-user views and content editors."
            >
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {[
                  { label: 'All simulations →', path: '/site-admin/simulations' },
                  { label: 'Tournament editor →', path: '/site-admin/tournaments' },
                  { label: 'Player editor →', path: '/site-admin/players' },
                ].map(link => (
                  <button
                    key={link.path}
                    onClick={() => navigate(link.path)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6,
                      padding: '7px 14px', borderRadius: 7,
                      background: 'var(--surface-2)', border: '1px solid var(--border)',
                      color: 'var(--text-muted)', fontSize: 13, cursor: 'pointer',
                    }}
                  >
                    {link.label}
                  </button>
                ))}
              </div>
            </Section>
          </>
        )}
      </div>
    </div>
  )
}
