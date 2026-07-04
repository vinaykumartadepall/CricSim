import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, RotateCw } from 'lucide-react'
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
  const [refreshing, setRefreshing] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore]   = useState(true)
  const offsetRef               = useRef(0)

  const fetchFirstPage = useCallback(async () => {
    offsetRef.current = 0
    try {
      const data = await api.listSimulations(clientId, PAGE_SIZE, 0)
      setSims(data)
      offsetRef.current = data.length
      setHasMore(data.length === PAGE_SIZE)
    } catch {
      setSims([])
    }
  }, [clientId])

  useEffect(() => {
    setLoading(true)
    fetchFirstPage().finally(() => setLoading(false))
  }, [fetchFirstPage])

  async function handleRefresh() {
    setRefreshing(true)
    try {
      // Force a minimum visible duration — the fetch usually resolves fast
      // enough that the spin/color change never actually gets a chance to paint.
      await Promise.all([fetchFirstPage(), new Promise(r => setTimeout(r, 400))])
    } finally {
      setRefreshing(false)
    }
  }

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
    <div className="max-w-2xl mx-auto px-6 py-8">
      <button
        className="flex items-center gap-1 text-sm mb-6"
        style={{ color: 'var(--text-muted)' }}
        onClick={() => navigate('/')}
      >
        <ChevronLeft size={14} /> Home
      </button>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
        <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>All simulations</div>
        <button
          onClick={handleRefresh}
          disabled={refreshing || loading}
          title="Refresh"
          className="icon-btn"
        >
          <RotateCw size={14} className={refreshing ? 'spin' : ''} />
        </button>
      </div>
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
