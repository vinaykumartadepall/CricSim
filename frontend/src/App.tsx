import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Header } from '@/components/layout/Header'
import { AuthProvider } from '@/contexts/AuthContext'
import { HelpProvider } from '@/contexts/HelpContext'
import { AuthModal } from '@/components/AuthModal'
import { HelpModal } from '@/components/HelpModal'
import { HomePage } from '@/pages/HomePage'
import { PlayModePage } from '@/pages/PlayModePage'
import { FunModePage } from '@/pages/FunModePage'
import { ChallengeModePage } from '@/pages/ChallengeModePage'
import { CustomModePage } from '@/pages/CustomModePage'
import { ResultsPage } from '@/pages/ResultsPage'
import { MatchDetailPage } from '@/pages/MatchDetailPage'
import { SimulationsPage } from '@/pages/SimulationsPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { MultiplayerLobbyPage } from '@/pages/MultiplayerLobbyPage'
import { DraftPage } from '@/pages/DraftPage'
import { ErrorBoundary } from '@/components/ErrorBoundary'
function AppShell() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <Header />
      <AuthModal />
      <HelpModal />
      <ErrorBoundary>
        <Routes>
          <Route path="/"                                    element={<HomePage />} />
          <Route path="/play"                                element={<PlayModePage />} />
          <Route path="/fun"                                 element={<FunModePage />} />
          <Route path="/challenge"                           element={<ChallengeModePage />} />
          <Route path="/custom"                              element={<CustomModePage />} />
          <Route path="/results/:simId"                      element={<ResultsPage />} />
          <Route path="/results/:simId/matches/:matchId"     element={<MatchDetailPage />} />
          <Route path="/simulations"                         element={<SimulationsPage />} />
          <Route path="/multiplayer"                         element={<MultiplayerLobbyPage />} />
          <Route path="/multiplayer/draft/:roomId"           element={<DraftPage />} />
          <Route path="/join/:roomId"                        element={<MultiplayerLobbyPage />} />
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
        <HelpProvider>
          <AppShell />
        </HelpProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
