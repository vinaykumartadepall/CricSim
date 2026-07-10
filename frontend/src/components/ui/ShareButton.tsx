import { useState } from 'react'
import { Share2, Check, Link as LinkIcon } from 'lucide-react'

interface ShareButtonProps {
  text: string
  url: string
  label?: string
  /** Lazily builds a result-card image to attach to the share sheet - only
   * called at click time (not on every render), and only used on browsers
   * that support Web Share's file attachments. Falls back to a plain
   * text+url share (or clipboard copy) everywhere else. */
  buildImage?: () => Promise<File | null>
  /** Overrides for callers that need this to match a specific banner's
   * background/padding (e.g. per-placement result banners) rather than the
   * default .btn-outline look. */
  style?: React.CSSProperties
}

// Single-action share - no dropdown. Web Share API when the browser/OS
// supports it (mobile Safari/Chrome, and increasingly desktop too); falls
// back to copying the link to the clipboard everywhere else, since a Share
// button that silently does nothing on unsupported browsers is worse than
// one that degrades to "copy" with a normal confirmation state.
export function ShareButton({ text, url, label = 'Share', buildImage, style }: ShareButtonProps) {
  const [copied, setCopied] = useState(false)
  const canNativeShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function'

  async function handleClick() {
    if (canNativeShare) {
      // Image-building failures fall back to a plain text+url share. This is
      // deliberately separate from the try/catch around navigator.share()
      // below - that one only ever means "the user cancelled the share
      // sheet," which must NOT trigger a second share-sheet popup without
      // the image.
      let file: File | null = null
      if (buildImage) {
        try {
          file = await buildImage()
        } catch {
          file = null
        }
      }
      const shareWithFile = !!file && !!navigator.canShare?.({ files: [file] })
      try {
        await (shareWithFile ? navigator.share({ text, url, files: [file!] }) : navigator.share({ text, url }))
      } catch {
        // Cancelled by the user - nothing to do.
      }
      return
    }
    try {
      await navigator.clipboard.writeText(`${text}\n\n${url}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      // Clipboard permission denied or unavailable - nothing sensible to fall back to.
    }
  }

  return (
    <button
      type="button"
      className="btn-outline flex items-center gap-1.5 text-xs"
      onClick={handleClick}
      style={style}
    >
      {copied ? <Check size={12} style={{ color: 'var(--win)' }} /> : canNativeShare ? <Share2 size={12} /> : <LinkIcon size={12} />}
      {copied ? 'Copied!' : label}
    </button>
  )
}
