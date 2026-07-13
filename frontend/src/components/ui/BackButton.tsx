import { ChevronLeft } from 'lucide-react'

export function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button className="flex items-center gap-1 text-sm mb-5" style={{ color: 'var(--text-muted)' }} onClick={onClick}>
      <ChevronLeft size={14} /> Back
    </button>
  )
}
