import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="flex flex-col items-center justify-center min-h-[calc(100vh-64px)] px-4 text-center">
        <div className="text-5xl mb-6" style={{ color: 'var(--loss)' }}>⚠</div>
        <div className="text-lg font-semibold mb-2" style={{ color: 'var(--text)' }}>
          Something went wrong
        </div>
        <div className="text-sm mb-1" style={{ color: 'var(--text-muted)' }}>
          An unexpected error occurred. Try refreshing the page.
        </div>
        <div
          className="text-xs mt-3 mb-6 px-3 py-2 rounded font-mono max-w-sm break-all"
          style={{ background: 'var(--surface-2)', color: 'var(--text-dim)' }}
        >
          {error.message}
        </div>
        <div className="flex gap-3">
          <button className="btn-outline" onClick={() => window.location.reload()}>
            Refresh page
          </button>
          <button className="btn-accent" onClick={() => { this.setState({ error: null }); window.location.href = '/' }}>
            Back to home
          </button>
        </div>
      </div>
    )
  }
}
