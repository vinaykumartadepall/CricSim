import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Header } from '@/components/layout/Header'
import { AuthProvider } from '@/contexts/AuthContext'
import { AuthModal } from '@/components/AuthModal'
import { HomePage } from '@/pages/HomePage'
import { FunModePage } from '@/pages/FunModePage'
import { ChallengeModePage } from '@/pages/ChallengeModePage'
import { ResultsPage } from '@/pages/ResultsPage'
import { MatchDetailPage } from '@/pages/MatchDetailPage'
import { SimulationsPage } from '@/pages/SimulationsPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { useTheme } from '@/hooks/useTheme'

function AppShell() {
  useTheme()

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <Header />
      <AuthModal />
      <ErrorBoundary>
        <Routes>
          <Route path="/"                                    element={<HomePage />} />
          <Route path="/fun"                                 element={<FunModePage />} />
          <Route path="/challenge"                           element={<ChallengeModePage />} />
          <Route path="/results/:simId"                      element={<ResultsPage />} />
          <Route path="/results/:simId/matches/:matchId"     element={<MatchDetailPage />} />
          <Route path="/simulations"                         element={<SimulationsPage />} />
          <Route path="*"                                    element={<NotFoundPage />} />
        </Routes>
      </ErrorBoundary>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppShell />
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
