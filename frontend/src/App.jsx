import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import EngagementDetail from './pages/EngagementDetail';
import NewEngagement from './pages/NewEngagement';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="engagements" element={<Dashboard />} />
          <Route path="engagements/new" element={<NewEngagement />} />
          <Route path="engagements/:id" element={<EngagementDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
