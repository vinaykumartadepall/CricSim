import type { VenueConfig } from '@/types'

// Single source of truth for the Advanced Settings option lists + their
// display labels - shared between MultiplayerLobbyPage's Create Room form
// (which sets these) and DraftPage's read-only "view settings" popup (which
// displays whatever a room ended up with), so the two never drift apart.

export const SCHEDULE_OPTIONS = [
  { value: 'round_robin', label: 'Round Robin' },
  { value: 'double_round_robin', label: 'Double Round Robin' },
]

export const PLAYOFF_OPTIONS = [
  { value: 'semis_final', label: 'Semis + Final' },
  { value: 'ipl', label: 'IPL-style (Qualifiers + Eliminator + Final)' },
]

export function scheduleLabel(value: string | null | undefined): string {
  return SCHEDULE_OPTIONS.find(o => o.value === value)?.label ?? 'Double Round Robin (default)'
}

export function playoffLabel(value: string | null | undefined): string {
  return PLAYOFF_OPTIONS.find(o => o.value === value)?.label ?? 'IPL-style (default)'
}

export function venueConfigSummary(config: VenueConfig | null | undefined): string {
  if (!config) return 'Curated venue list (default)'
  if (config.mode === 'specific') {
    return config.venues && config.venues.length > 0
      ? config.venues.join(', ')
      : 'Curated venue list (default)'
  }
  if (config.mode === 'country') {
    return config.country_names && config.country_names.length > 0
      ? config.country_names.join(', ')
      : 'Curated venue list (default)'
  }
  return 'Curated venue list (default)'
}
