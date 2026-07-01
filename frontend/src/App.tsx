import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom'
import { useEffect } from 'react'
import { Header } from '@/components/layout/Header'
import { AuthProvider } from '@/contexts/AuthContext'
import { HelpProvider } from '@/contexts/HelpContext'
import { SidebarProvider } from '@/contexts/SidebarContext'
import { AuthModal } from '@/components/AuthModal'
import { HelpModal } from '@/components/HelpModal'
import { Sidebar } from '@/components/Sidebar'
import { HomePage } from '@/pages/HomePage'
import { PlayModePage } from '@/pages/PlayModePage'
import { FunModePage } from '@/pages/FunModePage'
import { ChallengeModePage } from '@/pages/ChallengeModePage'
import { CustomModePage } from '@/pages/CustomModePage'
import { ResultsPage } from '@/pages/ResultsPage'
import { MatchDetailPage } from '@/pages/MatchDetailPage'
import { SimulationsPage } from '@/pages/SimulationsPage'
import { StatsPage } from '@/pages/StatsPage'
import { TitlesPage } from '@/pages/TitlesPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { MultiplayerLobbyPage } from '@/pages/MultiplayerLobbyPage'
import { DraftPage } from '@/pages/DraftPage'
import { PavilionPage } from '@/pages/preview/PavilionPage'
import { FloodlitPage } from '@/pages/preview/FloodlitPage'
import { BroadsheetPage } from '@/pages/preview/BroadsheetPage'
import { EmberPage } from '@/pages/preview/EmberPage'
import { ErrorBoundary } from '@/components/ErrorBoundary'

const HEADER_H = 60

function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])
  return null
}

function AppShell() {
  const { pathname } = useLocation()
  const hideHeader = pathname.startsWith('/multiplayer/draft/')
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <Sidebar />
      {!hideHeader && <Header />}
      {!hideHeader && <div style={{ height: HEADER_H, flexShrink: 0 }} />}
      <AuthModal />
      <HelpModal />
      <ScrollToTop />
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
          <Route path="/stats"                               element={<StatsPage />} />
          <Route path="/stats/titles"                        element={<TitlesPage />} />
          <Route path="/profile"                             element={<ProfilePage />} />
          <Route path="/multiplayer"                         element={<MultiplayerLobbyPage />} />
          <Route path="/multiplayer/draft/:roomId"           element={<DraftPage />} />
          <Route path="/join/:roomId"                        element={<MultiplayerLobbyPage />} />
          <Route path="/preview/pavilion"                    element={<PavilionPage />} />
          <Route path="/preview/floodlit"                    element={<FloodlitPage />} />
          <Route path="/preview/broadsheet"                  element={<BroadsheetPage />} />
          <Route path="/preview/ember"                       element={<EmberPage />} />
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
          <SidebarProvider>
            <AppShell />
          </SidebarProvider>
        </HelpProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
