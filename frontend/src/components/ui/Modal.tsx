import { createPortal } from 'react-dom'
import { useEffect } from 'react'
import { X } from 'lucide-react'

// Generic centered popup shell (backdrop, header + close button, scrollable
// body capped to the viewport) - originally built inline for Multiplayer's
// Create/Join Room modals, extracted here once DraftPage needed the same
// shell for its read-only "view settings" popup, so both share one
// implementation instead of two copies of the same overflow/scroll fix.
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose])

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-md rounded-2xl flex flex-col overflow-hidden fade-in"
        style={{ background: 'var(--surface)', border: '1px solid var(--border)', boxShadow: '0 24px 48px rgba(0,0,0,0.5)', maxHeight: '90vh' }}
      >
        {/* Modal header */}
        <div className="flex items-center justify-between px-6 py-4 flex-shrink-0" style={{ borderBottom: '1px solid var(--border)' }}>
          <span className="font-semibold text-base" style={{ color: 'var(--text)' }}>{title}</span>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg transition-all"
            style={{ color: 'var(--text-muted)', background: 'transparent' }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'var(--surface-2)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'transparent'}
          >
            <X size={16} />
          </button>
        </div>
        <div className="px-6 py-5 flex flex-col gap-4 overflow-y-auto" style={{ minHeight: 0 }}>
          {children}
        </div>
      </div>
    </div>,
    document.body,
  )
}
