import { useEffect, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { ChevronLeft, ChevronDown, ChevronUp } from 'lucide-react'
import { Spinner } from '@/components/ui/Spinner'
import { api } from '@/api/client'
import type { Scorecard, Innings } from '@/types'

type Tab = 'result' | 'scorecard' | 'commentary'

interface DeliveryItem {
  inning_number: number
  over_ball: string
  bowler: string
  batter: string
  non_striker: string
  runs_batter: number
  runs_extras: number
  outcome_type: string
  outcome_kind: string | null
  is_wicket: boolean
  is_free_hit: boolean
  commentary_text: string
}

interface Commentary {
  match_id: number
  match_label: string
  match_format: string | null
  overs_per_innings: number | null
  deliveries: DeliveryItem[]
}

// ── Player avatar (initials fallback — scorecard has no headshot_url) ────────

function PlayerAvatar({ name, url, size = 40 }: { name: string; url?: string | null; size?: number }) {
  const [imgError, setImgError] = useState(false)
  const initials = name.split(' ').filter(Boolean).map(w => w[0]).slice(0, 2).join('').toUpperCase()
  const COLORS = ['#0EA5E9', '#F97316', '#22C55E', '#F59E0B', '#8B5CF6', '#EF4444', '#EC4899', '#14B8A6']
  const color = COLORS[name.charCodeAt(0) % COLORS.length]
  if (url && !imgError) {
    return (
      <img
        src={url} alt={name}
        onError={() => setImgError(true)}
        style={{ width: size, height: size, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }}
      />
    )
  }
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: `${color}1A`, color, border: `1.5px solid ${color}55`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: Math.round(size * 0.36), fontWeight: 700, flexShrink: 0, letterSpacing: '-0.5px',
    }}>
      {initials}
    </div>
  )
}

// ── Per-innings display context (no hardcoded inning numbers in card) ─────────

interface InningsCtx {
  isChase: boolean
  target: number | null        // runs target for chasing innings
  leadOffset: number | null    // Test: lead = cumScore + leadOffset (+ means curr team leads)
  leadTeamWhenPositive: string
  leadTeamWhenNegative: string
  finalBanner: string | null
  isSuperOverInnings: boolean
  isOnlyOneOver: boolean       // super over — skip "in Y balls"
  ovPerInnings: number | null  // effective overs (derived from format, not stored value)
}

// ── Ball symbol ───────────────────────────────────────────────────────────────

function ballSymbol(d: DeliveryItem): string {
  if (d.is_wicket) return 'W'
  const kind = d.outcome_kind?.toLowerCase() ?? ''
  if (kind === 'wide') {
    const total = d.runs_batter + d.runs_extras
    return total <= 1 ? 'Wd' : `${total}Wd`
  }
  if (kind === 'noball') return 'Nb'
  if (d.runs_batter === 6) return '6'
  if (d.runs_batter === 4) return '4'
  const total = d.runs_batter + d.runs_extras
  return total === 0 ? '•' : String(total)
}

function ballColor(sym: string): string {
  if (sym === 'W')               return 'var(--loss)'
  if (sym === '6')               return 'var(--score)'
  if (sym === '4')               return 'var(--accent)'
  if (sym.endsWith('Wd') || sym === 'Nb') return 'var(--text-dim)'
  if (sym === '•')               return 'var(--text-dim)'
  return 'var(--text-muted)'
}

// ── Per-over snapshot ─────────────────────────────────────────────────────────

interface BatterStat { name: string; runs: number; balls: number }
interface BowlerStat { name: string; overs: string; maidens: number; runs: number; wickets: number }
interface OverSnapshot {
  overNum: number
  balls: DeliveryItem[]
  cumulativeScore: { runs: number; wickets: number }
  overRuns: number
  overWkts: number
  striker: BatterStat | null
  nonStriker: BatterStat | null
  bowler: BowlerStat | null
}

function computeSnapshots(delivs: DeliveryItem[]): OverSnapshot[] {
  const byOver: Record<number, DeliveryItem[]> = {}
  for (const d of delivs) {
    const ov = parseInt(d.over_ball.split('.')[0], 10)
    ;(byOver[ov] ??= []).push(d)
  }

  const batterRuns    = new Map<string, number>()
  const batterBalls   = new Map<string, number>()
  const bowlerRuns    = new Map<string, number>()
  const bowlerWkts    = new Map<string, number>()
  const bowlerLegal   = new Map<string, number>()
  const bowlerMaidens = new Map<string, number>()
  let cumRuns = 0, cumWkts = 0
  const snapshots: OverSnapshot[] = []

  for (const ov of Object.keys(byOver).map(Number).sort((a, b) => a - b)) {
    const balls = byOver[ov]
    let overRunsAcc = 0, overLegal = 0, overBowler = ''

    for (const d of balls) {
      const kind    = d.outcome_kind?.toLowerCase() ?? ''
      const isWide  = kind === 'wide'
      const isNoball = kind === 'noball'
      const ballRuns = d.runs_batter + d.runs_extras

      if (!isWide) batterBalls.set(d.batter, (batterBalls.get(d.batter) ?? 0) + 1)
      batterRuns.set(d.batter, (batterRuns.get(d.batter) ?? 0) + d.runs_batter)
      bowlerRuns.set(d.bowler, (bowlerRuns.get(d.bowler) ?? 0) + ballRuns)
      if (d.is_wicket) bowlerWkts.set(d.bowler, (bowlerWkts.get(d.bowler) ?? 0) + 1)
      if (!isWide && !isNoball) {
        bowlerLegal.set(d.bowler, (bowlerLegal.get(d.bowler) ?? 0) + 1)
        overLegal++
        overRunsAcc += ballRuns
      }
      overBowler = d.bowler
      cumRuns += ballRuns
      if (d.is_wicket) cumWkts++
    }

    if (overBowler && overLegal >= 6 && overRunsAcc === 0)
      bowlerMaidens.set(overBowler, (bowlerMaidens.get(overBowler) ?? 0) + 1)

    const last   = balls[balls.length - 1]
    const sName  = last?.batter ?? ''
    const nsName = last?.non_striker ?? ''
    const bName  = last?.bowler ?? ''
    const total  = bowlerLegal.get(bName) ?? 0

    snapshots.push({
      overNum: ov,
      balls,
      cumulativeScore: { runs: cumRuns, wickets: cumWkts },
      overRuns: balls.reduce((s, d) => s + d.runs_batter + d.runs_extras, 0),
      overWkts: balls.filter(d => d.is_wicket).length,
      striker:    sName  ? { name: sName,  runs: batterRuns.get(sName)  ?? 0, balls: batterBalls.get(sName)  ?? 0 } : null,
      nonStriker: nsName && nsName !== 'Unknown'
                         ? { name: nsName, runs: batterRuns.get(nsName) ?? 0, balls: batterBalls.get(nsName) ?? 0 }
                         : null,
      bowler:     bName  ? {
        name: bName,
        overs: `${Math.floor(total / 6)}.${total % 6}`,
        maidens: bowlerMaidens.get(bName) ?? 0,
        runs: bowlerRuns.get(bName) ?? 0,
        wickets: bowlerWkts.get(bName) ?? 0,
      } : null,
    })
  }
  return snapshots
}

