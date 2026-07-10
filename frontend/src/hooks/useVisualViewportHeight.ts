import { useEffect, useState } from 'react'

// `100dvh`/`fixed inset-0` are unaware of the on-screen keyboard on mobile -
// the layout viewport doesn't shrink when it opens, only the visual one, so
// a bottom-sheet positioned via `justify-end` inside `fixed inset-0` ends up
// rendered partly behind the keyboard instead of sitting above it. Tracking
// window.visualViewport directly and sizing the overlay to it is the fix
// that actually accounts for the keyboard, not just browser chrome.
export function useVisualViewportHeight(): number | null {
  const [height, setHeight] = useState<number | null>(
    typeof window !== 'undefined' && window.visualViewport ? window.visualViewport.height : null
  )
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const update = () => setHeight(vv.height)
    update()
    vv.addEventListener('resize', update)
    vv.addEventListener('scroll', update)
    return () => {
      vv.removeEventListener('resize', update)
      vv.removeEventListener('scroll', update)
    }
  }, [])
  return height
}
