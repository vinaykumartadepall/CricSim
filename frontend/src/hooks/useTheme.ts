import { useState, useEffect } from 'react'
import type { Theme } from '@/types'

const STORAGE_KEY = 'cricsim_theme'
const DEFAULT: Theme = 'night-stadium'

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => {
    return (localStorage.getItem(STORAGE_KEY) as Theme) || DEFAULT
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  return { theme, setTheme: setThemeState }
}
