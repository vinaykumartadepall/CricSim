import type { SimSummary, Tournament, TournamentSquads, TournamentResult, LeaderboardsDashboard, MatchItem, Scorecard, SwapEntry, SimHistoryNameCount, SimHistorySeasonCount, SimHistoryTeamBest, MultiplayerPlayer, PlayerSearchFilters, PlayerFilterOptions, RoomResponse, RoomState, CreateRoomBody, JoinRoomBody, AdminSettings, AdminCacheStrategyResponse, AdminSimulationDefaultsResponse, AdminSimListResponse, AdminTournamentSummary, AdminTournamentDetail, AdminPlayer, Country, Commentary } from '@/types'
import { supabase } from '@/lib/supabase'

const BASE = '/cricsimapi'

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {}
  const { data: { session } } = await supabase.auth.getSession()
  if (session?.access_token) return { Authorization: `Bearer ${session.access_token}` }
  return {}
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function authGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: await authHeaders() })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

async function authPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

async function authPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  getTournaments: (q?: string) =>
    get<Tournament[]>(`/lov/tournaments${q ? `?q=${encodeURIComponent(q)}` : ''}`),

  getTournamentSquads: (tournamentId: number) =>
    get<TournamentSquads>(`/lov/tournaments/${tournamentId}/squads`),

  getUnderdogs: (tournamentName: string) =>
    get<{ team_id: number; team_name: string; tournament_id: number; season: string; wins: number; total_matches: number; win_pct: number }[]>(
      `/lov/underdogs?tournament_name=${encodeURIComponent(tournamentName)}`
    ),

  startTournamentSim: (body: {
    tournament_id: number
    team_id?: number | null
    mode: string
    client_id: string
    swaps?: { player_out_id: number; player_in_id: number; from_team_id: number }[]
    batting_order?: number[]
  }) => post<{ sim_id: string; status: string }>('/simulations/tournament', body),

  getSimStatus: (simId: string) =>
    get<{
      sim_id: string; status: string; error?: string
      simulation_type?: string; match_id?: number
      matches_completed?: number; matches_total?: number
      teams?: number; total_deliveries?: number
      results?: { label: string; text: string; home: string; away: string }[]
      queue_position?: number | null
    }>(`/simulations/${simId}/status`),

  getSimResult: (simId: string, clientId?: string) => {
    const qs = clientId ? `?client_id=${encodeURIComponent(clientId)}` : ''
    return get<TournamentResult>(`/simulations/${simId}/result${qs}`)
  },

  getLeaderboards: (simId: string) =>
    get<LeaderboardsDashboard>(`/simulations/${simId}/leaderboards`),

  getMatches: (simId: string) =>
    get<MatchItem[]>(`/simulations/${simId}/matches`),

  getSimScorecard: (simId: string, clientId?: string) => {
    const qs = clientId ? `?client_id=${encodeURIComponent(clientId)}` : ''
    return get<Scorecard>(`/simulations/${simId}/scorecard${qs}`)
  },

  getMatchScorecard: (simId: string, matchId: number, clientId?: string) => {
    const qs = clientId ? `?client_id=${encodeURIComponent(clientId)}` : ''
    return get<Scorecard>(`/simulations/${simId}/matches/${matchId}/scorecard${qs}`)
  },

  getSimCommentary: (simId: string) =>
    get<Commentary>(
      `/simulations/${simId}/commentary`
    ),

  getMatchCommentary: (simId: string, matchId: number) =>
    get<Commentary>(
      `/simulations/${simId}/matches/${matchId}/commentary`
    ),

  getAwards: (simId: string) =>
    get<{ sim_id: string; awards: { player_name: string; team_name: string; batting_pts: number; bowling_pts: number; fielding_pts: number; total_pts: number }[] }>(
      `/simulations/${simId}/awards`
    ),

  getLineups: (simId: string) =>
    get<{ sim_id: string; teams: { team_name: string; players: { player_id: number; player_name: string; player_role: string | null; matches: number; runs: number; wickets: number; mvp_points: number; batting_pts: number; bowling_pts: number; fielding_pts: number }[] }[] }>(
      `/simulations/${simId}/lineups`
    ),

  getLeaderboardPage: (simId: string, type: string, limit = 50, offset = 0) =>
    get<{ entries: unknown[]; total: number }>(`/simulations/${simId}/leaderboards/${type}?limit=${limit}&offset=${offset}`),

  listSimulations: (clientId: string, limit = 5, offset = 0) =>
    get<SimSummary[]>(`/simulations?client_id=${encodeURIComponent(clientId)}&limit=${limit}&offset=${offset}`),

  getTotalSimulations: () =>
    get<{ total: number }>('/simulations/total'),

  getSimHistoryNameCounts: (clientId: string, mode?: string) => {
    const params = new URLSearchParams({ client_id: clientId })
    if (mode) params.set('mode', mode)
    return get<SimHistoryNameCount[]>(`/sim-history/counts?${params}`)
  },

  getSimHistorySeasonCounts: (clientId: string, tournamentIds: number[], mode?: string) => {
    const params = new URLSearchParams({ client_id: clientId, tournament_ids: tournamentIds.join(',') })
    if (mode) params.set('mode', mode)
    return get<SimHistorySeasonCount[]>(`/sim-history/counts?${params}`)
  },

  getSimHistoryBest: (clientId: string, tournamentId: number, mode?: string) => {
    const params = new URLSearchParams({ client_id: clientId, tournament_id: String(tournamentId) })
    if (mode) params.set('mode', mode)
    return get<SimHistoryTeamBest[]>(`/sim-history/best?${params}`)
  },

  // ── Auth endpoints (require Supabase JWT) ──────────────────────────────────

  getAuthProfile: () =>
    authGet<{ user_id: string; display_name: string }>('/auth/profile'),

  upsertAuthProfile: (display_name: string) =>
    authPost<{ user_id: string; display_name: string }>('/auth/profile', { display_name }),

  linkAnonymous: (anonymous_id: string) =>
    authPost<{ migrated: number }>('/auth/link-anonymous', { anonymous_id }),

  // ── Multiplayer endpoints ──────────────────────────────────────────────────

  searchPlayers: (q: string, filters: PlayerSearchFilters = {}) => {
    const params = new URLSearchParams({ q })
    filters.roles?.forEach(r => params.append('role', r))
    filters.countryIds?.forEach(id => params.append('country_id', String(id)))
    filters.battingStyles?.forEach(b => params.append('batting_style', b))
    filters.bowlingStyles?.forEach(b => params.append('bowling_style', b))
    return get<MultiplayerPlayer[]>(`/multiplayer/players?${params.toString()}`)
  },

  getPlayerFilters: () =>
    get<PlayerFilterOptions>('/multiplayer/player-filters'),

  createRoom: (body: CreateRoomBody) =>
    post<RoomResponse>('/multiplayer/rooms', body),

  joinRoom: (roomId: string, body: JoinRoomBody) =>
    post<RoomState>(`/multiplayer/rooms/${roomId}/join`, body),

  getRoom: (roomId: string) =>
    get<RoomState>(`/multiplayer/rooms/${roomId}`),

  // ── Admin endpoints (ops-only page, not linked from main nav) ───────────────
  // Require a Supabase JWT belonging to a user in the backend's ADMIN_USER_IDS.

  getAdminSettings: () =>
    authGet<AdminSettings>('/admin/settings'),

  setLogLevel: (level: string) =>
    authPut<{ level: string }>('/admin/log-level', { level }),

  setCacheStrategy: (strategy: string) =>
    authPut<AdminCacheStrategyResponse>('/admin/cache-strategy', { strategy }),

  setSimulationDefaults: (body: { outcome_strategy?: string; bowling_strategy?: string }) =>
    authPut<AdminSimulationDefaultsResponse>('/admin/simulation-defaults', body),

  getAdminSimulations: (limit = 50, offset = 0) =>
    authGet<AdminSimListResponse>(`/admin/data/simulations?limit=${limit}&offset=${offset}`),

  getAdminTournaments: (q?: string) =>
    authGet<AdminTournamentSummary[]>(`/admin/data/tournaments${q ? `?q=${encodeURIComponent(q)}` : ''}`),

  getAdminTournamentDetail: (tournamentId: number) =>
    authGet<AdminTournamentDetail>(`/admin/data/tournaments/${tournamentId}`),

  putAdminTournamentMeta: (tournamentId: number, body: { tournament_name?: string; format?: string; gender?: string }) =>
    authPut<{ updated: Record<string, string> }>(`/admin/data/tournaments/${tournamentId}/meta`, body),

  putAdminTeamMeta: (tournamentId: number, teamId: number, body: {
    name?: string; short_name?: string; primary_color?: string; secondary_color?: string
    home_venue?: string; clear_home_venue?: boolean
  }) =>
    authPut<{ updated: Record<string, string> }>(`/admin/data/tournaments/${tournamentId}/teams/${teamId}/meta`, body),

  putAdminVenues: (tournamentId: number, venues: { name: string; city?: string; previous_name?: string }[]) =>
    authPut<{ venues: number }>(`/admin/data/tournaments/${tournamentId}/venues`, { venues }),

  putAdminSchedule: (tournamentId: number, body: { schedule?: Record<string, unknown>; playoffs?: Record<string, unknown> }) =>
    authPut<{ updated: boolean }>(`/admin/data/tournaments/${tournamentId}/schedule`, body),

  putAdminSquad: (tournamentId: number, teamId: number, players: { player_id: number; batting_position: number }[]) =>
    authPut<{ updated: number }>(`/admin/squads/tournaments/${tournamentId}/teams/${teamId}`, { players }),

  searchAdminPlayers: (q: string, limit = 30) =>
    authGet<AdminPlayer[]>(`/admin/data/players?q=${encodeURIComponent(q)}&limit=${limit}`),

  putAdminPlayer: (playerId: number, body: Partial<Omit<AdminPlayer, 'player_id' | 'country_name' | 'headshot_url' | 'matches_played'>>) =>
    authPut<{ updated: Record<string, unknown> }>(`/admin/data/players/${playerId}`, body),

  getAdminCountries: () =>
    authGet<Country[]>('/admin/data/countries'),

  searchAdminVenues: (q: string, limit = 10) =>
    authGet<{ name: string; city: string | null; country: string | null; matches: number }[]>(
      `/admin/data/venues?q=${encodeURIComponent(q)}&limit=${limit}`),
}

export type { SwapEntry }
