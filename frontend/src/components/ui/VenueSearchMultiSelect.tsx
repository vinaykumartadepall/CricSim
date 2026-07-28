import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '@/api/client'
import type { VenueSearchResult } from '@/types'

// Debounced (250ms) server search against the real venue database, picking
// zero or more specific venues by name - generalized from
// AdminTournamentEditorPage.tsx's inline VenuesCard search-dropdown pattern
// (same debounce/API shape) into a real reusable component, since the admin
// version is tightly coupled to its own per-row editing state.
export function VenueSearchMultiSelect({
  values, onChange, placeholder = 'Search venues…',
}: {
  values: string[]
  onChange: (values: string[]) => void
  placeholder?: string
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<VenueSearchResult[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open || !query.trim()) { setResults([]); return }
    setLoading(true)
    const t = setTimeout(() => {
      api.searchMultiplayerVenues(query.trim())
        .then(setResults)
        .catch(() => setResults([]))
        .finally(() => setLoading(false))
    }, 250)
    return () => clearTimeout(t)
  }, [query, open])

  useEffect(() => {
    if (!open) return
    function onOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [open])

  function addVenue(name: string) {
    if (!values.includes(name)) onChange([...values, name])
    setQuery('')
  }

  function removeVenue(name: string) {
    onChange(values.filter(v => v !== name))
  }

  return (
    <div className="flex flex-col gap-2" ref={rootRef}>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map(name => (
            <span
              key={name}
              className="text-xs pl-2.5 pr-1.5 py-1 rounded-full flex items-center gap-1"
              style={{ background: 'var(--accent-tint)', color: 'var(--accent)' }}
            >
              <span className="truncate" style={{ maxWidth: 160 }}>{name}</span>
              <button
                type="button"
                onClick={() => removeVenue(name)}
                className="flex items-center justify-center rounded-full"
                style={{ width: 14, height: 14 }}
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <input
          className="input input-placeholder-muted"
          style={{ fontSize: 12, padding: '7px 10px' }}
          type="search" autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
          placeholder={placeholder}
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
        />
        {open && query.trim() && (
          <div
            className="absolute left-0 right-0 mt-1 rounded-lg overflow-hidden fade-in"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)', boxShadow: '0 8px 24px rgba(0,0,0,0.45)', zIndex: 30 }}
          >
            <div style={{ maxHeight: 220, overflowY: 'auto' }}>
              {loading ? (
                <div className="px-3 py-3 text-xs text-center" style={{ color: 'var(--text-dim)' }}>Searching…</div>
              ) : results.length === 0 ? (
                <div className="px-3 py-3 text-xs text-center" style={{ color: 'var(--text-dim)' }}>No matches</div>
              ) : (
                results.map(r => {
                  const already = values.includes(r.name)
                  return (
                    <button
                      key={r.name}
                      type="button"
                      disabled={already}
                      onClick={() => addVenue(r.name)}
                      className="w-full text-left px-3 py-2 text-xs flex items-center justify-between gap-2 transition-colors"
                      style={{ color: already ? 'var(--text-dim)' : 'var(--text)', opacity: already ? 0.5 : 1, cursor: already ? 'not-allowed' : 'pointer' }}
                      onMouseEnter={e => { if (!already) (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.05)' }}
                      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'none' }}
                    >
                      <span className="truncate">{r.name}{already ? ' (added)' : ''}</span>
                      <span className="shrink-0" style={{ fontSize: 10, color: 'var(--text-dim)' }}>
                        {[r.city, r.country].filter(Boolean).join(', ')}
                      </span>
                    </button>
                  )
                })
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
