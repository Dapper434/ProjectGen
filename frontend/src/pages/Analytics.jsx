import { useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { FileText, TrendingUp, Users, RotateCcw, Activity } from 'lucide-react';
import { formatKes, timeAgo } from '../lib/engagements';

const API = '/api';

const AGENT_COLORS = {
  'Brief Generator': '#c9971f',
  'Proposal Generator': '#0369a1',
  'Signal Extractor': '#b45309',
  'Account Manager (Human)': '#10b981',
};

const WORK_TYPE_COLORS = ['#f43f5e', '#f59e0b', '#0ea5e9', '#10b981', '#a855f7', '#c9971f'];

const FUNNEL_LABELS = {
  awaiting_transcript: 'Awaiting Transcript',
  brief_ready: 'Brief Ready',
  awaiting_review_transcript: 'Awaiting Review',
  proposal_ready: 'Proposal Ready',
  in_review: 'In Review',
  approved: 'Approved',
};

export default function Analytics() {
  const { user } = useOutletContext();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  const isAdmin = user?.role === 'Admin';

  useEffect(() => {
    if (!isAdmin) return;
    fetch(`${API}/analytics`, { credentials: 'include' })
      .then(res => (res.ok ? res.json() : Promise.reject(res)))
      .then(setData)
      .catch(() => setError('Could not load analytics.'));
  }, [isAdmin]);

  if (!isAdmin) {
    return (
      <div className="px-8 py-7">
        <p className="text-sm text-[#8a8a83]">Agency Pulse is only available to Admin accounts.</p>
      </div>
    );
  }
  if (error) {
    return <div className="px-8 py-7 text-sm text-rose-500">{error}</div>;
  }
  if (!data) {
    return <div className="px-8 py-7 text-sm text-[#8a8a83]">Loading…</div>;
  }

  const activeEngagements = data.totals.engagements - (data.totals.approved || 0);
  const awaitingTranscript = (data.funnel.find(f => f.status === 'awaiting_transcript') || {}).count || 0;

  const kpis = [
    { label: 'APPROVED REVENUE', value: formatKes(data.approved_revenue_kes), icon: FileText, color: '#10b981', sub: `${data.totals.approved} approved proposal${data.totals.approved === 1 ? '' : 's'}` },
    { label: 'OPEN PIPELINE VALUE', value: formatKes(data.pipeline_value_kes), icon: TrendingUp, color: '#c9971f', sub: data.pipeline_value_kes ? 'Unscoped/in-review work' : 'No unscoped work' },
    { label: 'ACTIVE ENGAGEMENTS', value: activeEngagements, icon: Users, color: '#0ea5e9', sub: `${awaitingTranscript} awaiting transcript` },
    { label: 'PROPOSAL SEND-BACK RATE', value: `${data.send_back_rate}%`, icon: RotateCcw, color: '#f59e0b', sub: 'Share of proposals revised at least once' },
  ];

  const funnel = data.funnel.map((f, i) => ({
    label: FUNNEL_LABELS[f.status] || f.status,
    count: f.count,
    color: f.status === 'approved' ? '#10b981' : '#c9971f',
    index: i,
  }));

  const turnaround = [
    { label: 'Transcript → Brief', value: data.turnaround.transcript_to_brief_hours != null ? `${data.turnaround.transcript_to_brief_hours} hrs` : '—' },
    { label: 'Brief → Proposal', value: data.turnaround.brief_to_proposal_hours != null ? `${data.turnaround.brief_to_proposal_hours} hrs` : '—' },
    { label: 'Proposal → Approval', value: data.turnaround.proposal_to_approval_hours != null ? `${data.turnaround.proposal_to_approval_hours} hrs` : '—' },
  ];

  const workTypes = data.work_type_breakdown.map((w, i) => ({
    label: w.work_type,
    count: w.count,
    color: WORK_TYPE_COLORS[i % WORK_TYPE_COLORS.length],
  }));
  const totalWorkTypeCount = workTypes.reduce((sum, w) => sum + w.count, 0);
  let cumulative = 0;
  const conicStops = workTypes.map(w => {
    const from = totalWorkTypeCount ? (cumulative / totalWorkTypeCount) * 100 : 0;
    cumulative += w.count;
    const to = totalWorkTypeCount ? (cumulative / totalWorkTypeCount) * 100 : 0;
    return `${w.color} ${from}% ${to}%`;
  }).join(', ');

  return (
    <div className="w-full max-w-[1440px] px-8 py-7">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-[#f7f5ef] text-2xl font-semibold mb-1">Agency Pulse</h1>
        <p className="text-[13px] text-[#8a8a83]">How work is moving through The Exodus, agency-wide</p>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        {kpis.map(({ label, value, icon: Icon, color, sub }) => (
          <div key={label} className="rounded-xl p-5 transition-all hover:border-[#333333]"
            style={{ background: 'linear-gradient(145deg, #151515 0%, #101010 100%)', border: '1px solid #242424' }}>
            <div className="flex items-center gap-1.5 mb-3">
              <Icon size={12} style={{ color }} />
              <span className="text-[10px] font-mono tracking-wider" style={{ color: color + 'cc' }}>{label}</span>
            </div>
            <p className="text-[22px] font-semibold text-[#f7f5ef] mb-1 leading-none">{value}</p>
            <p className="text-[11px] text-[#5c5c55] mt-1.5">{sub}</p>
          </div>
        ))}
      </div>

      {/* Client Proposals */}
      <div className="rounded-xl mb-4 overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
        <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
          <FileText size={14} className="text-[#8a8a83]" />
          <span className="text-[14px] font-semibold text-[#f2f0e8]">Client Proposals</span>
        </div>
        {data.proposals.length === 0 ? (
          <div className="px-5 py-8 text-center text-[13px] text-[#8a8a83]">No proposals yet.</div>
        ) : (
          <div>
            <div className="grid grid-cols-[2fr_1.2fr_0.8fr_1fr_1fr] px-5 py-2.5" style={{ borderBottom: '1px solid #191919' }}>
              {['Client', 'Status', 'Version', 'Created', 'Value'].map(h => (
                <span key={h} className="text-[11px] font-mono text-[#5c5c55] uppercase tracking-wider">{h}</span>
              ))}
            </div>
            {data.proposals.map((p, i) => (
              <div key={i} className="grid grid-cols-[2fr_1.2fr_0.8fr_1fr_1fr] px-5 py-4 hover:bg-[#1a1a1a] transition-colors items-center">
                <span className="text-[13px] text-[#d6d4c9] font-medium">{p.client_name}</span>
                <div>
                  <span className="text-[10px] font-mono font-semibold px-2 py-1 rounded-md"
                    style={{
                      color: p.status === 'approved' ? '#10b981' : '#c9971f',
                      background: p.status === 'approved' ? 'rgba(16,185,129,0.12)' : 'rgba(201,151,31,0.12)',
                      border: `1px solid ${p.status === 'approved' ? 'rgba(16,185,129,0.25)' : 'rgba(201,151,31,0.25)'}`,
                    }}>
                    {p.status.toUpperCase()}
                  </span>
                </div>
                <span className="text-[13px] text-[#8a8a83] font-mono">v{p.version}</span>
                <span className="text-[13px] text-[#8a8a83]">{p.created_at ? timeAgo(p.created_at) : '—'}</span>
                <span className="text-[13px] font-semibold text-[#f7f5ef]">{formatKes(p.total_kes)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Operational overview */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
          <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
            <Activity size={14} className="text-[#8a8a83]" />
            <div><span className="text-[14px] font-semibold text-[#f2f0e8]">Pipeline Funnel</span><p className="text-[11px] text-[#5c5c55]">Engagements by current stage</p></div>
          </div>
          <div className="p-4 grid grid-cols-2 gap-2">
            {funnel.map(({ label, count, color, index }) => (
              <div key={label} className="rounded-lg p-3" style={{ background: count ? `${color}12` : '#1a1a1a', border: `1px solid ${count ? `${color}35` : '#242424'}` }}>
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[11px] leading-tight text-[#8a8a83]">{label}</span>
                  <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono shrink-0" style={{ background: count ? `${color}20` : '#242424', color: count ? color : '#6e6e67' }}>{index + 1}</span>
                </div>
                <p className="mt-2 text-xl font-semibold text-[#f7f5ef]">{count}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
          <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="text-[#8a8a83]"><circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.2"/><path d="M7 4v3l2 1.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>
            <div><span className="text-[14px] font-semibold text-[#f2f0e8]">Avg. Turnaround Time</span><p className="text-[11px] text-[#5c5c55]">Average time per handoff</p></div>
          </div>
          <div className="p-4 flex flex-col gap-2">
            {turnaround.map(({ label, value }, index) => (
              <div key={label} className="flex items-center gap-3 rounded-lg p-3" style={{ background: '#1a1a1a', border: '1px solid #242424' }}>
                <div className="w-9 h-9 rounded-full shrink-0 flex items-center justify-center text-sm font-semibold" style={{ background: 'rgba(201,151,31,0.15)', color: '#c9971f' }}>{index + 1}</div>
                <div className="min-w-0 flex-1"><p className="text-[11px] text-[#8a8a83] leading-tight">{label}</p><p className="mt-1 text-[15px] font-semibold text-[#f7f5ef]">{value}</p></div>
                {index < turnaround.length - 1 && <span className="text-[#5c5c55] text-lg">→</span>}
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
          <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 10l3-4 3 2 4-6" stroke="#8a8a83" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            <span className="text-[14px] font-semibold text-[#f2f0e8]">Work Type Mix</span>
          </div>
          {workTypes.length === 0 ? (
            <div className="px-5 py-8 text-center text-[13px] text-[#8a8a83]">No briefs generated yet.</div>
          ) : (
            <div className="p-5 flex items-center gap-5">
              <div className="w-28 h-28 shrink-0 rounded-full flex items-center justify-center" style={{ background: `conic-gradient(${conicStops})` }}>
                <div className="w-20 h-20 rounded-full flex flex-col items-center justify-center" style={{ background: '#141414' }}>
                  <span className="text-2xl font-semibold text-[#f7f5ef]">{totalWorkTypeCount}</span>
                  <span className="text-[10px] text-[#8a8a83]">briefs</span>
                </div>
              </div>
              <div className="flex-1 grid grid-cols-1 gap-2">
                {workTypes.map(({ label, count, color }) => (
                  <div key={label} className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: color }} />
                      <span className="text-[11px] text-[#8a8a83] truncate capitalize">{label}</span>
                    </div>
                    <span className="text-[12px] font-semibold text-[#f7f5ef]">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Recent Activity */}
      <div className="rounded-xl" style={{ background: '#141414', border: '1px solid #242424' }}>
        <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="5.5" stroke="#8a8a83" strokeWidth="1.2"/>
            <path d="M7 4v3l2 1.5" stroke="#8a8a83" strokeWidth="1.2" strokeLinecap="round"/>
          </svg>
          <span className="text-[14px] font-semibold text-[#f2f0e8]">Recent Activity</span>
        </div>
        {data.recent_activity.length === 0 ? (
          <div className="px-5 py-8 text-center text-[13px] text-[#8a8a83]">No agent activity yet.</div>
        ) : (
          <div className="px-5 py-3 flex flex-col">
            {data.recent_activity.map((a, i) => (
              <div key={i} className="flex gap-3 py-3" style={i < data.recent_activity.length - 1 ? { borderBottom: '1px solid #191919' } : {}}>
                <div className="w-2 h-2 rounded-full mt-1.5 shrink-0" style={{ background: AGENT_COLORS[a.agent] || '#64748b' }} />
                <div className="min-w-0">
                  <p className="text-[13px] mb-0.5">
                    <span className="font-medium" style={{ color: AGENT_COLORS[a.agent] || '#64748b' }}>{a.agent}</span>
                    <span className="text-[#8a8a83]"> · {a.client_name}</span>
                  </p>
                  <p className="text-[12px] text-[#8a8a83] leading-relaxed truncate">{a.reasoning_summary}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
