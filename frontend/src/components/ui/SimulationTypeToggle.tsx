import { Zap, Crown } from 'lucide-react'

// Purely a UI hook for now - Captain Mode (interactive, manual batting/bowling
// control) isn't implemented yet. Automatic is the only real option; Captain
// is shown as a locked-preview card so the feature has a visible, on-brand
// home to land in later rather than appearing out of nowhere.
export function SimulationTypeToggle() {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-medium uppercase tracking-wide" style={{ color: 'var(--text-dim)' }}>
        Simulation Type
      </label>
      <div className="grid grid-cols-2 gap-2.5">
        {/* Automatic - the active choice. Gold border/icon/title/tint already
            communicate selection, no separate "Active" badge needed. */}
        <div
          className="relative flex flex-col items-center gap-1 rounded-xl px-3 py-3.5 text-center"
          style={{
            background: 'var(--accent-tint)',
            border: '1px solid var(--accent)',
            boxShadow: '0 0 0 3px var(--accent-glow)',
          }}
        >
          <Zap size={18} style={{ color: 'var(--accent)' }} />
          <span className="text-sm font-semibold" style={{ color: 'var(--accent)' }}>Automatic</span>
          <span className="text-[11px] leading-snug" style={{ color: 'var(--text-muted)' }}>Sit back and let the match unfold</span>
        </div>

        {/* Captain - locked preview */}
        <div
          className="relative flex flex-col items-center gap-1 rounded-xl px-3 py-3.5 text-center"
          style={{ background: 'var(--surface-2)', border: '1px dashed var(--border)', opacity: 0.92 }}
          title="Captain is coming soon"
        >
          <span
            className="absolute top-1.5 right-1.5 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full"
            style={{ background: 'var(--text-dim)', color: 'var(--text-muted)' }}
          >
            Soon
          </span>
          <Crown size={18} style={{ color: 'var(--text-dim)' }} />
          <span className="text-sm font-semibold" style={{ color: 'var(--text-dim)' }}>Captain</span>
          <span className="text-[11px] leading-snug" style={{ color: 'var(--text-dim)' }}>Make key decisions during the match</span>
        </div>
      </div>
    </div>
  )
}
