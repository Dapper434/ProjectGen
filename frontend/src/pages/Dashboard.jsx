import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { Layers, ArrowUpRight, Zap, Clock, AlertCircle } from 'lucide-react';
import { stageMeta, clientColor, formatId, timeAgo } from '../lib/engagements';

const AGENT_COLORS = {
  'Brief Generator': '#a16207',
  'Proposal Generator': '#0369a1',
  'Signal Extractor': '#b45309',
  'Account Manager (Human)': '#047857',
};

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { user } = useOutletContext();
  const isAccountManager = user?.role === 'Account Manager';
  const [engagements, setEngagements] = useState([]);
  const [analytics, setAnalytics] = useState(null);

  useEffect(() => {
    fetch('/api/engagements', { credentials: 'include' })
      .then(res => (res.ok ? res.json() : []))
      .then(setEngagements)
      .catch(err => console.error(err));
    fetch('/api/analytics', { credentials: 'include' })
      .then(res => (res.ok ? res.json() : null))
      .then(setAnalytics)
      .catch(err => console.error(err));
  }, []);

  const counts = useMemo(() => {
    const c = {};
    for (const eng of engagements) c[eng.status] = (c[eng.status] || 0) + 1;
    return c;
  }, [engagements]);

  const reviewCount = (counts.proposal_ready || 0) + (counts.in_review || 0);
  const actionCount = (counts.brief_ready || 0) + (counts.awaiting_review_transcript || 0);
  const activeCount = engagements.length - (counts.approved || 0);

  const turnaround = analytics?.turnaround;
  const hours = h => (h == null ? '—' : `${h} hrs`);

  const producerStats = [
    { label: 'Active Engagements', value: activeCount, icon: Layers, color: '#c9971f', sub: `${counts.awaiting_transcript || 0} awaiting transcript` },
    { label: 'Awaiting Action', value: actionCount, icon: AlertCircle, color: '#f59e0b', sub: 'Brief ready engagements' },
    { label: 'Avg. Turnaround', value: hours(turnaround?.transcript_to_brief_hours), icon: Clock, color: '#0ea5e9', sub: 'Transcript → Brief' },
  ];

  const managerStats = [
    { label: 'Proposals to Review', value: reviewCount, icon: AlertCircle, color: '#f59e0b', sub: reviewCount > 0 ? 'Ready now' : 'Nothing waiting' },
    { label: 'Approved Proposals', value: counts.approved || 0, icon: Layers, color: '#10b981', sub: 'Ready to send to client' },
    { label: 'Avg. Review Time', value: hours(turnaround?.proposal_to_approval_hours), icon: Clock, color: '#0ea5e9', sub: 'Proposal → Approval' },
  ];

  const dashboardStats = isAccountManager ? managerStats : producerStats;

  // AM sees the review queue front and center; producers see the latest work.
  const listSource = isAccountManager
    ? engagements.filter(e => e.status === 'proposal_ready' || e.status === 'in_review')
    : engagements;
  const recentEngagements = [...listSource].sort((a, b) => b.id - a.id).slice(0, 5);

  const activityFeed = (analytics?.recent_activity || []).slice(0, 5);

  return (
    <div className="px-8 py-7">
      {/* Greeting */}
      <div className="mb-8">
        <h1 className="text-[#f7f5ef] text-2xl font-semibold mb-1">{greeting()}, {user?.username ?? 'there'}</h1>
        <p className="text-[13px] text-[#8a8a83]">
          {isAccountManager
            ? <>You have <span className="text-[#e8c34a]">{reviewCount} proposal{reviewCount === 1 ? '' : 's'}</span> ready for your review.</>
            : <>You have <span className="text-[#e8c34a]">{actionCount} engagement{actionCount === 1 ? '' : 's'}</span> ready for the next step.</>}
        </p>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mb-8">
        {dashboardStats.map(({ label, value, icon: Icon, color, sub }) => (
          <div key={label} className="rounded-xl p-5 transition-all"
            style={{ background: 'linear-gradient(145deg, #151515 0%, #101010 100%)', border: '1px solid #242424' }}>
            <div className="flex items-center justify-between mb-3">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center"
                style={{ background: color + '18', border: `1px solid ${color}30` }}>
                <Icon size={14} style={{ color }} />
              </div>
            </div>
            <p className="text-[22px] font-semibold text-[#f7f5ef] leading-none mb-0.5">{value}</p>
            <p className="text-[12px] text-[#8a8a83] mb-1">{label}</p>
            <p className="text-[11px] text-[#5c5c55] font-mono">{sub}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
        {/* Recent Engagements */}
        <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
          <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
            <div className="flex items-center gap-2">
              <Layers size={14} className="text-[#8a8a83]" />
              <span className="text-[14px] font-semibold text-[#f2f0e8]">{isAccountManager ? 'Proposals awaiting review' : 'Recent Engagements'}</span>
            </div>
            <button
              onClick={() => navigate('/engagements')}
              className="flex items-center gap-1 text-[12px] text-[#c9971f] hover:text-[#e8c34a] transition-colors"
            >
              View all <ArrowUpRight size={12} />
            </button>
          </div>
          {recentEngagements.length === 0 ? (
            <div className="px-5 py-10 text-center">
              <p className="text-[13px] text-[#8a8a83]">
                {isAccountManager ? 'No proposals waiting for review.' : 'No engagements yet — create the first one.'}
              </p>
            </div>
          ) : (
            <div className="divide-y" style={{ borderColor: '#191919' }}>
              {recentEngagements.map(eng => {
                const col = clientColor(eng.client_name);
                const meta = stageMeta(eng.status);
                return (
                  <div
                    key={eng.id}
                    onClick={() => navigate(`/engagements/${eng.id}`)}
                    className="flex items-center gap-3 px-5 py-3.5 cursor-pointer hover:bg-[#1a1a1a] transition-colors group"
                  >
                    <div className="w-8 h-8 rounded-full flex items-center justify-center text-[12px] font-bold shrink-0"
                      style={{ background: col + '22', border: `1.5px solid ${col}44`, color: col }}>
                      {eng.client_name.charAt(0).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-medium text-[#d6d4c9] truncate">{eng.client_name}</p>
                      <p className="text-[11px] text-[#5c5c55] font-mono">Engagement {formatId(eng.id)}</p>
                    </div>
                    <span className="text-[10px] font-mono font-semibold px-2 py-1 rounded-md shrink-0"
                      style={{ color: meta.color, background: meta.bg }}>
                      {meta.label}
                    </span>
                    <ArrowUpRight size={13} className="text-[#5c5c55] group-hover:text-[#c9971f] transition-colors shrink-0" />
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right column */}
        <div className="flex flex-col gap-5">
          {/* Quick Actions */}
          <div className="rounded-xl p-5" style={{ background: '#141414', border: '1px solid #242424' }}>
            <p className="text-[14px] font-semibold text-[#f2f0e8] mb-4">Quick Actions</p>
            <div className="flex flex-col gap-2">
              <button
                onClick={() => navigate('/engagements/new')}
                className="flex items-center gap-2.5 px-3.5 py-3 rounded-lg text-[13px] font-medium text-white transition-all hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)', boxShadow: '0 2px 12px rgba(201,151,31,0.25)' }}
              >
                <Zap size={14} />
                New Engagement
              </button>
              <button
                onClick={() => navigate('/engagements')}
                className="flex items-center gap-2.5 px-3.5 py-3 rounded-lg text-[13px] font-medium text-[#d6d4c9] transition-all hover:bg-[#1a1a1a]"
                style={{ border: '1px solid #242424' }}
              >
                <Layers size={14} className="text-[#8a8a83]" />
                View All Engagements
              </button>
            </div>
          </div>

          {/* Activity Feed */}
          <div className="rounded-xl flex-1" style={{ background: '#141414', border: '1px solid #242424' }}>
            <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
              <Clock size={14} className="text-[#8a8a83]" />
              <span className="text-[14px] font-semibold text-[#f2f0e8]">Recent Activity</span>
            </div>
            <div className="px-5 py-3 flex flex-col">
              {activityFeed.length === 0 && (
                <p className="text-[12px] text-[#8a8a83] py-3">No agent activity yet.</p>
              )}
              {activityFeed.map((a, i) => (
                <div
                  key={i}
                  onClick={() => navigate(`/engagements/${a.engagement_id}`)}
                  className="flex gap-3 py-3 cursor-pointer"
                  style={i < activityFeed.length - 1 ? { borderBottom: '1px solid #191919' } : {}}
                >
                  <div className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0" style={{ background: AGENT_COLORS[a.agent] ?? '#64748b' }} />
                  <div className="min-w-0">
                    <p className="text-[12px] font-medium mb-0.5" style={{ color: AGENT_COLORS[a.agent] ?? '#64748b' }}>{a.agent}</p>
                    <p className="text-[11px] text-[#8a8a83] truncate">{a.client_name} · {a.action}</p>
                    <p className="text-[10px] text-[#5c5c55] mt-0.5">{timeAgo(a.created_at)}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
