import { useState, useEffect } from 'react'
import type { Theme } from '@/types'

const STORAGE_KEY = 'cricsim_theme'
const DEFAULT: Theme = 'ember-amber'
const VALID: Theme[] = ['ember-amber', 'ember-emerald', 'ember-crimson', 'ember-ice']

function resolveTheme(): Theme {
  const saved = localStorage.getItem(STORAGE_KEY) as Theme
  return VALID.includes(saved) ? saved : DEFAULT
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(resolveTheme)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  return { theme, setTheme: setThemeState }
}
