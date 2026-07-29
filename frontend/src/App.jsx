import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider } from './lib/config.jsx';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Engagements from './pages/Engagements';
import EngagementDetail from './pages/EngagementDetail';
import NewEngagement from './pages/NewEngagement';
import ClientDetail from './pages/ClientDetail';
import Analytics from './pages/Analytics';
import Playbook from './pages/Playbook';
import Inbox from './pages/Inbox';
import ProductionPlan from './pages/ProductionPlan';
import Settings, { SettingsIndex } from './pages/Settings';
import ProviderSettings from './pages/ProviderSettings';
import LabAgents from './pages/LabAgents';
import LabTranscription from './pages/LabTranscription';
import Recordings from './pages/Recordings';
import RecordingDetail from './pages/RecordingDetail';
import Boardroom from './pages/Boardroom';
import TalentDirectory from './pages/TalentDirectory';
import Casting from './pages/Casting';
import TalentPortal from './pages/TalentPortal';

function App() {
  return (
    <ConfigProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          {/* The talent portal is a separate surface: no internal Layout, no
              internal nav, no shared session assumptions. */}
          <Route path="/talent/login" element={<TalentPortal />} />
          <Route path="/talent/join" element={<TalentPortal />} />
          <Route path="/talent/set-password" element={<TalentPortal />} />
          <Route path="/talent/portal" element={<TalentPortal />} />
          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="engagements" element={<Engagements />} />
            <Route path="engagements/new" element={<NewEngagement />} />
            <Route path="engagements/:id" element={<EngagementDetail />} />
            <Route path="engagements/:id/production" element={<ProductionPlan />} />
            <Route path="clients/:id" element={<ClientDetail />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="playbook" element={<Playbook />} />
            <Route path="inbox" element={<Inbox />} />
            <Route path="settings" element={<Settings />}>
              <Route index element={<SettingsIndex />} />
              <Route path="providers" element={<ProviderSettings />} />
              <Route path="lab/agents" element={<LabAgents />} />
              <Route path="lab/speech" element={<LabTranscription />} />
            </Route>
            <Route path="recordings" element={<Recordings />} />
            <Route path="recordings/:id" element={<RecordingDetail />} />
            <Route path="boardroom" element={<Boardroom />} />
            <Route path="boardroom/:id" element={<Boardroom />} />
            <Route path="talent" element={<TalentDirectory />} />
            <Route path="engagements/:id/casting" element={<Casting />} />

            {/* Pre-reorganisation paths. Kept so bookmarks, the demo script and
                anything already linking to them still land somewhere sensible. */}
            <Route path="requirements" element={<Navigate to="/playbook" replace />} />
            <Route path="authoritative" element={<Navigate to="/playbook" replace />} />
            <Route path="providers" element={<Navigate to="/settings/providers" replace />} />
            <Route path="lab/agents" element={<Navigate to="/settings/lab/agents" replace />} />
            <Route path="lab/transcription" element={<Navigate to="/settings/lab/speech" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
