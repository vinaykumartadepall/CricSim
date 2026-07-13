// Label/value line on the wizard confirm step. Pass accentColor to highlight the value.
export function ConfirmRow({ label, value, accentColor }: {
  label: string
  value: string
  accentColor?: string
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="text-sm font-medium" style={{ color: accentColor ?? 'var(--text)' }}>{value}</span>
    </div>
  )
}
