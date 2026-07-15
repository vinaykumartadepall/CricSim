import { useSearchParams } from 'react-router-dom'

/**
 * Keeps the URL as the durable record of "where am I" in the mode wizards
 * (tournament_id + team_id + step), so reload/back/forward/history land back
 * in the right place instead of resetting to step 1 - the same recurring bug
 * class as retrySimId/room_id elsewhere in the app. Swaps are deliberately
 * NOT included (retrySimId remains the durable path for those, since they
 * only exist once a sim has actually been run).
 *
 * One hook shared by Fun/Challenge/Custom mode - previously three identical
 * page-local copies.
 */
export function useWizardUrlState<Step extends string>(setStep: (step: Step) => void) {
  const [searchParams, setSearchParams] = useSearchParams()

  function updateUrlParams(patch: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams)
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) next.delete(k)
      else next.set(k, v)
    }
    setSearchParams(next, { replace: true })
  }

  function goToStep(newStep: Step, extra?: Record<string, string | undefined>) {
    setStep(newStep)
    updateUrlParams({ step: newStep, ...extra })
  }

  return { searchParams, updateUrlParams, goToStep }
}
