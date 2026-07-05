import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Share, MessageCircle, Link as LinkIcon, Check } from 'lucide-react'

const MENU_WIDTH = 190

function MenuItem({ icon, label, onClick }: { icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left px-3 py-2 text-xs flex items-center gap-2.5 transition-colors"
      style={{ color: 'var(--text)' }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.05)' }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'none' }}
    >
      <span className="flex items-center justify-center flex-shrink-0" style={{ width: 13 }}>{icon}</span>
      <span className="truncate">{label}</span>
    </button>
  )
}

// Share menu for a result — Web Share API when the browser/OS supports it
// (mobile Safari/Chrome, and increasingly desktop too), plus explicit X and
// WhatsApp intents and a copy-link fallback for everywhere else.
export function ShareButton({ text, url, label = 'Share' }: { text: string; url: string; label?: string }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const canNativeShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function'

  useEffect(() => {
    if (!open) return
    function onOutside(e: MouseEvent) {
      const target = e.target as Node
      if (triggerRef.current?.contains(target)) return
      if (menuRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [open])

  useEffect(() => { if (!open) setCopied(false) }, [open])

  function toggleOpen() {
    if (!open) {
      // Menu renders in a portal at a fixed viewport position (computed from
      // the trigger's own rect) instead of position:absolute inside whatever
      // happens to contain this button — several call sites (e.g. the
      // tournament result banner) have overflow:hidden for rounded corners,
      // which would otherwise silently clip the menu and make it look like
      // the button just does nothing.
      const rect = triggerRef.current?.getBoundingClientRect()
      if (rect) {
        setMenuPos({ top: rect.bottom + 4, left: Math.max(8, rect.right - MENU_WIDTH) })
      }
    }
    setOpen(o => !o)
  }

  async function shareNative() {
    try {
      await navigator.share({ text, url })
      setOpen(false)
    } catch {
      // Cancelled by the user, or the call itself isn't actually supported —
      // either way leave the menu open so the explicit fallbacks are there.
    }
  }

  function shareToX() {
    const params = new URLSearchParams({ text, url })
    window.open(`https://twitter.com/intent/tweet?${params.toString()}`, '_blank', 'noopener,noreferrer')
    setOpen(false)
  }

  function shareToWhatsapp() {
    const params = new URLSearchParams({ text: `${text}\n\n${url}` })
    window.open(`https://wa.me/?${params.toString()}`, '_blank', 'noopener,noreferrer')
    setOpen(false)
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(`${text}\n\n${url}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      // Clipboard permission denied or unavailable — nothing sensible to
      // fall back to here, so just leave the button un-confirmed.
    }
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="btn-outline flex items-center gap-1.5 text-xs py-1.5 px-2.5"
        onClick={toggleOpen}
      >
        <Share size={12} /> {label}
      </button>

      {open && menuPos && createPortal(
        <div
          ref={menuRef}
          className="fixed rounded-lg overflow-hidden fade-in"
          style={{
            top: menuPos.top, left: menuPos.left, width: MENU_WIDTH,
            background: 'var(--surface)', border: '1px solid var(--border)',
            boxShadow: '0 8px 24px rgba(0,0,0,0.45)', zIndex: 100,
          }}
        >
          {canNativeShare && <MenuItem icon={<Share size={13} />} label="Share…" onClick={shareNative} />}
          <MenuItem icon={<span style={{ fontSize: 12, fontWeight: 700 }}>𝕏</span>} label="Share to X" onClick={shareToX} />
          <MenuItem icon={<MessageCircle size={13} />} label="Share to WhatsApp" onClick={shareToWhatsapp} />
          <MenuItem
            icon={copied ? <Check size={13} style={{ color: 'var(--win)' }} /> : <LinkIcon size={13} />}
            label={copied ? 'Copied!' : 'Copy link'}
            onClick={copyLink}
          />
        </div>,
        document.body,
      )}
    </>
  )
}
