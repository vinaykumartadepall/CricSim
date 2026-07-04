import { useEffect } from 'react'

// Module-level counter shared by every caller, so multiple independent
// lockers (sidebar, modals) can be active at once without stomping on each
// other's "previous value" the way separate capture/restore effects would —
// the body only becomes scrollable again once every locker has released it.
let lockCount = 0

export function useBodyScrollLock(locked: boolean) {
  useEffect(() => {
    if (!locked) return
    lockCount += 1
    document.body.style.overflow = 'hidden'
    return () => {
      lockCount -= 1
      if (lockCount <= 0) {
        lockCount = 0
        document.body.style.overflow = ''
      }
    }
  }, [locked])
}
