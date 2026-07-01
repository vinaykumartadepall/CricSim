import type { SimSummary, Tournament, TournamentSquads, TournamentResult, LeaderboardsDashboard, MatchItem, Scorecard, SwapEntry, SimHistoryNameCount, SimHistorySeasonCount, SimHistoryTeamBest, MultiplayerPlayer, RoomResponse, RoomState, CreateRoomBody, JoinRoomBody } from '@/types'
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

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
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
    get<{ sim_id: string; status: string; error?: string }>(`/simulations/${simId}/status`),

  getSimResult: (simId: string, clientId?: string) => {
    const qs = clientId ? `?client_id=${encodeURIComponent(clientId)}` : ''
    return get<TournamentResult>(`/simulations/${simId}/result${qs}`)
  },

  getLeaderboards: (simId: string) =>
    get<LeaderboardsDashboard>(`/simulations/${simId}/leaderboards`),

  getMatches: (simId: string) =>
    get<MatchItem[]>(`/simulations/${simId}/matches`),

  getSimScorecard: (simId: string) =>
    get<Scorecard>(`/simulations/${simId}/scorecard`),

  getMatchScorecard: (simId: string, matchId: number) =>
    get<Scorecard>(`/simulations/${simId}/matches/${matchId}/scorecard`),

  getSimCommentary: (simId: string) =>
    get<{ innings: { team: string; balls: { over: number; ball: number; text: string }[] }[] }>(
      `/simulations/${simId}/commentary`
    ),

  getMatchCommentary: (simId: string, matchId: number) =>
    get<{ innings: { team: string; balls: { over: number; ball: number; text: string }[] }[] }>(
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

  searchPlayers: (q: string, keeperOnly?: boolean) =>
    get<MultiplayerPlayer[]>(`/multiplayer/players?q=${encodeURIComponent(q)}${keeperOnly ? '&keeper_only=true' : ''}`),

  createRoom: (body: CreateRoomBody) =>
    post<RoomResponse>('/multiplayer/rooms', body),

  joinRoom: (roomId: string, body: JoinRoomBody) =>
    post<RoomState>(`/multiplayer/rooms/${roomId}/join`, body),

  getRoom: (roomId: string) =>
    get<RoomState>(`/multiplayer/rooms/${roomId}`),
}

export type { SwapEntry }
