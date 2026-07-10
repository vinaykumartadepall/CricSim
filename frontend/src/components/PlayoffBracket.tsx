import { useNavigate } from 'react-router-dom'
import type { MatchItem } from '@/types'

// ── Layout constants ──────────────────────────────────────────────────────────

const CW = 174   // card width
const CH = 84    // card height
const CGAP = 56  // column gap (space for connector lines)

// ── Match card ────────────────────────────────────────────────────────────────

function MatchCard({
  label, match, x, y, simId, userTeam,
}: {
  label: string
  match?: MatchItem
  x: number
  y: number
  simId: string
  userTeam: string | null
}) {
  const navigate = useNavigate()
  const isUser = !!userTeam && (match?.home_team === userTeam || match?.away_team === userTeam)
  const isFinal = label === 'Final'

  return (
    <div
      onClick={() => match && navigate(`/results/${simId}/matches/${match.match_id}`, { state: { fromTab: 'standings' } })}
      style={{
        position: 'absolute', left: x, top: y, width: CW, height: CH,
        background: 'var(--surface)',
        border: `1px solid ${isUser ? 'rgba(59,130,246,0.55)' : isFinal ? 'rgba(245,158,11,0.35)' : 'var(--border)'}`,
        borderRadius: 8, overflow: 'hidden',
        cursor: match ? 'pointer' : 'default',
        boxShadow: isFinal ? '0 0 14px rgba(245,158,11,0.07)' : undefined,
      }}
      onMouseEnter={e => { if (match) (e.currentTarget as HTMLElement).style.opacity = '0.75' }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.opacity = '1' }}
    >
      {/* Label */}
      <div style={{
        padding: '3px 8px',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 4,
        background: isFinal ? 'rgba(245,158,11,0.05)' : undefined,
      }}>
        {isFinal && <span style={{ fontSize: 10 }}>🏆</span>}
        <span style={{ fontSize: 10, fontWeight: 500, letterSpacing: '0.04em', color: isFinal ? 'var(--score)' : 'var(--text-dim)' }}>
          {label.toUpperCase()}
        </span>
      </div>

      {/* Teams */}
      {match ? (
        <div style={{ padding: '6px 8px 0' }}>
          {[
            { team: match.home_team, score: match.home_score, wkts: match.home_wickets },
            { team: match.away_team, score: match.away_score, wkts: match.away_wickets },
          ].map(({ team, score, wkts }) => {
            const win = team === match.winner
            return (
              <div key={team} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
                <span style={{
                  fontSize: 11, fontWeight: win ? 600 : 400,
                  color: win ? 'var(--text)' : 'var(--text-muted)',
                  maxWidth: 104, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {team}
                </span>
                <span style={{
                  fontSize: 11, fontFamily: 'monospace', fontWeight: win ? 600 : 400,
                  color: win ? 'var(--score)' : 'var(--text-dim)', marginLeft: 4, flexShrink: 0,
                }}>
                  {score != null ? `${score}/${wkts ?? 0}` : '-'}
                </span>
              </div>
            )
          })}
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: CH - 26 }}>
          <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>TBD</span>
        </div>
      )}
    </div>
  )
}

// ── Connector line ────────────────────────────────────────────────────────────

function Line({ d }: { d: string }) {
  return <path d={d} fill="none" stroke="var(--border)" strokeWidth={1.5} strokeLinejoin="round" />
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  matches: MatchItem[]
  simId: string
  userTeamName: string | null
}

function detectFormat(labels: Set<string>): 'ipl' | 'semis' | 'quarters' | null {
  if (labels.has('Qualifier 1') || labels.has('Eliminator')) return 'ipl'
  if (labels.has('Semi-final 1') || labels.has('Semi-final 2')) return 'semis'
  if (labels.has('QF 1')) return 'quarters'
  return null
}

