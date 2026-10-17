import type { SimSummary, Tournament, TournamentSquads, TournamentResult, LeaderboardsDashboard, MatchItem, Scorecard, SwapEntry, SimHistoryNameCount, SimHistorySeasonCount, SimHistoryTeamBest, ChallengeLeaderboardResponse, MyTeamRankItem, MultiplayerPlayer, PlayerSearchFilters, PlayerFilterOptions, RoomResponse, RoomState, CreateRoomBody, JoinRoomBody, PublicRoomSummary, VenueSearchResult, VenueCountry, AdminSettings, AdminCacheStrategyResponse, AdminSimulationDefaultsResponse, LeaderboardsEnabledResponse, AdminSimListResponse, AdminTournamentSummary, AdminTournamentDetail, AdminPlayer, Country, Commentary } from '@/types'
import { supabase } from '@/lib/supabase'
import { getClientId, getClientSecret, resetAnonymousIdentity } from '@/api/clientId'

const BASE = '/cricsimapi'

/**
 * Identity for every request (api/identity_auth.py): the Supabase JWT when
 * signed in, plus this browser's client_id + secret. The server trusts only
 * these - a client_id in a URL or body proves nothing.
 */
async function identityHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    'X-Client-Id': getClientId(),
    'X-Client-Secret': await getClientSecret(),
  }
  if (supabase) {
    const { data: { session } } = await supabase.auth.getSession()
    if (session?.access_token) headers.Authorization = `Bearer ${session.access_token}`
  }
  return headers
}

/** Same proofs for the room WebSocket, sent as its first message (browsers
 *  can't put headers on a WebSocket, and a URL would end up in access logs). */
export async function wsAuthMessage(): Promise<Record<string, string>> {
  if (supabase) {
    const { data: { session } } = await supabase.auth.getSession()
    if (session?.access_token) return { type: 'auth', token: session.access_token }
  }
  return { type: 'auth', client_id: getClientId(), secret: await getClientSecret() }
}

async function signedIn(): Promise<boolean> {
  if (!supabase) return false
  const { data: { session } } = await supabase.auth.getSession()
  return !!session
}

/** The server rejected this browser's anonymous identity for good: it belongs
 *  to a signed-in account (and we're signed out), or its secret doesn't match.
 *  Start a fresh anonymous identity rather than failing every request. */
async function recoverIdentity(res: Response): Promise<void> {
  const reason = res.headers.get('X-Identity-Error')
  if (reason === 'credential_mismatch' || (reason === 'identity_linked' && !(await signedIn()))) {
    resetAnonymousIdentity()
  }
}

async function send(path: string, method: string, body?: unknown): Promise<Response> {
  const headers = await identityHeaders()
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(`${BASE}${path}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) await recoverIdentity(res)
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || `${res.status} ${res.statusText}`)
  }
  return res
}

const get = async <T>(path: string): Promise<T> => (await send(path, 'GET')).json()
const post = async <T>(path: string, body: unknown): Promise<T> => (await send(path, 'POST', body)).json()
const put = async <T>(path: string, body: unknown): Promise<T> => (await send(path, 'PUT', body)).json()
// No response body (204) - identity/sync-anonymous is fire-and-forget.
const postNoContent = async (path: string, body: unknown): Promise<void> => { await send(path, 'POST', body) }
// Admin and account endpoints - identical now that every request carries the
// JWT; kept as names so call sites still read as "needs sign-in".
const authGet = get
const authPost = post
const authPut = put

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


  getLineups: (simId: string) =>
    get<{ sim_id: string; teams: { team_name: string; players: { player_id: number; player_name: string; player_role: string | null; headshot_url: string | null; matches: number; runs: number; wickets: number; mvp_points: number; batting_pts: number; bowling_pts: number; fielding_pts: number }[] }[] }>(
      `/simulations/${simId}/lineups`
    ),

  getLeaderboardPage: (simId: string, type: string, limit = 50, offset = 0) =>
    get<{ entries: unknown[]; total: number }>(`/simulations/${simId}/leaderboards/${type}?limit=${limit}&offset=${offset}`),

  listSimulations: (clientId: string, limit = 5, offset = 0) =>
    get<SimSummary[]>(`/simulations?client_id=${encodeURIComponent(clientId)}&limit=${limit}&offset=${offset}`),

  getTotalSimulations: () =>
    get<{ total: number }>('/simulations/total'),

  getSimHistoryNameCounts: (clientId: string, mode?: string, nameQuery?: string) => {
    const params = new URLSearchParams({ client_id: clientId })
    if (mode) params.set('mode', mode)
    if (nameQuery) params.set('name_query', nameQuery)
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

  getChallengeLeaderboard: (
    clientId: string, tournamentId: number, teamName: string, mode: string,
    limit = 10, offset = 0,
  ) => {
    const params = new URLSearchParams({
      client_id: clientId, tournament_id: String(tournamentId), team_name: teamName, mode,
      limit: String(limit), offset: String(offset),
    })
    return get<ChallengeLeaderboardResponse>(`/sim-history/leaderboard?${params}`)
  },

  getMyChallengeRanks: (clientId: string, tournamentId: number, mode: string) => {
    const params = new URLSearchParams({ client_id: clientId, tournament_id: String(tournamentId), mode })
    return get<MyTeamRankItem[]>(`/sim-history/my-ranks?${params}`)
  },

  getLeaderboardsEnabled: () =>
    get<LeaderboardsEnabledResponse>('/sim-history/leaderboards-enabled'),

  // ── Identity endpoints (simulation.identity_links) ─────────────────────────

  syncAnonymousIdentity: (client_id: string, username: string) =>
    postNoContent('/identity/sync-anonymous', { client_id, username }),

  // Requires a Supabase JWT - called once per sign-in; the server resolves
  // the auth id from the token itself, not from the body.
  linkIdentity: (client_id: string, fallback_username: string) =>
    authPost<{ canonical_id: string; username: string }>('/identity/link', {
      client_id, fallback_username,
    }),

  setUsername: (client_id: string, username: string) =>
    put<{ canonical_id: string; username: string }>('/identity/username', { client_id, username }),

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

  getActiveHostedRoomCount: (clientId: string) =>
    get<{ count: number; limit: number }>(`/multiplayer/rooms/active-count?client_id=${encodeURIComponent(clientId)}`),

  joinRoom: (roomId: string, body: JoinRoomBody) =>
    post<RoomState>(`/multiplayer/rooms/${roomId}/join`, body),


  searchMultiplayerVenues: (q: string, limit = 10) =>
    get<VenueSearchResult[]>(`/multiplayer/venues/search?q=${encodeURIComponent(q)}&limit=${limit}`),

  getMultiplayerCountries: () =>
    get<VenueCountry[]>('/multiplayer/countries'),

  getPublicRooms: (filters: { mode?: string[]; matchFormat?: string[] } = {}) => {
    const params = new URLSearchParams()
    filters.mode?.forEach(m => params.append('mode', m))
    filters.matchFormat?.forEach(f => params.append('match_format', f))
    return get<PublicRoomSummary[]>(`/multiplayer/rooms/public?${params.toString()}`)
  },

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

  setLeaderboardsEnabled: (enabled: boolean) =>
    authPut<LeaderboardsEnabledResponse>('/admin/leaderboards-enabled', { enabled }),

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
