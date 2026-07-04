export interface Tournament {
  tournament_id: number
  name: string
  season: string
  team_count: number
  gender: string
  format?: string | null
  overseas_limit?: number | null
  home_country_name?: string | null
}

export interface Player {
  player_id: number
  player_name: string
  player_role: string | null
  batting_style: string | null
  bowling_style: string | null
  batting_position?: number | null
  cricinfo_id: number | null
  headshot_url: string | null
  country_name?: string | null
}

export interface Team {
  team_id: number
  team_name: string
  short_name?: string | null
  players: Player[]
}

export interface TournamentSquads {
  tournament_id: number
  teams: Team[]
}

export interface SimHistoryNameCount {
  name: string
  tournament_ids: number[]
  total: number
  completed: number
}

export interface SimHistorySeasonCount {
  tournament_id: number
  total: number
  completed: number
}

export interface SimHistoryTeamBest {
  team_name: string
  best_placement: string
  swap_count: number
  sim_id: string
}

export type SimMode = 'fun' | 'challenge'
export type Theme = 'ember-amber' | 'ember-emerald' | 'ember-crimson' | 'ember-ice'

export interface SwapEntry {
  player_out_id: number
  player_in_id: number
  from_team_id: number
  // display only
  player_out_name: string
  player_in_name: string
}

export interface SimSummary {
  sim_id: string
  simulation_type: string
  status: string
  created_at: string
  mode?: string | null
  tournament_name?: string | null
  season?: string | null
  user_team_name?: string | null
  swap_count?: number | null
  winner_name?: string | null
  user_team_placement?: string | null
  match_id?: number | null
  match_format?: string | null
}

export interface PointsTableRow {
  team: string
  played: number
  won: number
  lost: number
  tied: number
  no_result: number
  points: number
  nrr: number
}

export interface TournamentResult {
  sim_id: string
  status: string
  tournament_name: string | null
  season: string | null
  winner: string | null
  runner_up: string | null
  total_matches: number
  points_table: PointsTableRow[]
  user_team_name?: string | null
  user_team_placement?: string | null
  mode?: string | null
  source_tournament_id?: number | null
  user_team_id?: number | null
}

export interface BattingRow {
  rank: number
  player: string
  team: string
  matches: number
  innings: number
  runs: number
  average: number | null
  strike_rate: number | null
  highest_score: number
  fifties: number
  hundreds: number
  fours: number
  sixes: number
  not_outs: number
}

export interface BowlingRow {
  rank: number
  player: string
  team: string
  matches: number
  innings: number
  overs: string
  runs: number
  wickets: number
  economy: number | null
  average: number | null
  strike_rate: number | null
  dots: number
  best_bowling: string
  four_wicket_hauls: number
  five_wicket_hauls: number
}

export interface MvpRow {
  rank: number
  player: string
  team: string
  batting_pts: number
  bowling_pts: number
  fielding_pts: number
  total: number
}

export interface LeaderboardsDashboard {
  sim_id: string
  most_runs: BattingRow[]
  highest_score: unknown[]
  best_batting_average: BattingRow[]
  best_strike_rate: BattingRow[]
  most_sixes: BattingRow[]
  most_fours: BattingRow[]
  most_wickets: BowlingRow[]
  best_bowling_average: BowlingRow[]
  best_economy: BowlingRow[]
  best_bowling_figures: unknown[]
  most_dots: BowlingRow[]
  mvp: MvpRow[]
}

export interface InningsScore {
  runs: number
  wkts: number
}

export interface MatchItem {
  match_id: number
  match_label: string
  home_team: string
  away_team: string
  winner: string | null
  result: string | null
  win_type: string | null
  win_by: number | null
  is_super_over: boolean
  venue?: string | null
  venue_country?: string | null
  match_format?: string | null
  home_score: number | null
  home_wickets: number | null
  home_overs: string | null
  home_innings?: InningsScore[] | null
  away_score: number | null
  away_wickets: number | null
  away_overs: string | null
  away_innings?: InningsScore[] | null
}

export interface BatterRow {
  name: string
  runs: number
  balls: number
  fours: number
  sixes: number
  strike_rate: number
  dismissal: string | null
  headshot_url?: string | null
}

export interface BowlerRow {
  name: string
  overs: string
  runs: number
  wickets: number
  economy?: number
  dot_balls?: number
}

export interface Innings {
  inning_number: number
  batting_team: string
  bowling_team: string
  total_runs: number
  total_wickets: number
  overs: string
  extras: number
  extras_wides: number
  extras_nb: number
  extras_lb: number
  extras_byes: number
  batters: BatterRow[]
  bowlers: BowlerRow[]
}

export interface Scorecard {
  match_id: number
  match_label: string
  home_team: string
  away_team: string
  venue: string | null
  venue_country?: string | null
  match_format: string | null
  result_description: string | null
  innings: Innings[]
}

export interface AwardEntry {
  player_name: string
  team_name: string
  batting_pts: number
  bowling_pts: number
  fielding_pts: number
  total_pts: number
}

// ── Multiplayer types ─────────────────────────────────────────────────────────

export interface MultiplayerPlayer {
  player_id: number
  name: string
  role: string
  batting_style: string | null
  bowling_style: string | null
  headshot_url: string | null
  is_keeper: boolean
}

export interface RoomMember {
  client_id: string
  display_name: string
  team_name: string
  draft_order: number
  squad: number[]
  connected: boolean
}

export interface RoomState {
  room_id: string
  host_id?: string
  mode: '1v1' | 'tournament'
  tournament_name: string
  player_count: number
  match_format: string
  status: 'waiting' | 'drafting' | 'reordering' | 'simulating' | 'completed'
  current_picker: string | null
  picks_made: number
  total_picks: number
  members: RoomMember[]
}

export interface CreateRoomBody {
  client_id: string
  display_name: string
  team_name?: string
  mode: '1v1' | 'tournament'
  tournament_name: string
  player_count: number
  match_format: string
}

export interface JoinRoomBody {
  client_id: string
  display_name: string
  team_name?: string
}

export interface RoomResponse extends RoomState {
  room_id: string
  tournament_name: string
}

export interface AdminSettings {
  log_level: string
  cache_strategy: string
  available_cache_strategies: string[]
  outcome_strategy: string
  bowling_strategy: string
  available_outcome_strategies: string[]
  available_bowling_strategies: string[]
}

export interface AdminCacheStrategyResponse {
  strategy: string
  available: string[]
}

export interface AdminSimulationDefaultsResponse {
  outcome_strategy: string
  bowling_strategy: string
  available_outcome_strategies: string[]
  available_bowling_strategies: string[]
}