// ── Innings scorecard panel ───────────────────────────────────────────────────

function InningsPanel({ inn, defaultOpen, isSuperOver }: { inn: Innings; defaultOpen: boolean; isSuperOver: boolean }) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="card overflow-hidden">
      <button className="w-full flex items-center justify-between px-4 py-3 text-left" onClick={() => setOpen(o => !o)}>
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{inn.batting_team}</span>
          {isSuperOver && (
            <span className="text-xs px-1.5 py-0.5 rounded font-semibold" style={{ background: 'rgba(245,158,11,0.15)', color: 'var(--score)', fontSize: 10 }}>
              Super Over
            </span>
          )}
          <span className="text-base font-bold" style={{ color: 'var(--score)' }}>{inn.total_runs}/{inn.total_wickets}</span>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>({inn.overs} ov)</span>
        </div>
        {open
          ? <ChevronUp size={16} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
          : <ChevronDown size={16} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />}
      </button>

      {open && (
        <div className="px-4 pb-4">
          <div className="text-xs font-semibold uppercase tracking-wider mb-2 mt-1" style={{ color: 'var(--text-dim)' }}>Batting</div>
          <div className="overflow-x-auto mb-4">
            <table className="w-full text-sm min-w-[300px]">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Batter','R','B','4s','6s','SR'].map(h => (
                    <th key={h} className="pr-3 py-2 text-left font-medium" style={{ color: 'var(--text-muted)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {inn.batters.map((b, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td className="pr-3 py-2" style={{ minWidth: 120 }}>
                      <div className="font-medium" style={{ color: 'var(--text)' }}>{b.name}</div>
                      <div className="mt-0.5" style={{ color: 'var(--text-dim)', fontSize: 10 }}>{b.dismissal || 'not out'}</div>
                    </td>
                    <td className="pr-3 py-2 font-semibold" style={{ color: 'var(--score)', whiteSpace: 'nowrap' }}>
                      {b.runs}
                    </td>
                    <td className="pr-3 py-2" style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{b.balls}</td>
                    <td className="pr-3 py-2" style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{b.fours}</td>
                    <td className="pr-3 py-2" style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{b.sixes}</td>
                    <td className="pr-3 py-2" style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{b.strike_rate.toFixed(1)}</td>
                  </tr>
                ))}
                {inn.extras > 0 && (
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <td className="pr-3 py-2 font-medium" style={{ color: 'var(--text-muted)' }}>Extras</td>
                    <td className="pr-3 py-2" colSpan={5} style={{ whiteSpace: 'nowrap' }}>
                      <span className="font-semibold" style={{ color: 'var(--text-muted)' }}>{inn.extras}</span>{' '}
                      <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                        ({[
                          inn.extras_wides > 0 && `${inn.extras_wides}w`,
                          inn.extras_nb > 0    && `${inn.extras_nb}nb`,
                          inn.extras_lb > 0    && `${inn.extras_lb}lb`,
                          inn.extras_byes > 0  && `${inn.extras_byes}b`,
                        ].filter(Boolean).join(', ')})
                      </span>
                    </td>
                  </tr>
                )}
                <tr>
                  <td className="pr-3 pt-2 pb-1 font-semibold" style={{ color: 'var(--text)' }}>Total</td>
                  <td className="pt-2 pb-1" colSpan={5} style={{ whiteSpace: 'nowrap' }}>
                    <span className="font-semibold" style={{ color: 'var(--text)' }}>{inn.total_runs}/{inn.total_wickets}</span>{' '}
                    <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                      ({inn.overs} ov, {(() => {
                        const [ov, b] = inn.overs.split('.').map(Number)
                        const balls = ov * 6 + (b || 0)
                        return balls > 0 ? (inn.total_runs / (balls / 6)).toFixed(2) : '0.00'
                      })()} rpo)
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--text-dim)' }}>Bowling</div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[280px]">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Bowler','O','R','W','Econ'].map(h => (
                    <th key={h} className="pr-3 py-2 text-left font-medium" style={{ color: 'var(--text-muted)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {inn.bowlers.map((b, i) => (
                  <tr key={i} style={{ borderBottom: i < inn.bowlers.length - 1 ? '1px solid var(--border)' : 'none' }}>
                    <td className="pr-3 py-2 font-medium" style={{ color: 'var(--text)', whiteSpace: 'nowrap' }}>{b.name}</td>
                    <td className="pr-3 py-2" style={{ color: 'var(--text-muted)' }}>{b.overs}</td>
                    <td className="pr-3 py-2" style={{ color: 'var(--text-muted)' }}>{b.runs}</td>
                    <td className="pr-3 py-2 font-semibold" style={{ color: b.wickets > 0 ? 'var(--accent)' : 'var(--text-muted)' }}>{b.wickets}</td>
                    <td className="pr-3 py-2" style={{ color: 'var(--text-muted)' }}>{b.economy != null ? b.economy.toFixed(2) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Over summary card ─────────────────────────────────────────────────────────

function OverSummaryCard({ snap, ctx, isFinalOver }: {
  snap: OverSnapshot
  ctx: InningsCtx
  isFinalOver: boolean
}) {
  const { overNum, balls, cumulativeScore, overRuns, overWkts, striker, nonStriker, bowler } = snap
  const symbols = balls.map(ballSymbol)

  let statusLine: string | null = null

  if (!isFinalOver && ctx.isChase && ctx.target != null) {
    const runsNeeded = ctx.target - cumulativeScore.runs
    if (runsNeeded <= 0) {
      statusLine = 'Target reached!'
    } else if (!ctx.isOnlyOneOver && ctx.ovPerInnings != null) {
      const legalInOver = balls.filter(d => !['wide','noball'].includes(d.outcome_kind?.toLowerCase() ?? '')).length
      const ballsLeft   = ctx.ovPerInnings * 6 - (overNum * 6 + legalInOver)
      if (ballsLeft > 0) statusLine = `Need ${runsNeeded} runs to win in ${ballsLeft} ball${ballsLeft !== 1 ? 's' : ''}`
      else statusLine = `Need ${runsNeeded} runs to win`
    } else {
      statusLine = `Need ${runsNeeded} runs to win`
    }
  } else if (!isFinalOver && !ctx.isChase && ctx.leadOffset != null) {
    const lead = cumulativeScore.runs + ctx.leadOffset
    if (lead > 0) statusLine = `${ctx.leadTeamWhenPositive} lead by ${lead}`
    else if (lead < 0) statusLine = `${ctx.leadTeamWhenNegative} lead by ${Math.abs(lead)}`
    else statusLine = 'Scores level'
  }

  const hasBatterPanel = !!(striker || nonStriker || bowler)

  return (
    <div className="my-2 rounded-lg overflow-hidden" style={{ border: '1px solid var(--border)', background: 'var(--surface-2)' }}>
      {/* Header: left = over+score | right = balls (right-aligned) + runs below */}
      <div className="flex items-stretch" style={{ borderBottom: hasBatterPanel || statusLine ? '1px solid var(--border)' : undefined }}>
        <div className="flex flex-col justify-center px-3 py-2 shrink-0" style={{ minWidth: 100, borderRight: '1px solid var(--border)' }}>
          <span className="text-xs font-bold" style={{ color: 'var(--text)' }}>Over {overNum + 1}</span>
          <span className="text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>{cumulativeScore.runs}-{cumulativeScore.wickets}</span>
        </div>
        <div className="flex-1 flex flex-col items-end px-3 py-2 gap-1">
          <div className="flex gap-1 flex-wrap justify-end">
            {symbols.map((sym, i) => (
              <span key={i} className="text-xs font-bold font-mono w-6 h-6 flex items-center justify-center rounded"
                style={{ background: 'var(--surface)', color: ballColor(sym) }}>
                {sym}
              </span>
            ))}
          </div>
          <span className="text-xs" >
            {overRuns} run{overRuns !== 1 ? 's' : ''}{overWkts > 0 ? `, ${overWkts}W` : ''}
          </span>
        </div>
      </div>

      {/* Batter + bowler panel */}
      {hasBatterPanel && (
        <div className="flex gap-0 px-3 py-2" style={{ borderBottom: statusLine ? '1px solid var(--border)' : undefined }}>
          <div className="flex-1 flex flex-col gap-0.5" style={{ borderRight: '1px solid var(--border)', paddingRight: 12 }}>
            {striker && (
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs">{striker.name}</span>
                <span className="text-xs font-mono shrink-0">
                  {striker.runs} <span style={{ color: 'var(--text-dim)' }}>({striker.balls})</span>
                </span>
              </div>
            )}
            {nonStriker && (
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs">{nonStriker.name}</span>
                <span className="text-xs font-mono shrink-0">
                  {nonStriker.runs} <span style={{ color: 'var(--text-dim)' }}>({nonStriker.balls})</span>
                </span>
              </div>
            )}
          </div>
          {bowler && (
            <div className="flex flex-col items-end justify-center" style={{ paddingLeft: 12, minWidth: 100 }}>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{bowler.name}</span>
              <span className="text-xs font-mono">
                {bowler.overs}-{bowler.maidens}-{bowler.runs}-{bowler.wickets}
              </span>
            </div>
          )}
        </div>
      )}

      {statusLine && (
        <div className="px-3 py-1.5 text-xs font-medium" style={{ color: 'var(--score)' }}>{statusLine}</div>
      )}
    </div>
  )
}

// ── Result summary tab ────────────────────────────────────────────────────────

const ECO_THRESHOLD: Record<string, number> = { T20: 7.5, ODI: 5.5, Test: 3.0 }

interface PlayerStat {
  name: string
  team: string
  headshot_url: string | null
  batting: { runs: number; balls: number; fours: number; sixes: number; strike_rate: number; not_out: boolean } | null
  bowling: { overs: string; runs: number; wickets: number; economy: number; dot_balls: number } | null
  batting_pts: number
  bowling_pts: number
  total: number
}

function computePOTM(scorecard: Scorecard): PlayerStat | null {
  const fmt = scorecard.match_format ?? 'T20'
  const ecoThreshold = ECO_THRESHOLD[fmt] ?? 7.5

  const teamFor: Record<string, string> = {}
  const headshotFor: Record<string, string | null> = {}
  const batStats: Record<string, { runs: number; balls: number; fours: number; sixes: number; sr: number; dismissal: string }> = {}
  const bwlStats: Record<string, { overs: string; runs: number; wickets: number; economy: number; dot_balls: number }> = {}

  for (const inn of scorecard.innings) {
    for (const b of inn.batters ?? []) {
      batStats[b.name] = { runs: b.runs, balls: b.balls, fours: b.fours ?? 0, sixes: b.sixes ?? 0, sr: b.strike_rate ?? 0, dismissal: b.dismissal ?? '' }
      teamFor[b.name] = inn.batting_team ?? ''
      headshotFor[b.name] ??= b.headshot_url ?? null
    }
    for (const bw of inn.bowlers ?? []) {
      bwlStats[bw.name] = { overs: bw.overs, runs: bw.runs, wickets: bw.wickets, economy: bw.economy ?? 0, dot_balls: bw.dot_balls ?? 0 }
      teamFor[bw.name] ??= inn.bowling_team ?? ''
    }
  }

  const players = new Set([...Object.keys(batStats), ...Object.keys(bwlStats)])
  let best: PlayerStat | null = null

  for (const name of players) {
    const bat = batStats[name] ?? null
    const bwl = bwlStats[name] ?? null

    // ── Batting points (mirrors awards.py PlayerMatchPoints) ──
    let batPts = 0
    if (bat) {
      batPts += bat.runs * 0.5
      batPts += bat.fours * 1.0
      batPts += bat.sixes * 2.0
      if (bat.runs >= 50) batPts += 10.0
      if (bat.runs >= 100) batPts += 20.0
      const notOut = bat.dismissal === 'not out'
      if (!notOut && bat.runs < 10 && bat.balls >= 3) batPts -= 3.0  // cheap dismissal
      if (notOut && bat.balls > 0) batPts += 2.0                     // not-out bonus
    }

    // ── Bowling points (mirrors awards.py PlayerMatchPoints) ──
    let bwlPts = 0
    if (bwl) {
      bwlPts += bwl.wickets * 10.0
      bwlPts += bwl.dot_balls * 1.0
      // Economy bonus: requires >= 2 complete overs
      const completeOvers = parseInt(bwl.overs.split('.')[0], 10)
      if (completeOvers >= 2 && bwl.economy < ecoThreshold) {
        const bonus = (ecoThreshold - bwl.economy) / ecoThreshold * 2.0 * completeOvers
        bwlPts += Math.min(bonus, 12.0)
      }
    }

    const stat: PlayerStat = {
      name,
      team: teamFor[name] ?? '',
      headshot_url: headshotFor[name] ?? null,
      batting: bat ? { runs: bat.runs, balls: bat.balls, fours: bat.fours, sixes: bat.sixes, strike_rate: bat.sr, not_out: bat.dismissal === 'not out' } : null,
      bowling: bwl,
      batting_pts: batPts,
      bowling_pts: bwlPts,
      total: batPts + bwlPts,
    }
    if (!best || stat.total > best.total) best = stat
  }

  return best
}

function computeFielding(scorecard: Scorecard): Record<string, number> {
  const catches: Record<string, number> = {}
  const add = (name: string) => { catches[name] = (catches[name] ?? 0) + 1 }

  for (const inn of scorecard.innings) {
    for (const b of inn.batters ?? []) {
      const d = b.dismissal ?? ''
      if (!d || d === 'not out') continue
      if (d.startsWith('c&b ')) {
        add(d.slice(4).trim())
      } else if (d.startsWith('c ') && d.includes(' b ')) {
        add(d.slice(2, d.indexOf(' b ')).trim())
      } else if (d.startsWith('st ') && d.includes(' b ')) {
        add(d.slice(3, d.indexOf(' b ')).trim())
      } else if (d.startsWith('run out (') && d.endsWith(')')) {
        const f = d.slice(9, -1).trim()
        if (f) add(f)
      }
    }
  }
  return catches
}

// Keyed by DeliveryItem object reference (handles duplicate over_ball values for wides/no-balls)
function computeWicketBatterStats(delivs: DeliveryItem[]): Map<DeliveryItem, { runs: number; balls: number }> {
  const runsSoFar  = new Map<string, number>()
  const ballsSoFar = new Map<string, number>()
  const result     = new Map<DeliveryItem, { runs: number; balls: number }>()
  for (const d of delivs) {
    runsSoFar.set(d.batter, (runsSoFar.get(d.batter) ?? 0) + d.runs_batter)
    if ((d.outcome_kind?.toLowerCase() ?? '') !== 'wide') {
      ballsSoFar.set(d.batter, (ballsSoFar.get(d.batter) ?? 0) + 1)
    }
    if (d.is_wicket) {
      result.set(d, { runs: runsSoFar.get(d.batter) ?? 0, balls: ballsSoFar.get(d.batter) ?? 0 })
    }
  }
  return result
}

// ── Worm chart ────────────────────────────────────────────────────────────────

// Fixed colours — always distinct regardless of active theme
const WORM_C1 = '#0EA5E9'          // sky blue   (team batting 1st)
const WORM_C2 = '#F97316'          // orange     (team batting 2nd)
const WORM_C1_DIM = '#0EA5E970'    // sky blue 44%  (Test 2nd innings)
const WORM_C2_DIM = '#F9731670'    // orange 44%    (Test 2nd innings)

function WormChart({ deliveries, matchFormat, innings: inningsList }: {
  deliveries: DeliveryItem[]
  matchFormat: string | null
  innings: Innings[]
}) {
  const isTest = matchFormat === 'Test'
  const W = 400, H = 130
  const PAD = { t: 8, r: 8, b: 30, l: 32 }
  const chartW = W - PAD.l - PAD.r
  const chartH = H - PAD.t - PAD.b

  const byInning: Record<number, DeliveryItem[]> = {}
  for (const d of deliveries) {
    if (!isTest && d.inning_number > 2) continue
    ;(byInning[d.inning_number] ??= []).push(d)
  }

  function getPoints(innNum: number): { x: number; y: number }[] {
    const delivs = byInning[innNum]
    if (!delivs || delivs.length === 0) return []
    const snaps = computeSnapshots(delivs)
    return [{ x: 0, y: 0 }, ...snaps.map(s => ({ x: s.overNum + 1, y: s.cumulativeScore.runs }))]
  }

  // Wicket positions — fractional x within over, exact cumulative y
  function getWicketPositions(innNum: number, startX = 0, startY = 0): { x: number; y: number }[] {
    const delivs = byInning[innNum]
    if (!delivs) return []
    let cumRuns = startY, prevOv = -1, legalInOv = 0
    const result: { x: number; y: number }[] = []
    for (const d of delivs) {
      const ov = parseInt(d.over_ball.split('.')[0], 10)
      if (ov !== prevOv) { legalInOv = 0; prevOv = ov }
      cumRuns += d.runs_batter + d.runs_extras
      if ((d.outcome_kind?.toLowerCase() ?? '') !== 'wide') legalInOv++
      if (d.is_wicket) result.push({ x: startX + ov + legalInOv / 6, y: cumRuns })
    }
    return result
  }

  const team1 = inningsList.find(i => i.inning_number === 1)?.batting_team ?? 'Team 1'
  const team2 = inningsList.find(i => i.inning_number === 2)?.batting_team ?? 'Team 2'

  const pts1a = getPoints(1)
  const pts2a = getPoints(2)
  const pts1b_raw = isTest ? getPoints(3) : []
  const pts2b_raw = isTest ? getPoints(4) : []

  const xOff1 = pts1a.at(-1)?.x ?? 0
  const yOff1 = pts1a.at(-1)?.y ?? 0
  const xOff2 = pts2a.at(-1)?.x ?? 0
  const yOff2 = pts2a.at(-1)?.y ?? 0
  const pts1b = pts1b_raw.slice(1).map(p => ({ x: p.x + xOff1, y: p.y + yOff1 }))
  const pts2b = pts2b_raw.slice(1).map(p => ({ x: p.x + xOff2, y: p.y + yOff2 }))

  const wk1 = [...getWicketPositions(1), ...getWicketPositions(3, xOff1, yOff1)]
  const wk2 = [...getWicketPositions(2), ...getWicketPositions(4, xOff2, yOff2)]

  const allPts = [...pts1a, ...pts1b, ...pts2a, ...pts2b]
  if (allPts.length < 2) return null

  const maxX = Math.max(1, ...allPts.map(p => p.x))
  const maxY = Math.max(1, ...allPts.map(p => p.y))

  const sx = (x: number) => PAD.l + (x / maxX) * chartW
  const sy = (y: number) => PAD.t + chartH - (y / maxY) * chartH
  const poly = (pts: { x: number; y: number }[]) =>
    pts.map(p => `${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' ')

  const yTicks = [0, Math.round(maxY / 2), maxY]
  const xTickCount = Math.min(5, maxX)
  const xStep = Math.ceil(maxX / xTickCount)
  const xTicks = Array.from({ length: xTickCount + 1 }, (_, i) => Math.min(i * xStep, maxX))
    .filter((v, i, a) => a.indexOf(v) === i)

  return (
    <div className="rounded-xl overflow-hidden" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
      <div className="px-4 pt-3 pb-1 text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>
        Match Worm
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 140 }}>
        {/* Grid */}
        {yTicks.map(y => (
          <g key={y}>
            <line x1={PAD.l} y1={sy(y)} x2={W - PAD.r} y2={sy(y)} stroke="rgba(255,255,255,0.06)" strokeWidth={1} />
            <text x={PAD.l - 4} y={sy(y) + 3.5} textAnchor="end" fontSize={8} fill="var(--text-dim)">{y}</text>
          </g>
        ))}
        {xTicks.slice(1).map(x => (
          <text key={x} x={sx(x)} y={H - PAD.b + 12} textAnchor="middle" fontSize={8} fill="var(--text-dim)">Ov {x}</text>
        ))}
        <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={PAD.t + chartH} stroke="var(--border)" strokeWidth={1} />

        {/* Team 1 lines */}
        {pts1a.length > 1 && (
          <polyline points={poly(pts1a)} fill="none" stroke={WORM_C1} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        )}
        {isTest && pts1b.length > 1 && (
          <polyline points={poly([pts1a[pts1a.length - 1], ...pts1b])} fill="none" stroke={WORM_C1_DIM} strokeWidth={2} strokeDasharray="5,3" strokeLinecap="round" />
        )}

        {/* Team 2 lines */}
        {pts2a.length > 1 && (
          <polyline points={poly(pts2a)} fill="none" stroke={WORM_C2} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        )}
        {isTest && pts2b.length > 1 && (
          <polyline points={poly([pts2a[pts2a.length - 1], ...pts2b])} fill="none" stroke={WORM_C2_DIM} strokeWidth={2} strokeDasharray="5,3" strokeLinecap="round" />
        )}

        {/* Wicket dots — hollow circles on the line */}
        {wk1.map((pt, i) => (
          <circle key={`w1-${i}`} cx={sx(pt.x)} cy={sy(pt.y)} r={3.5} fill="var(--bg)" stroke={WORM_C1} strokeWidth={1.5} />
        ))}
        {wk2.map((pt, i) => (
          <circle key={`w2-${i}`} cx={sx(pt.x)} cy={sy(pt.y)} r={3.5} fill="var(--bg)" stroke={WORM_C2} strokeWidth={1.5} />
        ))}

        {/* Legend */}
        <line x1={PAD.l + 2} y1={H - 8} x2={PAD.l + 12} y2={H - 8} stroke={WORM_C1} strokeWidth={2} />
        <text x={PAD.l + 16} y={H - 5} fontSize={9} fill="var(--text-muted)">{team1}</text>
        <line x1={PAD.l + Math.min(team1.length * 5.5 + 22, 165)} y1={H - 8} x2={PAD.l + Math.min(team1.length * 5.5 + 32, 175)} y2={H - 8} stroke={WORM_C2} strokeWidth={2} />
        <text x={PAD.l + Math.min(team1.length * 5.5 + 36, 179)} y={H - 5} fontSize={9} fill="var(--text-muted)">{team2}</text>
        {isTest && (
          <text x={W - PAD.r} y={H - 5} textAnchor="end" fontSize={8} fill="var(--text-dim)">dashed = 2nd innings</text>
        )}
      </svg>
    </div>
  )
}

function bannerText(desc: string | null): string {
  if (!desc) return ''
  if (desc.includes('Super Over')) {
    const parts = desc.split('·').map(s => s.trim())
    const soWinner = parts[1] ?? ''
    return `Match tied! ${soWinner}`
  }
  if (desc === 'No result') return 'No result'
  if (desc === 'Match tied') return 'Match tied'
  return `${desc}!`
}

function ResultSummaryTab({ scorecard, deliveries, userTeam }: {
  scorecard: Scorecard
  deliveries: DeliveryItem[]
  userTeam: string | null
}) {
  const potm = computePOTM(scorecard)
  const fielding = computeFielding(scorecard)
  const isTest = scorecard.match_format === 'Test'
  const desc = scorecard.result_description ?? null

  // Parse winner from result description
  const winnerMatch = desc?.match(/^(.+?)\s+won\s+by\s+(.+)$/)
  const winner = winnerMatch ? winnerMatch[1].trim() : null
  const margin = winnerMatch ? winnerMatch[2].trim() : null
  const isTied = desc === 'Match tied' || desc?.startsWith('Match tied')
  const isNoResult = desc === 'No result'

  const userWon  = !!userTeam && !!winner && winner.toLowerCase() === userTeam.toLowerCase()
  const userLost = !!userTeam && !!winner && winner.toLowerCase() !== userTeam.toLowerCase()

  // Group innings by team (for Test: team may have 2 innings each)
  const teamOrder: string[] = []
  const teamInnings: Record<string, Innings[]> = {}
  for (const inn of scorecard.innings) {
    if (!isTest && inn.inning_number > 2) continue
    const team = inn.batting_team
    if (!teamOrder.includes(team)) teamOrder.push(team)
    ;(teamInnings[team] ??= []).push(inn)
  }

  return (
    <div className="fade-in flex flex-col gap-3">
      {/* Result card — personalized if userTeam known, generic otherwise */}
      {desc && (
        <div
          className="rounded-xl px-4 py-4 flex flex-col gap-1 text-center"
          style={{
            background: userWon
              ? 'rgba(245,158,11,0.12)'
              : userLost
                ? 'rgba(239,68,68,0.07)'
                : 'rgba(245,158,11,0.08)',
            border: userWon
              ? '1px solid rgba(245,158,11,0.35)'
              : userLost
                ? '1px solid rgba(239,68,68,0.2)'
                : '1px solid rgba(245,158,11,0.2)',
          }}
        >
          {userWon ? (
            <>
              <div className="text-xl font-extrabold" style={{ color: 'var(--score)' }}>You won!</div>
              {margin && <div className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>{winner} won by {margin}</div>}
            </>
          ) : userLost ? (
            <>
              <div className="text-base font-bold" style={{ color: 'var(--text-muted)' }}>You lost</div>
              {winner && margin && (
                <div className="text-xs" style={{ color: 'var(--text-dim)' }}>{winner} won by {margin}</div>
              )}
            </>
          ) : isTied ? (
            <div className="text-sm font-bold" style={{ color: 'var(--score)' }}>Match tied!</div>
          ) : isNoResult ? (
            <div className="text-sm font-bold" style={{ color: 'var(--text-muted)' }}>No result</div>
          ) : (
            <div className="text-sm font-bold" style={{ color: 'var(--score)' }}>{bannerText(desc)}</div>
          )}
          {scorecard.venue && (
            <div className="text-xs mt-1" style={{ color: 'var(--text-dim)' }}>
              {scorecard.venue}{scorecard.venue_country ? `, ${scorecard.venue_country}` : ''}
            </div>
          )}
        </div>
      )}

      {/* Team scores */}
      <div className="rounded-xl overflow-hidden" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
        {teamOrder.map((team, idx) => {
          const innings = teamInnings[team] ?? []
          const isWinner = !!winner && team.toLowerCase() === winner.toLowerCase()
          return (
            <div
              key={team}
              className="flex items-center justify-between px-4 py-3"
              style={{ borderBottom: idx < teamOrder.length - 1 ? '1px solid var(--border)' : 'none' }}
            >
              <div className="flex items-center gap-2 flex-shrink-0 mr-3">
                <span className="text-sm font-semibold" style={{ color: isWinner ? 'var(--accent)' : 'var(--text)' }}>{team}</span>
              </div>
              <span className="text-sm font-mono text-right" style={{ color: 'var(--score)' }}>
                {isTest
                  ? innings.map(i => `${i.total_runs}/${i.total_wickets}`).join(' & ')
                  : innings.map(i => (
                    <span key={i.inning_number}>
                      {i.total_runs}/{i.total_wickets}{' '}
                      <span style={{ color: 'var(--text-dim)', fontSize: '0.8em' }}>({i.overs} ov)</span>
                    </span>
                  ))
                }
              </span>
            </div>
          )
        })}
      </div>

      {/* Player of the Match */}
      {potm && (() => {
        const catches = fielding[potm.name] ?? 0
        const perfParts: string[] = []
        if (potm.batting) {
          const star = potm.batting.not_out ? '*' : ''
          perfParts.push(`${potm.batting.runs}${star} (${potm.batting.balls})`)
        }
        if (potm.bowling) perfParts.push(`${potm.bowling.runs}/${potm.bowling.wickets}`)
        if (catches > 0) perfParts.push(`${catches} ${catches === 1 ? 'catch' : 'catches'}`)

        return (
          <div className="rounded-xl px-4 py-3 flex gap-3 items-center"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
            <PlayerAvatar name={potm.name} url={potm.headshot_url} size={44} />
            <div className="flex flex-col gap-0.5 flex-1 min-w-0">
              <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>
                Player of the Match
              </div>
              <div className="text-sm font-bold truncate" style={{ color: 'var(--text)' }}>{potm.name}</div>
              <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{potm.team}</div>
              {perfParts.length > 0 && (
                <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                  {perfParts.join('  ·  ')}
                </div>
              )}
            </div>
          </div>
        )
      })()}

      {/* Worm chart — after POTM */}
      {deliveries.length > 0 && (
        <WormChart deliveries={deliveries} matchFormat={scorecard.match_format ?? null} innings={scorecard.innings} />
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function MatchDetailPage() {
  const { simId, matchId } = useParams<{ simId: string; matchId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const fromTab = ((location.state as Record<string, unknown>)?.fromTab as string) ?? 'matches'
  const backPath = ((location.state as Record<string, unknown>)?.backPath as string) ?? null
  const userTeam = ((location.state as Record<string, unknown>)?.userTeam as string) ?? null
  const [tab, setTab] = useState<Tab>('result')
  const [scorecard, setScorecard] = useState<Scorecard | null>(null)
  const [commentary, setCommentary] = useState<Commentary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const mid = matchId ? parseInt(matchId, 10) : null

  useEffect(() => {
    if (!simId || mid == null) return
    setLoading(true)
    // Fetch both scorecard and commentary upfront (commentary needed for worm chart)
    Promise.all([
      api.getMatchScorecard(simId, mid).catch(() => api.getSimScorecard(simId)),
      api.getMatchCommentary(simId, mid).catch(() => api.getSimCommentary(simId)).catch(() => null),
    ]).then(([sc, comm]) => {
      setScorecard(sc as Scorecard)
      if (comm) setCommentary(comm as unknown as Commentary)
    }).catch(() => setError('Scorecard not available'))
      .finally(() => setLoading(false))
  }, [simId, mid])

  if (loading) return <div className="flex justify-center py-16"><Spinner /></div>

  if (error || !scorecard) {
    return (
      <div className="max-w-lg mx-auto px-4 py-16 text-center">
        <div className="text-4xl mb-4">⚠</div>
        <div className="text-sm mb-4" style={{ color: 'var(--text-muted)' }}>{error || 'No scorecard found'}</div>
        <button className="btn-outline" onClick={() => navigate(-1)}>Go back</button>
      </div>
    )
  }

  const hasSuperOver = scorecard.innings.some(i => i.inning_number >= 3) &&
                       commentary?.match_format !== 'Test'

  const inn = (n: number) => scorecard.innings.find(i => i.inning_number === n)

  // Last regular innings idx for default-open panel
  const mainInnings = hasSuperOver
    ? scorecard.innings
    : scorecard.innings.filter(i => i.inning_number <= 2)
  const lastInnIdx = mainInnings.length - 1

  return (
    <div className="w-full px-1 py-6">
      <button className="flex items-center gap-1 text-sm mb-5" style={{ color: 'var(--text-muted)' }}
        onClick={() => backPath
          ? navigate(backPath, { state: { tab: fromTab } })
          : navigate(`/results/${simId}`, { state: { tab: fromTab, scrollTo: fromTab === 'matches' ? mid : undefined } })
        }>
        <ChevronLeft size={14} /> Back
      </button>

      <div className="mb-4">
        <div className="text-base font-semibold" style={{ color: 'var(--text)' }}>
          {scorecard.home_team} vs {scorecard.away_team}
        </div>
        <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
          {scorecard.match_label}
          {scorecard.venue ? ` · ${scorecard.venue}${scorecard.venue_country ? `, ${scorecard.venue_country}` : ''}` : ''}
        </div>
      </div>

      <div className="flex gap-1 mb-5 p-1 rounded-lg" style={{ background: 'var(--surface)' }}>
        {(['result', 'scorecard', 'commentary'] as Tab[]).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className="flex-1 py-2 rounded-md text-sm font-medium capitalize transition-all"
            style={{
              background: tab === t ? 'var(--surface-2)' : 'transparent',
              color: tab === t ? 'var(--accent)' : 'var(--text-muted)',
              border: tab === t ? '1px solid var(--border)' : '1px solid transparent',
            }}>
            {t}
          </button>
        ))}
      </div>

      {/* ── Result summary ── */}
      {tab === 'result' && (
        <ResultSummaryTab
          scorecard={scorecard}
          deliveries={commentary?.deliveries ?? []}
          userTeam={userTeam}
        />
      )}

      {/* ── Scorecard ── */}
      {tab === 'scorecard' && (
        <div className="fade-in flex flex-col gap-3">
          {scorecard.innings.map((i, idx) => (
            <InningsPanel
              key={i.inning_number}
              inn={i}
              defaultOpen={idx === lastInnIdx}
              isSuperOver={hasSuperOver && i.inning_number >= 3}
            />
          ))}
        </div>
      )}

      {/* ── Commentary ── */}
      {tab === 'commentary' && (
        <div className="fade-in">
          {commentary === null ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : commentary.deliveries.length === 0 ? (
            <div className="text-center py-8 text-sm" style={{ color: 'var(--text-dim)' }}>No commentary available</div>
          ) : (
            (() => {
              const isTestFormat = commentary.match_format === 'Test'
              const byInning: Record<number, DeliveryItem[]> = {}
              for (const d of commentary.deliveries) {
                ;(byInning[d.inning_number] ??= []).push(d)
              }
              const hasSO = !isTestFormat && [3, 4].some(n => byInning[n])

              // Derive correct overs from format — stored value is corrupted to 1 for super over matches
              const mainMatchOvPerInnings: number | null = (() => {
                if (isTestFormat) return null
                const fmt = (commentary.match_format ?? '').toUpperCase()
                if (fmt.includes('T20')) return 20
                if (fmt === 'ODI') return 50
                // fallback: stored value if it looks sane
                return (commentary.overs_per_innings ?? 0) > 1 ? commentary.overs_per_innings : null
              })()

              // Build innings context — no hardcoded numbers inside OverSummaryCard
              const buildCtx = (innNum: number): InningsCtx => {
                const i1 = inn(1), i2 = inn(2), i3 = inn(3), i4 = inn(4)

                const base = { leadOffset: null, leadTeamWhenPositive: '', leadTeamWhenNegative: '', isSuperOverInnings: false, isOnlyOneOver: false }

                if (isTestFormat) {
                  if (innNum === 1) {
                    return { ...base, isChase: false, target: null, finalBanner: null, ovPerInnings: null }
                  }
                  if (innNum === 2) {
                    return { ...base, isChase: false, target: null, leadOffset: -(i1?.total_runs ?? 0), leadTeamWhenPositive: i2?.batting_team ?? '', leadTeamWhenNegative: i1?.batting_team ?? '', finalBanner: null, ovPerInnings: null }
                  }
                  if (innNum === 3) {
                    const offset = (i1?.total_runs ?? 0) - (i2?.total_runs ?? 0)
                    return { ...base, isChase: false, target: null, leadOffset: offset, leadTeamWhenPositive: i1?.batting_team ?? '', leadTeamWhenNegative: i2?.batting_team ?? '', finalBanner: null, ovPerInnings: null }
                  }
                  if (innNum === 4) {
                    const testTarget = (i1?.total_runs ?? 0) + (i3?.total_runs ?? 0) - (i2?.total_runs ?? 0) + 1
                    return { ...base, isChase: true, target: testTarget, finalBanner: scorecard.result_description ?? null, ovPerInnings: null }
                  }
                } else {
                  if (innNum === 1) {
                    const target = (i1?.total_runs ?? 0) + 1
                    const overs  = mainMatchOvPerInnings
                    const banner = i2 ? (overs ? `${i2.batting_team} need ${target} to win in ${overs} over${overs !== 1 ? 's' : ''}` : `${i2.batting_team} need ${target} to win`) : null
                    return { ...base, isChase: false, target: null, finalBanner: banner, ovPerInnings: mainMatchOvPerInnings }
                  }
                  if (innNum === 2) {
                    const banner = hasSO ? 'Match tied — Super Over to follow' : (scorecard.result_description ?? null)
                    return { ...base, isChase: true, target: (i1?.total_runs ?? 0) + 1, finalBanner: banner, ovPerInnings: mainMatchOvPerInnings }
                  }
                  if (innNum === 3 && hasSO) {
                    const soTarget = (i3?.total_runs ?? 0) + 1
                    const banner   = i4 ? `${i4.batting_team} need ${soTarget} to win` : null
                    return { ...base, isChase: false, target: null, finalBanner: banner, isSuperOverInnings: true, isOnlyOneOver: true, ovPerInnings: 1 }
                  }
                  if (innNum === 4 && hasSO) {
                    return { ...base, isChase: true, target: (i3?.total_runs ?? 0) + 1, finalBanner: scorecard.result_description ?? null, isSuperOverInnings: true, isOnlyOneOver: true, ovPerInnings: 1 }
                  }
                }
                return { ...base, isChase: false, target: null, finalBanner: null, ovPerInnings: null }
              }

              return Object.keys(byInning)
                .map(Number)
                .sort((a, b) => b - a)   // newest innings first
                .map(innNum => {
                  const delivs    = byInning[innNum]
                  const innEntry  = scorecard.innings.find(i => i.inning_number === innNum)
                  const ctx       = buildCtx(innNum)
                  const snapshots = computeSnapshots(delivs)
                  const maxOverNum = Math.max(...snapshots.map(s => s.overNum))
                  const wicketStats = computeWicketBatterStats(delivs)

                  const innLabel = ctx.isSuperOverInnings
                    ? `Super Over — ${innEntry?.batting_team ?? `Team ${innNum}`}`
                    : (innEntry?.batting_team ?? `Innings ${innNum}`)

                  return (
                    <div key={innNum} className="mb-8">
                      <div className="text-sm font-semibold mb-3 sticky top-0 py-2 z-10"
                        style={{ color: 'var(--text)', background: 'var(--bg)' }}>
                        {innLabel} Innings
                      </div>

                      {[...snapshots].reverse().map(snap => {
                        const isFinalOver = snap.overNum === maxOverNum
                        return (
                          <div key={snap.overNum}>
                            {/* Result / target banner sits above the final over card */}
                            {isFinalOver && ctx.finalBanner && (
                              <div className="mb-2 px-3 py-2 rounded-lg text-xs font-semibold"
                                style={{ background: 'var(--surface-2)', color: 'var(--score)', border: '1px solid var(--border)' }}>
                                {ctx.finalBanner}
                              </div>
                            )}
                            <OverSummaryCard snap={snap} ctx={ctx} isFinalOver={isFinalOver} />
                            <div className="flex flex-col gap-0.5 mb-1">
                              {[...snap.balls].reverse().map((ball, i) => {
                                const ws = ball.is_wicket ? wicketStats.get(ball) : undefined
                                return (
                                  <div key={i} className="flex gap-3 px-3 py-1.5 rounded-md"
                                    style={{ background: ball.is_wicket ? 'rgba(239,68,68,0.07)' : ball.runs_batter === 6 ? 'rgba(245,158,11,0.06)' : 'transparent' }}>
                                    <span className="shrink-0 text-xs font-mono font-semibold pt-0.5"
                                      style={{ color: ball.is_wicket ? 'var(--loss)' : ball.runs_batter >= 4 ? 'var(--score)' : 'var(--accent)', minWidth: 32 }}>
                                      {ball.over_ball}
                                    </span>
                                    <span className="text-xs flex flex-col gap-0.5" style={{ color: 'var(--text-muted)' }}>
                                      <span>{ball.commentary_text.replace(/^\d+\.\d+\s*/, '').replace(/wide\+(\d+)/g, '$1 wides')}</span>
                                      {ws && (
                                        <span className="font-semibold" style={{ color: 'var(--loss)' }}>
                                          {ball.batter} departs for {ws.runs} ({ws.balls})
                                        </span>
                                      )}
                                    </span>
                                  </div>
                                )
                              })}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )
                })
            })()
          )}
        </div>
      )}
    </div>
  )
}
