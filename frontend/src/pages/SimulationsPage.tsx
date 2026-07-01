import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { Spinner } from '@/components/ui/Spinner'
import { SimCard } from '@/components/SimCard'
import type { SimSummary } from '@/types'

const PAGE_SIZE = 20

export function SimulationsPage() {
  const navigate = useNavigate()
  const { clientId } = useAuth()
  const [sims, setSims]         = useState<SimSummary[]>([])
  const [loading, setLoading]   = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore]   = useState(true)
  const offsetRef               = useRef(0)

  useEffect(() => {
    offsetRef.current = 0
    setLoading(true)
    api.listSimulations(clientId, PAGE_SIZE, 0)
      .then(data => {
        setSims(data)
        offsetRef.current = data.length
        setHasMore(data.length === PAGE_SIZE)
      })
      .catch(() => setSims([]))
      .finally(() => setLoading(false))
  }, [clientId])

  async function loadMore() {
    setLoadingMore(true)
    try {
      const data = await api.listSimulations(clientId, PAGE_SIZE, offsetRef.current)
      setSims(prev => [...prev, ...data])
      offsetRef.current += data.length
      setHasMore(data.length === PAGE_SIZE)
    } catch {
      // silently fail — existing items stay
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <button
        className="flex items-center gap-1 text-sm mb-6"
        style={{ color: 'var(--text-muted)' }}
        onClick={() => navigate('/')}
      >
        <ChevronLeft size={14} /> Home
      </button>

      <div className="text-xl font-semibold mb-1" style={{ color: 'var(--text)' }}>All simulations</div>
      <div className="text-sm mb-6" style={{ color: 'var(--text-muted)' }}>Your full simulation history</div>

      {loading ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : sims.length === 0 ? (
        <div className="card p-8 text-center">
          <div className="text-3xl mb-3">🏏</div>
          <div className="text-sm" style={{ color: 'var(--text-dim)' }}>
            No simulations yet. Run your first one from the home page.
          </div>
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-2">
            {sims.map(sim => <SimCard key={sim.sim_id} sim={sim} />)}
          </div>

          {hasMore && (
            <div className="flex justify-center mt-6">
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="btn-outline flex items-center gap-2 px-6 py-2.5 text-sm"
                style={{ opacity: loadingMore ? 0.6 : 1 }}
              >
                {loadingMore ? (
                  <>
                    <span className="spin inline-block w-3.5 h-3.5 rounded-full border-2"
                      style={{ borderColor: 'rgba(255,255,255,0.2)', borderTopColor: 'var(--accent)' }} />
                    Loading…
                  </>
                ) : (
                  'Load more'
                )}
              </button>
            </div>
          )}

          {!hasMore && sims.length > PAGE_SIZE && (
            <div className="text-center mt-6 text-xs" style={{ color: 'var(--text-dim)' }}>
              All {sims.length} simulations loaded
            </div>
          )}
        </>
      )}
    </div>
  )
}
