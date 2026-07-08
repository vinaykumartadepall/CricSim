import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Check } from 'lucide-react'

export interface FilterDropdownOption {
  value: string
  label: string
}

function CheckableItem({ label, checked, onClick }: { label: string; checked: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left px-3 py-2 text-xs flex items-center gap-2 transition-colors"
      style={{ color: checked ? 'var(--text)' : 'var(--text-muted)' }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.05)' }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'none' }}
    >
      <span
        className="flex items-center justify-center rounded flex-shrink-0"
        style={{
          width: 14, height: 14,
          background: checked ? 'var(--accent)' : 'transparent',
          border: `1px solid ${checked ? 'var(--accent)' : 'var(--border)'}`,
        }}
      >
        {checked && <Check size={10} style={{ color: 'var(--bg)' }} />}
      </span>
      <span className="truncate">{label}</span>
    </button>
  )
}

// Custom themed multi-select dropdown standing in for a native <select> —
// a native select's closed state can be styled, but its open option list is
// rendered by the OS/browser and can't be themed at all, so it always looks
// like a jarring, unstyled popup dropped on top of the app's own dark
// surfaces. This renders the whole thing (trigger + list) with the app's own
// surface/border/accent tokens instead, and — since these filters should be
// combinable, not one-at-a-time — supports selecting more than one value,
// staying open between picks so multiple items can be checked in one go.
export function FilterDropdown({
  placeholder, values, options, onChange, searchable = false, disabled = false,
}: {
  placeholder: string
  values: string[]
  options: FilterDropdownOption[]
  onChange: (values: string[]) => void
  searchable?: boolean
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [open])

  useEffect(() => { if (!open) setSearch('') }, [open])

  const filtered = searchable && search.trim()
    ? options.filter(o => o.label.toLowerCase().includes(search.trim().toLowerCase()))
    : options

  const selectedLabels = options.filter(o => values.includes(o.value)).map(o => o.label)
  const triggerText =
    selectedLabels.length === 0 ? placeholder
    : selectedLabels.length === 1 ? selectedLabels[0]
    : `${selectedLabels.length} selected`

  function toggle(v: string) {
    onChange(values.includes(v) ? values.filter(x => x !== v) : [...values, v])
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => !disabled && setOpen(o => !o)}
        disabled={disabled}
        className="w-full flex items-center justify-between gap-1.5 rounded-lg transition-colors"
        style={{
          padding: '7px 10px',
          fontSize: 12,
          background: values.length > 0 ? 'var(--accent-tint)' : 'var(--surface-2)',
          border: `1px solid ${open || values.length > 0 ? 'var(--accent)' : 'var(--border)'}`,
          color: values.length > 0 ? 'var(--accent)' : 'var(--text-muted)',
          fontWeight: values.length > 0 ? 600 : 400,
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.6 : 1,
        }}
      >
        <span className="truncate">{triggerText}</span>
        <ChevronDown
          size={12}
          style={{ color: values.length > 0 ? 'var(--accent)' : 'var(--text-dim)', flexShrink: 0, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
        />
      </button>

      {open && (
        <div
          className="absolute left-0 right-0 mt-1 rounded-lg overflow-hidden fade-in"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)', boxShadow: '0 8px 24px rgba(0,0,0,0.45)', zIndex: 30 }}
        >
          {searchable && (
            <div className="p-1.5" style={{ borderBottom: '1px solid var(--border)' }}>
              <input
                autoFocus
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search…"
                className="input"
                style={{ fontSize: 12, padding: '6px 8px' }}
              />
            </div>
          )}
          <div style={{ maxHeight: 200, overflowY: 'auto' }}>
            {values.length > 0 && (
              <button
                type="button"
                onClick={() => onChange([])}
                className="w-full text-left px-3 py-2 text-xs transition-colors"
                style={{ color: 'var(--text-dim)', borderBottom: '1px solid var(--border)' }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.05)' }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'none' }}
              >
                Clear selection
              </button>
            )}
            {filtered.map(o => (
              <CheckableItem key={o.value} label={o.label} checked={values.includes(o.value)} onClick={() => toggle(o.value)} />
            ))}
            {filtered.length === 0 && (
              <div className="px-3 py-3 text-xs text-center" style={{ color: 'var(--text-dim)' }}>No matches</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
