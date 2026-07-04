import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useLocation } from 'react-router-dom'
import { X, ChevronLeft, ChevronRight } from 'lucide-react'
import { useHelp } from '@/contexts/HelpContext'
import { findMatchedHelp, hasSeenHelp, markHelpSeen } from '@/config/helpContent'

// Pages that manage their own step-based help triggers — skip pathname auto-open for these
const STEP_BASED_PATHS = ['/fun', '/challenge', '/custom']

export function HelpModal() {
  const { helpOpen, closeHelp, openHelp, helpInitialSlide, helpSingleSlide } = useHelp()
  const { pathname } = useLocation()
  const [index, setIndex] = useState(0)

  const matched = findMatchedHelp(pathname)
  const content = matched?.content ?? null

  const isStepBased = STEP_BASED_PATHS.some(p => pathname === p || pathname.startsWith(p + '/'))

  // Reset to the requested initial slide whenever the modal opens
  useEffect(() => {
    if (helpOpen) setIndex(helpInitialSlide)
  }, [helpOpen, helpInitialSlide])

  // Reset to first slide on route change
  useEffect(() => { setIndex(0) }, [pathname])

  // Auto-open on page arrival, first visit only (non-stepped pages only).
  // Keyed by the resolved content key (e.g. '/results'), NOT the raw pathname —
  // dynamic routes like /results/:simId have a different pathname every time,
  // which would defeat "first visit only" entirely if used directly.
  // The "simulation still running" state lives on its own route (SimulatingPage)
  // that has no registered help content, so there's no risk of popping up mid-run.
  useEffect(() => {
    if (!matched || isStepBased) return
    if (!hasSeenHelp(matched.key)) {
      markHelpSeen(matched.key)
      openHelp(0, false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname])

  if (!helpOpen || !content) return null

  const total = content.slides.length
  const slide = content.slides[index] ?? content.slides[0]
  const isFirst = index === 0
  const isLast = index === total - 1

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
      onClick={e => { if (e.target === e.currentTarget) closeHelp() }}
    >
      <div
        className="w-full max-w-sm rounded-2xl overflow-hidden fade-in"
        style={{ background: 'var(--surface)', border: '1px solid var(--border)', boxShadow: '0 16px 48px rgba(0,0,0,0.5)' }}
      >
        {/* Top bar: section title + close */}
        <div className="flex items-center justify-between px-5 pt-4 pb-3" style={{ borderBottom: '1px solid var(--border)' }}>
          <h2 className="text-lg font-bold m-0" style={{ color: 'var(--text)', letterSpacing: '-0.3px' }}>
            {content.title}
          </h2>
          <button onClick={closeHelp} style={{ color: 'var(--text-dim)', lineHeight: 0, flexShrink: 0 }}>
            <X size={15} />
          </button>
        </div>

        {/* Navigation row — hidden in single-slide mode */}
        {!helpSingleSlide && (
          <div className="flex items-center justify-between px-4 pt-4 pb-0">
            <button
              onClick={() => setIndex(i => i - 1)}
              disabled={isFirst}
              className="p-1.5 rounded-lg transition-all"
              style={{
                color: isFirst ? 'var(--border)' : 'var(--accent)',
                background: isFirst ? 'transparent' : 'rgba(59,130,246,0.08)',
              }}
            >
              <ChevronLeft size={18} />
            </button>

            {/* Dot indicators */}
            <div className="flex items-center gap-1.5">
              {content.slides.map((_, i) => (
                <button
                  key={i}
                  onClick={() => setIndex(i)}
                  style={{
                    width: i === index ? 16 : 6,
                    height: 6,
                    borderRadius: 3,
                    background: i === index ? 'var(--accent)' : 'var(--border)',
                    transition: 'all 200ms ease',
                    flexShrink: 0,
                  }}
                />
              ))}
            </div>

            <button
              onClick={() => setIndex(i => i + 1)}
              disabled={isLast}
              className="p-1.5 rounded-lg transition-all"
              style={{
                color: isLast ? 'var(--border)' : 'var(--accent)',
                background: isLast ? 'transparent' : 'rgba(59,130,246,0.08)',
              }}
            >
              <ChevronRight size={18} />
            </button>
          </div>
        )}

        {/* Slide content */}
        <div className="px-5 pt-4 pb-2" style={{ minHeight: 140 }}>
          {/* Slide header */}
          <div className="text-base font-semibold mb-3" style={{ color: 'var(--text)' }}>
            {slide.header}
          </div>

          {/* Instructions list */}
          <ul className="m-0 p-0 list-none flex flex-col gap-2">
            {slide.instructions.map((inst, i) => (
              <li key={i} className="flex items-start gap-2 text-sm" style={{ color: 'var(--text-muted)' }}>
                <span
                  className="mt-0.5 w-4 h-4 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
                  style={{ background: 'rgba(59,130,246,0.12)', color: 'var(--accent)' }}
                >
                  {i + 1}
                </span>
                {inst}
              </li>
            ))}
          </ul>

          {/* Tip */}
          {slide.tip && (
            <div
              className="mt-4 px-3 py-2.5 rounded-lg text-xs"
              style={{ background: 'rgba(245,158,11,0.08)', color: 'var(--score)', border: '1px solid rgba(245,158,11,0.2)' }}
            >
              💡 {slide.tip}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 flex gap-2">
          {helpSingleSlide || isLast ? (
            <button
              onClick={closeHelp}
              className="w-full py-2.5 rounded-xl text-sm font-semibold"
              style={{ background: 'var(--accent)', color: 'var(--bg)' }}
            >
              Got it
            </button>
          ) : (
            <>
              <button
                onClick={closeHelp}
                className="flex-1 py-2.5 rounded-xl text-sm font-medium"
                style={{ background: 'var(--surface-2)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}
              >
                Skip
              </button>
              <button
                onClick={() => setIndex(i => i + 1)}
                className="flex-1 py-2.5 rounded-xl text-sm font-semibold"
                style={{ background: 'var(--accent)', color: 'var(--bg)' }}
              >
                Next
              </button>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
