// IPL and the World Cup are what most players are looking for — surface
// them first instead of making users hunt alphabetically. Everything else
// stays alphabetical. Shared across every single-player mode's tournament
// picker (Fun Mode, Challenge Mode, Custom Mode) so they can't drift.
const PINNED_TOURNAMENTS = ['Indian Premier League', 'ICC Cricket World Cup']

export function sortTournamentNames(names: string[]): string[] {
  const pinned = PINNED_TOURNAMENTS.filter(n => names.includes(n))
  const rest = names.filter(n => !PINNED_TOURNAMENTS.includes(n)).sort()
  return [...pinned, ...rest]
}