export function PlayoffBracket({ matches, simId, userTeamName }: Props) {
  const byLabel: Record<string, MatchItem> = {}
  for (const m of matches) byLabel[m.match_label] = m

  const fmt = detectFormat(new Set(matches.map(m => m.match_label)))
  if (!fmt) return null

  // ── Layout definitions ────────────────────────────────────────────────────

  let svgW: number, svgH: number
  let cards: { label: string; x: number; y: number }[]
  let lines: string[]

  if (fmt === 'semis') {
    //  Final (0,54)   SF1 (230,0)
    //                 SF2 (230,108)
    const finY = (CH + 24) / 2                 // 54
    const sf1cy = CH / 2                        // 42
    const sf2cy = CH + 24 + CH / 2             // 150
    const finCy = finY + CH / 2                // 96
    const mx = CW + CGAP / 2                   // 202

    svgW = CW * 2 + CGAP
    svgH = CH * 2 + 24
    cards = [
      { label: 'Final',        x: 0,          y: finY  },
      { label: 'Semi-final 1', x: CW + CGAP,  y: 0     },
      { label: 'Semi-final 2', x: CW + CGAP,  y: CH+24 },
    ]
    lines = [
      `M${CW},${finCy} H${mx} V${sf1cy} H${CW + CGAP}`,
      `M${CW},${finCy} H${mx} V${sf2cy} H${CW + CGAP}`,
    ]

  } else if (fmt === 'ipl') {
    //  Final (0,0)   Q2 (230,62)   Q1   (460,0)
    //                              Elim (460,124)
    const col1x = CW + CGAP             // 230
    const col2x = CW * 2 + CGAP * 2    // 460
    const mx01  = CW + CGAP / 2        // 202
    const mx12  = col1x + CW + CGAP / 2 // 432

    const q1cy   = CH / 2              // 42
    const elimY  = CH + 40             // 124
    const elimCy = elimY + CH / 2      // 166
    const q2Y    = (q1cy + elimCy) / 2 - CH / 2  // 62
    const q2cy   = q2Y + CH / 2       // 104
    const finCy  = CH / 2             // 42

    svgW = col2x + CW
    svgH = elimY + CH
    cards = [
      { label: 'Final',        x: 0,     y: 0     },
      { label: 'Qualifier 2',  x: col1x, y: q2Y   },
      { label: 'Qualifier 1',  x: col2x, y: 0     },
      { label: 'Eliminator',   x: col2x, y: elimY },
    ]
    lines = [
      // Final ← Q1 winner: straight horizontal
      `M${CW},${finCy} H${col2x}`,
      // Q2 ← Q1 loser: forks down from mx12 to Q2 right edge
      `M${mx12},${q1cy} V${q2cy} H${col1x + CW}`,
      // Q2 ← Eliminator winner
      `M${col2x},${elimCy} H${mx12} V${q2cy} H${col1x + CW}`,
      // Final ← Q2 winner
      `M${col1x},${q2cy} H${mx01} V${finCy} H${CW}`,
    ]

  } else {
    //  Final (0,162)   SF1 (230, 54)   QF1 (460,  0)
    //                                  QF2 (460,108)
    //                  SF2 (230,270)   QF3 (460,216)
    //                                  QF4 (460,324)
    const col1x = CW + CGAP
    const col2x = CW * 2 + CGAP * 2
    const mx01  = CW + CGAP / 2
    const mx12  = col1x + CW + CGAP / 2

    const qf1cy = CH / 2;        const qf2cy = 108 + CH / 2
    const qf3cy = 216 + CH / 2;  const qf4cy = 324 + CH / 2
    const sf1Y  = (qf1cy + qf2cy) / 2 - CH / 2
    const sf2Y  = (qf3cy + qf4cy) / 2 - CH / 2
    const sf1cy = sf1Y + CH / 2
    const sf2cy = sf2Y + CH / 2
    const finY  = (sf1cy + sf2cy) / 2 - CH / 2
    const finCy = finY + CH / 2

    svgW = col2x + CW
    svgH = 324 + CH
    cards = [
      { label: 'Final', x: 0,     y: finY },
      { label: 'SF 1',  x: col1x, y: sf1Y },
      { label: 'SF 2',  x: col1x, y: sf2Y },
      { label: 'QF 1',  x: col2x, y: 0   },
      { label: 'QF 2',  x: col2x, y: 108 },
      { label: 'QF 3',  x: col2x, y: 216 },
      { label: 'QF 4',  x: col2x, y: 324 },
    ]
    lines = [
      `M${col2x},${qf1cy} H${mx12} V${sf1cy} H${col1x + CW}`,
      `M${col2x},${qf2cy} H${mx12} V${sf1cy} H${col1x + CW}`,
      `M${col2x},${qf3cy} H${mx12} V${sf2cy} H${col1x + CW}`,
      `M${col2x},${qf4cy} H${mx12} V${sf2cy} H${col1x + CW}`,
      `M${col1x},${sf1cy} H${mx01} V${finCy} H${CW}`,
      `M${col1x},${sf2cy} H${mx01} V${finCy} H${CW}`,
    ]
  }

  return (
    <div style={{ overflowX: 'auto', overflowY: 'visible', paddingBottom: 4 }}>
      <div style={{ position: 'relative', width: svgW, height: svgH, flexShrink: 0 }}>
        <svg
          style={{ position: 'absolute', inset: 0, overflow: 'visible', pointerEvents: 'none' }}
          viewBox={`0 0 ${svgW} ${svgH}`}
          width={svgW}
          height={svgH}
        >
          {lines.map((d, i) => <Line key={i} d={d} />)}
        </svg>
        {cards.map(({ label, x, y }) => (
          <MatchCard
            key={label}
            label={label}
            match={byLabel[label]}
            x={x} y={y}
            simId={simId}
            userTeam={userTeamName}
          />
        ))}
      </div>
    </div>
  )
}
