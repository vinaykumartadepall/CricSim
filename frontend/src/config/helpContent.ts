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
        ],
        tip: 'Number of different challenges played are shown for each tournament/season — try to finish all of them!',
      },
      {
        header: 'Pick a Season',
        instructions: [
          'Select the season you want to simulate',
        ]
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
          'You need to have atleast 1 wicket keeper in your final XI',
          'You can also reorder your batting lineup using arrows to the right of each player\'s slot'
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
          'You need to have atleast 1 wicket keeper in your final XI',
          'You can also reorder your batting lineup using ↑ ↓ arrows'
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
        ],
      },
      {
        header: 'Pick a Season',
        instructions: [
          'Select the season you want to simulate',
        ]
      },
      {
        header: 'Draft Your XI',
        instructions: [
          'Draft 11 players from available player pool',
          'players already in opposition teams are not available',
          'Tap a player to add them — tap × to remove',
          'You need to have atleast 1 wicket keeper in your final XI',
          'Use the ↑ ↓ arrows to reorder your batting lineup',
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
          'Tournament: everyone drafts an XI and teams compete in a full bracket',
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
          'You have 60 seconds per pick before a player is auto-selected',
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
        header: 'Standings',
        instructions: [
          'Full points table for all teams in the tournament',
          'Top 4 teams (marked Q) qualify for the playoffs',
          'NRR (net run rate) breaks ties on points',
        ],
        tip: 'The winner row shows a trophy icon after playoffs complete',
      },
      {
        header: 'Leaderboards',
        instructions: [
          'Four sub-tabs: Most Runs, Most Wickets, Best Economy, and MVP',
          'MVP uses a fantasy points formula covering runs, wickets, boundaries, and economy',
        ],
      },
      {
        header: 'Matches',
        instructions: [
          'Every match is grouped by stage: Group Stage then Playoffs',
          'Click any match row to expand its full scorecard',
        ],
        tip: 'Scorecards show full batting and bowling figures for both innings',
      },
      {
        header: 'Awards',
        instructions: [
          'Player of the Tournament is highlighted at the top',
          'Full breakdown of batting, bowling, and fielding points for every player',
        ],
        tip: 'Fielding points come from catches, run-outs, and stumpings',
      },
    ],
  },

  '/results/matches': {
    title: 'Match Detail',
    slides: [
      {
        header: 'Result Tab',
        instructions: [
          'Shows the winner banner with winning margin',
          'Both teams\' scores are displayed side by side',
          'Man of the Match is shown with actual batting and bowling figures',
        ],
        tip: 'Super Over results are indicated separately if the match was tied',
      },
      {
        header: 'Scorecard',
        instructions: [
          'Full batting card: runs, balls, fours, sixes, strike rate, and dismissal',
          'Full bowling card: overs, runs, wickets, and economy',
          'Both innings are shown for each team',
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

export function findHelpContent(pathname: string): HelpContent | null {
  if (/\/results\/[^/]+\/matches\//.test(pathname)) return HELP_CONTENT['/results/matches'] ?? null
  if (/\/multiplayer\/draft\//.test(pathname))       return HELP_CONTENT['/multiplayer/draft'] ?? null
  if (/\/results\//.test(pathname))                  return HELP_CONTENT['/results'] ?? null

  const keys = Object.keys(HELP_CONTENT).sort((a, b) => b.length - a.length)
  for (const key of keys) {
    if (pathname === key || pathname.startsWith(key + '/')) return HELP_CONTENT[key]
  }
  return null
}
