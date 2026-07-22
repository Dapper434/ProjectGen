import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { LayoutDashboard, Layers, BarChart3, ClipboardCheck, Inbox, LogOut, Plus } from 'lucide-react';
import { useEffect, useState } from 'react';
import SearchBar from './SearchBar';

const navItems = [
  { icon: LayoutDashboard, label: 'Dashboard', to: '/dashboard' },
  { icon: Layers, label: 'Engagements', to: '/engagements' },
  { icon: Inbox, label: 'Inbox', to: '/inbox' },
  { icon: ClipboardCheck, label: 'Requirements', to: '/requirements' },
];

const adminNavItems = [
  { icon: BarChart3, label: 'Analytics', to: '/analytics' },
];

export default function Layout() {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [inboxCount, setInboxCount] = useState(0);

  // Pending Fathom transcripts badge — refreshed on a slow poll so a meeting
  // that just ended surfaces without a manual reload.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const fetchCount = async () => {
      try {
        const res = await fetch('/api/inbox?status=pending', { credentials: 'include' });
        if (res.ok && !cancelled) setInboxCount((await res.json()).pending_count || 0);
      } catch { /* backend down — badge just stays as-is */ }
    };
    fetchCount();
    const timer = setInterval(fetchCount, 60000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [user]);

  useEffect(() => {
    const fetchUser = async () => {
      try {
        const res = await fetch('/api/me', { credentials: 'include' });
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
    await fetch('/api/logout', { method: 'POST', credentials: 'include' });
    navigate('/login');
  };

  if (!user) {
    return <div className="h-screen bg-[#0a0a0a] text-[#a3a39c] flex items-center justify-center text-sm">Loading…</div>;
  }

  const initials = user.username.slice(0, 2).toUpperCase();

  return (
    <div className="flex h-screen bg-[#0a0a0a] overflow-hidden font-sans">
      {/* Sidebar */}
      <aside className="w-[210px] shrink-0 flex flex-col" style={{ background: 'linear-gradient(180deg, #0d0d0d 0%, #0a0a0a 100%)', borderRight: '1px solid #242424' }}>
        {/* Logo */}
        <div className="px-5 pt-6 pb-5">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)', boxShadow: '0 0 12px rgba(201,151,31,0.4)' }}>
              <span className="text-white font-bold text-xs tracking-tight">F.OS</span>
            </div>
            <span className="text-[#f7f5ef] font-semibold text-[15px] tracking-tight">FactoryOS</span>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-2 flex flex-col gap-0.5">
          {[...navItems, ...(user.role === 'Admin' ? adminNavItems : [])].map(({ icon: Icon, label, to }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13px] font-medium transition-all duration-150 group ${
                  isActive
                    ? 'text-[#f7f5ef]'
                    : 'text-[#8a8a83] hover:text-[#d6d4c9] hover:bg-[#ffffff06]'
                }`
              }
              style={({ isActive }) => isActive ? {
                background: 'linear-gradient(90deg, rgba(201,151,31,0.18) 0%, rgba(201,151,31,0.06) 100%)',
                borderLeft: '2px solid #c9971f',
                paddingLeft: '10px',
              } : { borderLeft: '2px solid transparent' }}
            >
              {({ isActive }) => (
                <>
                  <Icon size={16} className={isActive ? 'text-[#e8c34a]' : 'text-[#5c5c55] group-hover:text-[#8a8a83]'} />
                  {label}
                  {to === '/inbox' && inboxCount > 0 && (
                    <span className="ml-auto text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-[#c9971f]/20 text-[#e8c34a] border border-[#c9971f]/30">
                      {inboxCount}
                    </span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Bottom */}
        <div className="px-3 py-4 mt-auto" style={{ borderTop: '1px solid #242424' }}>
          <button
            onClick={handleLogout}
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] text-[#8a8a83] hover:text-rose-500 hover:bg-rose-500/5 transition-all w-full mb-3"
          >
            <LogOut size={14} className="text-[#5c5c55]" />
            Sign out
          </button>
          <div className="px-3 py-2.5 rounded-lg flex items-center gap-2.5" style={{ background: '#151515', border: '1px solid #242424' }}>
            <div className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-[10px] font-bold text-[#e8c34a]"
              style={{ background: 'rgba(201,151,31,0.2)', border: '1px solid rgba(201,151,31,0.3)' }}>
              {initials}
            </div>
            <div className="min-w-0">
              <p className="text-[12px] font-medium text-[#d6d4c9] truncate">{user.username}</p>
              <p className="text-[10px] text-[#5c5c55] truncate">{user.role}</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main column */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar with search */}
        <header className="h-[52px] shrink-0 flex items-center px-6 gap-3" style={{ borderBottom: '1px solid #242424', background: '#0a0a0a' }}>
          <SearchBar />
          <div className="ml-auto">
            <button
              onClick={() => navigate('/engagements/new')}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-white text-[13px] font-medium transition-all hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)', boxShadow: '0 2px 12px rgba(201,151,31,0.3)' }}
            >
              <Plus size={13} />
              New Engagement
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <Outlet context={{ user }} />
        </main>
      </div>
    </div>
  );
}
