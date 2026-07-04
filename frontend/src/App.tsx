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
import { SimulatingPage } from '@/pages/SimulatingPage'
import { MatchDetailPage } from '@/pages/MatchDetailPage'
import { SimulationsPage } from '@/pages/SimulationsPage'
import { StatsPage } from '@/pages/StatsPage'
import { TitlesPage } from '@/pages/TitlesPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { AdminPage } from '@/pages/AdminPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { MultiplayerLobbyPage } from '@/pages/MultiplayerLobbyPage'
import { DraftPage } from '@/pages/DraftPage'
import { ErrorBoundary } from '@/components/ErrorBoundary'

const HEADER_H = 60

function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
    // Safety net: several components (Sidebar, modals) independently lock/restore
    // document.body.style.overflow with no coordination between them, so a stale
    // capture-restore can leave scrolling stuck disabled on an unrelated later page.
    // A fresh navigation should always be scrollable regardless of what leaked before.
    document.body.style.overflow = ''
  }, [pathname])
  return null
}

function AppShell() {
  const { pathname } = useLocation()
  const hideHeader = pathname.startsWith('/multiplayer/draft/')
  // Draft rooms and theme-preview mockups intentionally use the full viewport width.
  const isFullBleed = hideHeader || pathname.startsWith('/preview/')
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <Sidebar />
      {!hideHeader && <Header />}
      {!hideHeader && <div style={{ height: HEADER_H, flexShrink: 0 }} />}
      <AuthModal />
      <HelpModal />
      <ScrollToTop />
      <ErrorBoundary>
        <div className={isFullBleed ? undefined : 'mx-auto w-full'} style={isFullBleed ? undefined : { maxWidth: 1400 }}>
        <Routes>
          <Route path="/"                                    element={<HomePage />} />
          <Route path="/play"                                element={<PlayModePage />} />
          <Route path="/fun"                                 element={<FunModePage />} />
          <Route path="/challenge"                           element={<ChallengeModePage />} />
          <Route path="/custom"                              element={<CustomModePage />} />
          <Route path="/simulating/:simId"                   element={<SimulatingPage />} />
          <Route path="/results/:simId"                      element={<ResultsPage />} />
          <Route path="/results/:simId/matches/:matchId"     element={<MatchDetailPage />} />
          <Route path="/simulations"                         element={<SimulationsPage />} />
          <Route path="/stats"                               element={<StatsPage />} />
          <Route path="/stats/titles"                        element={<TitlesPage />} />
          <Route path="/profile"                             element={<ProfilePage />} />
          <Route path="/admin"                                element={<AdminPage />} />
          <Route path="/multiplayer"                         element={<MultiplayerLobbyPage />} />
          <Route path="/multiplayer/draft/:roomId"           element={<DraftPage />} />
          <Route path="/join/:roomId"                        element={<MultiplayerLobbyPage />} />
          <Route path="*"                                    element={<NotFoundPage />} />
        </Routes>
        </div>
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
