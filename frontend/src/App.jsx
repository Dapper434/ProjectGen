import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Engagements from './pages/Engagements';
import EngagementDetail from './pages/EngagementDetail';
import NewEngagement from './pages/NewEngagement';
import ClientDetail from './pages/ClientDetail';
import Analytics from './pages/Analytics';
import Requirements from './pages/Requirements';
import Inbox from './pages/Inbox';
import ProductionPlan from './pages/ProductionPlan';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="engagements" element={<Engagements />} />
          <Route path="engagements/new" element={<NewEngagement />} />
          <Route path="engagements/:id" element={<EngagementDetail />} />
          <Route path="engagements/:id/production" element={<ProductionPlan />} />
          <Route path="clients/:id" element={<ClientDetail />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="requirements" element={<Requirements />} />
          <Route path="inbox" element={<Inbox />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
