// ─────────────────────────────────────────────────────────────────────────────
// Help content configuration — edit here to update in-app help text.
//
// Each key is matched against the current URL path (prefix matching, most
// specific wins). Each slide has a header, a list of instructions, and an
// optional tip shown at the bottom.
// ─────────────────────────────────────────────────────────────────────────────

export interface HelpSlide {
  header: string
  instructions: string[]
  tip?: string
}

export interface HelpContent {
  title: string
  slides: HelpSlide[]
}

export const HELP_CONTENT: Record<string, HelpContent> = {
  '/': {
    title: 'Welcome to CricSim',
    slides: [
      {
        header: 'Single Player',
        instructions: [
          'Simulate a full IPL season by yourself',
          'Choose from Fun, Challenge, or Custom mode',
          'Each mode gives you a different level of control over the team',
        ]
      },
      {
        header: 'Multiplayer Draft',
        instructions: [
          'Create a room and invite friends using a code or link',
          'Each player drafts their own XI from the player pool',
          'The best team wins — 1v1 match or a full tournament',
        ]
      },
      {
        header: 'Recent Simulations',
        instructions: [
          'Your last 5 simulations are listed at the bottom of the home screen',
          'Click any row to jump straight back to the results',
          'Click view all to view your full simulation history',
        ]
      },
    ],
  },

  '/play': {
    title: 'Single Player Modes',
    slides: [
      {
        header: 'Fun Mode',
        instructions: [
          'Pick any team from any season',
          'Make up to 3 trades with other team in the tournament',
          'Reorder your batting lineup',
          'Try to win the title by losing no matches',
        ],
        tip: 'A trade can weaken an opposition along with strengthening your team — choose wisely',
      },
      {
        header: 'Challenge Mode',
        instructions: [
          'Take over one of the underdog teams in the history',
          'Trade in better players to strengthen the squad',
          'Aim for the title with minimum trades',
        ],
        tip: 'A trade can weaken an opposition along with strengthening your team — choose wisely',
      },
      {
        header: 'Custom Mode',
        instructions: [
          'Select any season from any tournament',
          'Replace a team in that tournament with your own team',
          'Draft players among the available player pool to create your own XI',
          'Enter the tournament and see how your team performs',
        ]
      },
    ],
  },

  '/fun': {
    title: 'Fun Mode',
    slides: [
      {
        header: 'Pick a Tournament',
        instructions: [
          'Search or scroll to find the tournament you want',
          'Each tournament shows how many seasons are available',
          'Selecting a tournament shows all seasons available for that tournament',
        ],
        tip: 'Number of different challenges played are shown for each tournament/season — try to finish all of them!',
      },
      {
        header: 'Pick a Team',
        instructions: [
          'Pick a team you want to manage',
          'Select no preference if you just want to simulate the tournament without managing any team',
        ],
        tip: 'Your best best finish with each team is shown on the card',
      },
      {
        header: 'Edit Your Squad',
        instructions: [
          'Your selected team\'s players are listed',
          'Click TRADE on a player to replace them with someone from another team',
          'Trade out weak players and bring in stronger ones from other teams',
          'You can trade up to 3 players, limited to 1 player from each opposing team - choose wisely',
          'You cannot trade a batter for a bowler or vice versa — roles must match',
          'Click reorder lineup to change the batting order of your team',
        ],
        tip: 'Try to make it a perfect season with no losses!',
      },
    ],
  },

  '/challenge': {
    title: 'Challenge Mode',
    slides: [
      {
        header: 'Pick a Tournament',
        instructions: [
          'Search or scroll to find the tournament you want',
          'Each tournament shows how many seasons are available',
        ],
        tip: 'Number of different challenges played are shown for each tournament/season — try to finish all of them!',
      },
      {
        header: 'Pick an Underdog',
        instructions: [
          'Teams are listed weakest first, by win percentage in that season',
          'Select a team from a season to take over',
        ],
        tip: 'Your best best finish with each team is shown on the card',
      },
      {
        header: 'Strengthen Your Squad',
        instructions: [
          'Your selected team\'s players are listed',
          'Click TRADE on a player to replace them with someone from another team',
          'Trade out weak players and bring in stronger ones from other teams',
          'No limit on number of trades, but you can only trade 1 player from each team',
          'You cannot trade a batter for a bowler or vice versa — roles must match',
          'Click reorder lineup to change the batting order of your team'
        ],
        tip: 'Try to win the title with minimum trades!',
      },
    ],
  },

  '/custom': {
    title: 'Custom Mode',
    slides: [
      {
        header: 'Pick a Tournament',
        instructions: [
          'Search or scroll to find the tournament you want',
          'Each tournament shows how many seasons are available',
          'Selecting a tournament shows all seasons available for that tournament',
        ],
      },
      {
        header: 'Draft Your XI',
        instructions: [
          'Draft 11 players from available player pool',
          'Players already in opposition teams are not available',
          'Tap a player to add them — tap × to remove',
          'Click reorder lineup to change the batting order of your team',
        ]
      }
    ],
  },

  '/multiplayer': {
    title: 'Multiplayer Draft',
    slides: [
      {
        header: 'Create or Join a Room',
        instructions: [
          'Create a room and share the code or invite link with friends',
          'Friends join by entering the room code or clicking the link',
          'Set the format (1v1 or Tournament) and player count when creating',
        ],
      },
      {
        header: '1v1 vs Tournament',
        instructions: [
          '1v1: two players each draft an XI, then play a single match',
          'Tournament: everyone drafts an XI and teams compete in a full tournament',
        ]
      },
      {
        header: 'Starting the Draft',
        instructions: [
          'Wait for all players to join the room',
          'The host clicks "Start Draft" to begin',
          'Once started, picks happen in snake order',
        ],
      },
    ],
  },

  '/multiplayer/draft': {
    title: 'Draft Room',
    slides: [
      {
        header: 'Pick Order',
        instructions: [
          'Picks go in snake order: P1, P2, … then back in reverse',
          'You have 60 seconds per pick before a random player is auto-selected',
        ],
        tip: 'Watch the notification banner — it shows every pick as it happens',
      },
      {
        header: 'Picking a Player',
        instructions: [
          'When it\'s your turn, the "Pick a Player" button lights up',
          'Search by name or filter by keeper to find the right player',
          'Drafted players show which team picked them',
        ],
        tip: 'You must include a wicket-keeper before your last selection',
      },
      {
        header: 'Reorder Phase',
        instructions: [
          'After all 11 picks, you get 60 seconds to set your batting order',
          'Use ↑ ↓ arrows to reorder. Click "I\'m Ready" to lock in early',
        ],
        tip: 'Simulation starts when all players are ready or the timer runs out',
      },
    ],
  },

  '/results': {
    title: 'Your Results',
    slides: [
      {
        header: 'Overview',
        instructions: [
          "View the full points table of the tournament simulation",
          "View playoffs bracket in a separate tab",
          "Player of the tournament is displayed at the top of the overview tab",
        ],
      },
      {
        header: 'Leaderboards',
        instructions: [
          'Multiple leaderboards are available for each tournament',
          'Click on any leaderboard to view the full list of players and the detailed stats or search by player name',
        ],
      },
      {
        header: 'Matches',
        instructions: [
          'View all matches in the tournament, filter only your team\'s matches with the \'My Matches\' toggle',
          'Click any match to view complete match details like scorecard and ball by ball commentary',
        ]
      }
    ],
  },

  '/results/matches': {
    title: 'Match Detail',
    slides: [
      {
        header: 'Result Tab',
        instructions: [
          'Summary of the match result, including player of the match and innings progression graph',
        ],
      },
      {
        header: 'Scorecard',
        instructions: [
          'Full detailed scorecard of the match, including batting and bowling stats for both teams',
        ],
      },
      {
        header: 'Commentary',
        instructions: [
          'Ball-by-ball text description of every delivery',
          'Scroll through to relive key moments of the match',
        ],
        tip: 'Wickets and boundaries are highlighted in the commentary feed',
      },
    ],
  },
}

