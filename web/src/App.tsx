import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { NavBar } from './components/NavBar'
import { AuditLedger } from './pages/AuditLedger'
import { DecisionDetail } from './pages/DecisionDetail'
import { LiveTriage } from './pages/LiveTriage'
import { Results } from './pages/Results'

export function App() {
  return (
    <BrowserRouter>
      <NavBar />
      <Routes>
        <Route path="/" element={<LiveTriage />} />
        <Route path="/decisions/:decisionId" element={<DecisionDetail />} />
        <Route path="/ledger" element={<AuditLedger />} />
        <Route path="/results" element={<Results />} />
      </Routes>
    </BrowserRouter>
  )
}
