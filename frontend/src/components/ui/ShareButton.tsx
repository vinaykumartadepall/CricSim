import { useState } from 'react'
import { Share2, Check, Link as LinkIcon } from 'lucide-react'

// Single-action share — no dropdown. Web Share API when the browser/OS
// supports it (mobile Safari/Chrome, and increasingly desktop too); falls
// back to copying the link to the clipboard everywhere else, since a Share
// button that silently does nothing on unsupported browsers is worse than
// one that degrades to "copy" with a normal confirmation state.
export function ShareButton({ text, url, label = 'Share' }: { text: string; url: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  const canNativeShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function'

  async function handleClick() {
    if (canNativeShare) {
      try {
        await navigator.share({ text, url })
      } catch {
        // Cancelled by the user — nothing to do.
      }
      return
    }
    try {
      await navigator.clipboard.writeText(`${text}\n\n${url}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      // Clipboard permission denied or unavailable — nothing sensible to fall back to.
    }
  }

  return (
    <button
      type="button"
      className="btn-outline flex items-center gap-1.5 text-xs py-1.5 px-2.5"
      onClick={handleClick}
    >
      {copied ? <Check size={12} style={{ color: 'var(--win)' }} /> : canNativeShare ? <Share2 size={12} /> : <LinkIcon size={12} />}
      {copied ? 'Copied!' : label}
    </button>
  )
}