// ─────────────────────────────────────────────────────────────────────────────
// Path matching helper — exported for use in HelpModal
// ─────────────────────────────────────────────────────────────────────────────

export interface MatchedHelp {
  key: string
  content: HelpContent
}

// Returns both the resolved content AND the canonical key it matched under
// (e.g. '/results', not the raw '/results/<simId>') — callers that track
// "has this been seen before" (HelpModal) must key off this canonical form,
// since the raw pathname is different for every simulation/match id and would
// never repeat, defeating the "first visit only" check entirely.
export function findMatchedHelp(pathname: string): MatchedHelp | null {
  if (/\/results\/[^/]+\/matches\//.test(pathname)) {
    const content = HELP_CONTENT['/results/matches']
    return content ? { key: '/results/matches', content } : null
  }
  if (/\/multiplayer\/draft\//.test(pathname)) {
    const content = HELP_CONTENT['/multiplayer/draft']
    return content ? { key: '/multiplayer/draft', content } : null
  }
  if (/\/results\//.test(pathname)) {
    const content = HELP_CONTENT['/results']
    return content ? { key: '/results', content } : null
  }

  const keys = Object.keys(HELP_CONTENT).sort((a, b) => b.length - a.length)
  for (const key of keys) {
    if (pathname === key || pathname.startsWith(key + '/')) return { key, content: HELP_CONTENT[key] }
  }
  return null
}

// ─────────────────────────────────────────────────────────────────────────────
// "Seen" tracking — shared by HelpModal's generic auto-open AND the step-based
// pages (Fun/Challenge/Custom mode) that call openHelp() directly per step.
// Always key off a stable identifier (canonical content key, or `${path}#${step}`
// for step-based pages) — never the raw pathname when it can contain a dynamic
// id, or "first time only" silently turns into "every time".
// ─────────────────────────────────────────────────────────────────────────────

export function hasSeenHelp(key: string): boolean {
  return !!localStorage.getItem(`cricsim_help_seen_${key}`)
}

export function markHelpSeen(key: string): void {
  localStorage.setItem(`cricsim_help_seen_${key}`, '1')
}
