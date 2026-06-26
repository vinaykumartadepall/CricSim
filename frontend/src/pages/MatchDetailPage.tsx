import { useEffect, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { ChevronLeft, ChevronDown, ChevronUp } from 'lucide-react'
import { Spinner } from '@/components/ui/Spinner'
import { api } from '@/api/client'
import type { Scorecard, Innings } from '@/types'

type Tab = 'scorecard' | 'commentary'

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
  if (kind === 'wide') return 'Wd'
  if (kind === 'noball') return 'Nb'
  if (d.runs_batter === 6) return '6'
  if (d.runs_batter === 4) return '4'
  const total = d.runs_batter + d.runs_extras
  return total === 0 ? '•' : String(total)
}

function ballColor(sym: string): string {
  if (sym === 'W')                  return 'var(--loss)'
  if (sym === '6')                  return 'var(--score)'
  if (sym === '4')                  return 'var(--accent)'
  if (sym === 'Wd' || sym === 'Nb') return 'var(--text-dim)'
  if (sym === '•')                  return 'var(--text-dim)'
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
                    <td className="pr-3 py-2 font-semibold" style={{ color: 'var(--score)', whiteSpace: 'nowrap' }}>{b.runs}</td>
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
          <span className="text-xs" style={{ color: 'var(--text-dim)' }}>
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
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{striker.name}</span>
                <span className="text-xs font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>
                  {striker.runs} <span style={{ color: 'var(--text-dim)' }}>({striker.balls})</span>
                </span>
              </div>
            )}
            {nonStriker && (
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{nonStriker.name}</span>
                <span className="text-xs font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>
                  {nonStriker.runs} <span style={{ color: 'var(--text-dim)' }}>({nonStriker.balls})</span>
                </span>
              </div>
            )}
          </div>
          {bowler && (
            <div className="flex flex-col items-end justify-center" style={{ paddingLeft: 12, minWidth: 100 }}>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{bowler.name}</span>
              <span className="text-xs font-mono" style={{ color: 'var(--text-dim)' }}>
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

// ── Main page ─────────────────────────────────────────────────────────────────

export function MatchDetailPage() {
  const { simId, matchId } = useParams<{ simId: string; matchId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const fromTab = ((location.state as Record<string, unknown>)?.fromTab as string) ?? 'matches'
  const [tab, setTab] = useState<Tab>('scorecard')
  const [scorecard, setScorecard] = useState<Scorecard | null>(null)
  const [commentary, setCommentary] = useState<Commentary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const mid = matchId ? parseInt(matchId, 10) : null

  useEffect(() => {
    if (!simId || mid == null) return
    setLoading(true)
    api.getMatchScorecard(simId, mid)
      .then(sc => setScorecard(sc))
      .catch(() => setError('Scorecard not available'))
      .finally(() => setLoading(false))
  }, [simId, mid])

  useEffect(() => {
    if (!simId || mid == null || tab !== 'commentary') return
    if (commentary !== null) return
    api.getMatchCommentary(simId, mid)
      .then((data: any) => setCommentary(data as Commentary))
      .catch(() => setCommentary({ match_id: mid!, match_label: '', match_format: null, overs_per_innings: null, deliveries: [] }))
  }, [simId, mid, tab, commentary])

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

  const isTest = scorecard.innings.some(i => i.inning_number === 1) &&
                 !scorecard.innings.some(i => i.inning_number === 3 && scorecard.innings[0]?.batting_team === scorecard.innings[2]?.batting_team)
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
        onClick={() => navigate(`/results/${simId}`, { state: { tab: fromTab, scrollTo: fromTab === 'matches' ? mid : undefined } })}>
        <ChevronLeft size={14} /> {fromTab === 'standings' ? 'Back to standings' : 'Back to matches'}
      </button>

      <div className="mb-4">
        <div className="text-base font-semibold" style={{ color: 'var(--text)' }}>{scorecard.match_label}</div>
        {scorecard.result_description && (
          <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{scorecard.result_description}</div>
        )}
      </div>

      <div className="flex gap-1 mb-5 p-1 rounded-lg" style={{ background: 'var(--surface)' }}>
        {(['scorecard', 'commentary'] as Tab[]).map(t => (
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
                              {[...snap.balls].reverse().map((ball, i) => (
                                <div key={i} className="flex gap-3 px-3 py-1.5 rounded-md"
                                  style={{ background: ball.is_wicket ? 'rgba(239,68,68,0.07)' : ball.runs_batter === 6 ? 'rgba(245,158,11,0.06)' : 'transparent' }}>
                                  <span className="shrink-0 text-xs font-mono font-semibold pt-0.5"
                                    style={{ color: ball.is_wicket ? 'var(--loss)' : ball.runs_batter >= 4 ? 'var(--score)' : 'var(--accent)', minWidth: 32 }}>
                                    {ball.over_ball}
                                  </span>
                                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                                    {ball.commentary_text.replace(/^\d+\.\d+\s*/, '')}
                                  </span>
                                </div>
                              ))}
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
