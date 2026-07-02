import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

interface HelpContextValue {
  helpOpen: boolean
  openHelp: (startSlide?: number, singleSlide?: boolean) => void
  closeHelp: () => void
  helpInitialSlide: number
  helpSingleSlide: boolean
  helpBlocked: boolean
  setHelpBlocked: (blocked: boolean) => void
}

const HelpContext = createContext<HelpContextValue>({
  helpOpen: false,
  openHelp: () => {},
  closeHelp: () => {},
  helpInitialSlide: 0,
  helpSingleSlide: false,
  helpBlocked: false,
  setHelpBlocked: () => {},
})

export function HelpProvider({ children }: { children: ReactNode }) {
  const [helpOpen, setHelpOpen] = useState(false)
  const [helpInitialSlide, setHelpInitialSlide] = useState(0)
  const [helpSingleSlide, setHelpSingleSlide] = useState(false)
  // Set by a page that isn't ready for its auto-help popup yet (e.g. a
  // simulation is still running) — HelpModal defers auto-opening until false.
  const [helpBlocked, setHelpBlocked] = useState(false)

  const openHelp = useCallback((startSlide = 0, singleSlide = false) => {
    setHelpInitialSlide(startSlide)
    setHelpSingleSlide(singleSlide)
    setHelpOpen(true)
  }, [])

  const closeHelp = useCallback(() => setHelpOpen(false), [])

  return (
    <HelpContext.Provider value={{ helpOpen, openHelp, closeHelp, helpInitialSlide, helpSingleSlide, helpBlocked, setHelpBlocked }}>
      {children}
    </HelpContext.Provider>
  )
}

export function useHelp() {
  return useContext(HelpContext)
}
