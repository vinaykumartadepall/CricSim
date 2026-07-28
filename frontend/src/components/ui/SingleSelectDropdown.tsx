import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Check } from 'lucide-react'

export interface SingleSelectOption {
  value: string
  label: string
}

function SelectableItem({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left px-3 py-2 text-xs flex items-center justify-between gap-2 transition-colors"
      style={{ color: selected ? 'var(--accent)' : 'var(--text-muted)' }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.05)' }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'none' }}
    >
      <span className="truncate">{label}</span>
      {selected && <Check size={12} style={{ color: 'var(--accent)', flexShrink: 0 }} />}
    </button>
  )
}

// Single-select sibling of FilterDropdown - same visual shell (custom-themed
// trigger + option list standing in for a native <select>, whose open state
// can't be themed), but picking a value closes the dropdown immediately and
// there's exactly one value instead of an array. A built-in "Default" row
// clears the selection back to null (today's existing default behavior)
// rather than needing a separate clear button.
export function SingleSelectDropdown({
  placeholder, value, options, onChange, defaultLabel = 'Default', disabled = false,
}: {
  placeholder: string
  value: string | null
  options: SingleSelectOption[]
  onChange: (value: string | null) => void
  defaultLabel?: string
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [open])

  const selectedOption = options.find(o => o.value === value)
  const triggerText = selectedOption ? selectedOption.label : placeholder

  function pick(v: string | null) {
    onChange(v)
    setOpen(false)
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
          background: value ? 'var(--accent-tint)' : 'var(--surface-2)',
          border: `1px solid ${open || value ? 'var(--accent)' : 'var(--border)'}`,
          color: value ? 'var(--accent)' : 'var(--text-muted)',
          fontWeight: value ? 600 : 400,
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.6 : 1,
        }}
      >
        <span className="truncate">{triggerText}</span>
        <ChevronDown
          size={12}
          style={{ color: value ? 'var(--accent)' : 'var(--text-muted)', flexShrink: 0, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
        />
      </button>

      {open && (
        <div
          className="absolute left-0 right-0 mt-1 rounded-lg overflow-hidden fade-in"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)', boxShadow: '0 8px 24px rgba(0,0,0,0.45)', zIndex: 30 }}
        >
          <div style={{ maxHeight: 220, overflowY: 'auto' }}>
            <SelectableItem label={defaultLabel} selected={value === null} onClick={() => pick(null)} />
            {options.map(o => (
              <SelectableItem key={o.value} label={o.label} selected={o.value === value} onClick={() => pick(o.value)} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
