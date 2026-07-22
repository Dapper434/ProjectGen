import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ChevronRight, Layers, TrendingUp, Clock, HelpCircle, ArrowUpRight, Plus } from 'lucide-react';
import { stageMeta, clientColor, formatId, timeAgo, formatKes } from '../lib/engagements';

const API = '/api';

export default function ClientDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [client, setClient] = useState(null);
  const [error, setError] = useState('');

  const fetchClient = useCallback(async () => {
    try {
      const res = await fetch(`${API}/clients/${id}`, { credentials: 'include' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError(err.error || 'Could not load this client.');
        return;
      }
      setClient(await res.json());
    } catch (err) {
      console.error(err);
      setError('Connection failed. Is the backend running?');
    }
  }, [id]);

  useEffect(() => { fetchClient(); }, [fetchClient]);

  if (error) {
    return <div className="px-8 py-7 text-sm text-rose-500">{error}</div>;
  }
  if (!client) {
    return <div className="px-8 py-7 text-sm text-[#8a8a83]">Loading…</div>;
  }

  const color = clientColor(client.name);
  const carryForward = client.carry_forward || [];
  const engagements = client.engagements || [];

  return (
    <div className="px-8 py-7">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-xs text-[#6e6e67] mb-6">
        <button onClick={() => navigate('/dashboard')} className="hover:text-[#a3a39c] transition-colors">Dashboard</button>
        <ChevronRight size={12} />
        <span className="text-[#f7f5ef]">{client.name}</span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between mb-7 gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-full flex items-center justify-center text-lg font-bold shrink-0"
            style={{ background: color + '22', border: `1.5px solid ${color}44`, color }}>
            {client.name.charAt(0).toUpperCase()}
          </div>
          <div>
            <h1 className="font-serif text-[#f7f5ef] text-2xl mb-0.5">{client.name}</h1>
            <p className="text-sm text-[#a3a39c]">
              {client.industry ? `${client.industry} · ` : ''}{client.rollup.engagement_count} engagement{client.rollup.engagement_count === 1 ? '' : 's'}
            </p>
          </div>
        </div>
        <button
          onClick={() => navigate('/engagements/new')}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-white text-[13px] font-medium transition-all hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)', boxShadow: '0 2px 12px rgba(201,151,31,0.3)' }}
        >
          <Plus size={14} />
          New Engagement
        </button>
      </div>

      {client.notes && (
        <p className="text-xs text-[#6e6e67] mb-7 max-w-2xl">{client.notes}</p>
      )}

      {/* Rollup stats */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mb-7">
        {[
          { label: 'Approved Revenue', value: formatKes(client.rollup.approved_revenue_kes), icon: TrendingUp, color: '#10b981' },
          { label: 'Open Pipeline Value', value: formatKes(client.rollup.pipeline_value_kes), icon: Layers, color: '#c9971f' },
          { label: 'Last Activity', value: client.rollup.last_activity_at ? timeAgo(client.rollup.last_activity_at) : 'No activity yet', icon: Clock, color: '#0ea5e9' },
        ].map(({ label, value, icon: Icon, color: c }) => (
          <div key={label} className="rounded-xl p-5" style={{ background: 'linear-gradient(145deg, #151515 0%, #101010 100%)', border: '1px solid #242424' }}>
            <div className="flex items-center gap-1.5 mb-3">
              <Icon size={12} style={{ color: c }} />
              <span className="text-[10px] font-mono tracking-wider" style={{ color: c + 'cc' }}>{label.toUpperCase()}</span>
            </div>
            <p className="text-[20px] font-semibold text-[#f7f5ef] leading-none">{value}</p>
          </div>
        ))}
      </div>

      {/* Carry into next meeting — relationship-wide, across every engagement */}
      {carryForward.length > 0 && (
        <div className="rounded-xl mb-7" style={{ background: '#141414', border: '1px solid #242424' }}>
          <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
            <HelpCircle size={14} className="text-[#8a8a83]" />
            <span className="text-[14px] font-semibold text-[#f2f0e8]">Carry Into Next Meeting</span>
          </div>
          <div className="px-5 py-3 flex flex-col">
            {carryForward.map((item, i) => (
              <div
                key={i}
                onClick={() => navigate(`/engagements/${item.engagement_id}`)}
                className="flex gap-3 py-3 cursor-pointer group"
                style={i < carryForward.length - 1 ? { borderBottom: '1px solid #191919' } : {}}
              >
                <div className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 bg-[#f59e0b]" />
                <div className="min-w-0 flex-1">
                  <p className="text-[12px] text-[#d6d4c9]">{item.text}</p>
                  <p className="text-[10px] text-[#5c5c55] font-mono mt-0.5">{item.source} · Engagement {formatId(item.engagement_id)}</p>
                </div>
                <ArrowUpRight size={13} className="text-[#5c5c55] group-hover:text-[#c9971f] transition-colors shrink-0" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Every engagement/workflow with this client */}
      <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
        <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
          <Layers size={14} className="text-[#8a8a83]" />
          <span className="text-[14px] font-semibold text-[#f2f0e8]">All Engagements</span>
        </div>
        {engagements.length === 0 ? (
          <div className="px-5 py-10 text-center">
            <p className="text-[13px] text-[#8a8a83]">No engagements yet for this client.</p>
          </div>
        ) : (
          <div className="divide-y" style={{ borderColor: '#191919' }}>
            {engagements.map(eng => {
              const meta = stageMeta(eng.status);
              return (
                <div
                  key={eng.id}
                  onClick={() => navigate(`/engagements/${eng.id}`)}
                  className="flex items-center gap-3 px-5 py-3.5 cursor-pointer hover:bg-[#1a1a1a] transition-colors group"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium text-[#d6d4c9] truncate">
                      {eng.work_type ? eng.work_type.replace(/-/g, ' ') : 'Engagement'} <span className="text-[#5c5c55] font-mono">{formatId(eng.id)}</span>
                    </p>
                    <p className="text-[11px] text-[#5c5c55] font-mono">
                      {eng.created_at ? timeAgo(eng.created_at) : 'Started'}
                      {eng.value_kes > 0 ? ` · ${formatKes(eng.value_kes)}` : ''}
                    </p>
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
    </div>
  );
}
