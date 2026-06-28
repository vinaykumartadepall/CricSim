import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { Spinner } from '@/components/ui/Spinner'
import { SimCard } from '@/components/SimCard'
import type { SimSummary } from '@/types'

export function SimulationsPage() {
  const navigate = useNavigate()
  const { clientId } = useAuth()
  const [sims, setSims] = useState<SimSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listSimulations(clientId, 100)
      .then(data => setSims(data))
      .catch(() => setSims([]))
      .finally(() => setLoading(false))
  }, [clientId])

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <button
        className="flex items-center gap-1 text-sm mb-6"
        style={{ color: 'var(--text-muted)' }}
        onClick={() => navigate('/')}
      >
        <ChevronLeft size={14} /> Back to home
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
        <div className="flex flex-col gap-2">
          {sims.map(sim => <SimCard key={sim.sim_id} sim={sim} />)}
        </div>
      )}
    </div>
  )
}
