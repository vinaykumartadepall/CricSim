// Parses the backend's match result description strings ("X won by 20 runs",
// "Match tied · Y won Super Over", …). This is the ONLY place allowed to know
// those formats - a backend wording change must break exactly one function,
// not several page-local regexes silently (see the em-dash incident).
//
// Playoff tiebreak descriptions (TournamentEngine._resolve_undecided_playoff /
// _build_result_description): a knockout fixture that was genuinely drawn/tied
// still needs a winner, decided by (in order) a tied Super Over -> group-stage
// rank (limited overs), or first-innings lead -> group-stage rank (Test).
// All three produce "Match {tied|drawn} · <team> <reason>" - winner must be
// extracted from all of them, or the personalized win/loss banner would show
// a plain "Match drawn" even to the team that actually advanced.

export interface ParsedMatchResult {
  winner: string | null       // winning team, incl. every tiebreak-decided case below
  soWinner: string | null     // set when the match was decided by a Super Over
  advancedNote: string | null // human-readable "why", when winner exists despite a tie/draw
  margin: string | null       // "20 runs" / "4 wickets" for decisive wins
  isTied: boolean
  isNoResult: boolean
  isDrawn: boolean
}

export function parseMatchResult(desc: string | null | undefined): ParsedMatchResult {
  const soMatch = desc?.match(/^Match tied · (.+) won Super Over$/)
  const soWinner = soMatch ? soMatch[1].trim() : null

  const soTieMatch = desc?.match(/^Match tied · Super Over tied · (.+) advanced due to better group stage finish$/)
  const leadMatch = desc?.match(/^Match (?:tied|drawn) · (.+) advanced on first-innings lead$/)
  const rankMatch = desc?.match(/^Match (?:tied|drawn) · (.+) advanced due to better group stage finish$/)

  let tiebreakWinner: string | null = null
  let advancedNote: string | null = null
  if (soTieMatch) {
    tiebreakWinner = soTieMatch[1].trim()
    advancedNote = 'won a tied Super Over tiebreak on group stage position'
  } else if (leadMatch) {
    tiebreakWinner = leadMatch[1].trim()
    advancedNote = 'advanced on a first-innings lead'
  } else if (rankMatch) {
    tiebreakWinner = rankMatch[1].trim()
    advancedNote = 'advanced on better group stage position'
  }

  const winnerMatch = desc?.match(/^(.+?)\s+won\s+by\s+(.+)$/)
  return {
    soWinner,
    advancedNote,
    winner: soWinner ?? tiebreakWinner ?? (winnerMatch ? winnerMatch[1].trim() : null),
    margin: winnerMatch ? winnerMatch[2].trim() : null,
    isTied: desc === 'Match tied',
    isNoResult: desc === 'No result',
    isDrawn: desc === 'Match drawn',
  }
}
