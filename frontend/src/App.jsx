import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import EngagementDetail from './pages/EngagementDetail';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="rate-card" element={<div className="p-8 text-white">Rate Card Placeholder</div>} />
          <Route path="engagements/:id" element={<EngagementDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
