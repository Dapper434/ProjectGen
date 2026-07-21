import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { LogOut, LayoutDashboard, BriefcaseBusiness, BarChart3 } from 'lucide-react';
import { useEffect, useState } from 'react';
import SearchBar from './SearchBar';

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [user, setUser] = useState(null);

  useEffect(() => {
    const fetchUser = async () => {
      try {
        const res = await fetch('http://localhost:5000/api/me', {credentials: 'include'});
        if (res.ok) {
          const data = await res.json();
          setUser(data);
        } else {
          navigate('/login');
        }
      } catch (err) {
        navigate('/login');
      }
    };
    fetchUser();
  }, [navigate]);

  const handleLogout = async () => {
    await fetch('http://localhost:5000/api/logout', { method: 'POST', credentials: 'include' });
    navigate('/login');
  };

  if (!user) return <div className="min-h-screen bg-zinc-950 text-zinc-50 flex items-center justify-center">Loading...</div>;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 flex">
      {/* Sidebar */}
      <aside className="w-64 shrink-0 min-h-screen border-r border-zinc-800 p-6 flex flex-col">
        <div className="flex items-center gap-2 mb-12">
          <div className="w-8 h-8 bg-indigo-600 rounded-sm flex items-center justify-center font-bold text-white tracking-tighter">
            F.OS
          </div>
          <span className="font-semibold text-lg tracking-tight">FactoryOS</span>
        </div>
        
        <nav className="flex-1 space-y-2">
          <button 
            onClick={() => navigate('/dashboard')}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-md transition-colors ${location.pathname === '/dashboard' ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'}`}
          >
            <LayoutDashboard size={18} />
            <span className="font-medium text-sm">Dashboard</span>
          </button>

          <button
            onClick={() => navigate('/engagements')}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-md transition-colors ${location.pathname === '/engagements' || location.pathname.startsWith('/engagements/') ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'}`}
          >
            <BriefcaseBusiness size={18} />
            <span className="font-medium text-sm">Engagements</span>
          </button>

        </nav>

        <div className="mt-auto border-t border-zinc-800 pt-6">
          <div className="flex items-center justify-between">
            <div className="flex flex-col">
              <span className="text-sm font-medium">{user.username}</span>
              <span className="text-xs text-zinc-500">{user.role}</span>
            </div>
            <button onClick={handleLogout} className="text-zinc-400 hover:text-white">
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </aside>
      
      {/* Main Content */}
      <div className="flex-1 overflow-auto bg-zinc-950">
        <div className="sticky top-0 z-10 bg-zinc-950/95 backdrop-blur border-b border-zinc-800 px-8 py-3">
          <SearchBar />
        </div>
        <Outlet context={{ user }} />
      </div>
    </div>
  );
}
