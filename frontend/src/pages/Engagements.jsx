import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PIPELINE_STAGES, STAGE_META, stageMeta, clientColor, formatId } from '../lib/engagements';

const tabs = [
  { id: 'all', label: 'All' },
  ...PIPELINE_STAGES.map(stage => ({
    id: stage,
    label: STAGE_META[stage].label.toLowerCase().replace(/\b\w/g, c => c.toUpperCase()),
    stages: [stage],
  })),
];

function EngagementCard({ eng, onClick }) {
  const meta = stageMeta(eng.status);
  const color = clientColor(eng.client_name);

  return (
    <div
      onClick={onClick}
      className="relative rounded-xl cursor-pointer transition-all duration-200 group"
      style={{
        background: 'linear-gradient(145deg, #151515 0%, #101010 100%)',
        border: '1px solid #242424',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.borderColor = color + '55';
        e.currentTarget.style.boxShadow = `0 4px 20px ${color}18`;
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = '#242424';
        e.currentTarget.style.boxShadow = 'none';
      }}
    >
      {/* Status badge top-right */}
      <div className="absolute top-3 right-3">
        <span
          className="text-[9px] font-mono font-semibold tracking-wider px-2 py-1 rounded-md"
          style={{ color: meta.color, background: meta.bg }}
        >
          {meta.label}
        </span>
      </div>

      <div className="p-5 pt-4">
        {/* Client avatar */}
        <div
          className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold mb-4"
          style={{ background: color + '28', border: `1.5px solid ${color}55`, color }}
        >
          {eng.client_name.charAt(0).toUpperCase()}
        </div>

        {/* Client name */}
        <p className="text-[15px] font-semibold text-[#f2f0e8] mb-1 pr-24 leading-snug">{eng.client_name}</p>
        <p className="text-[12px] text-[#5c5c55] font-mono">ID: {formatId(eng.id)}</p>
      </div>

      {/* Bottom strip */}
      <div className="px-5 py-2.5 flex items-center justify-between" style={{ borderTop: '1px solid #191919' }}>
        <span className="text-[11px] text-[#5c5c55]">Engagement {formatId(eng.id)}</span>
        <div className="w-5 h-5 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all"
          style={{ background: color + '22' }}>
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
            <path d="M1 7L7 1M7 1H2M7 1V6" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      </div>
    </div>
  );
}

export default function Engagements() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('all');
  const [engagements, setEngagements] = useState([]);

  useEffect(() => {
    fetch('/api/engagements', { credentials: 'include' })
      .then(res => (res.ok ? res.json() : []))
      .then(data => setEngagements([...data].sort((a, b) => b.id - a.id)))
      .catch(err => console.error(err));
  }, []);

  const filtered = engagements.filter(e => {
    const tab = tabs.find(t => t.id === activeTab);
    return !tab?.stages || tab.stages.includes(e.status);
  });

  const tabCounts = useMemo(() => tabs.reduce((acc, t) => {
    acc[t.id] = !t.stages ? engagements.length : engagements.filter(e => t.stages.includes(e.status)).length;
    return acc;
  }, {}), [engagements]);

  return (
    <div className="px-8 py-7">
      {/* Header */}
      <div className="flex items-start justify-between mb-7">
        <div>
          <h1 className="text-[#f7f5ef] text-2xl font-semibold mb-1">Engagements</h1>
          <p className="text-[13px] text-[#8a8a83]">Manage your active client engagements</p>
        </div>
      </div>

      {/* Tab filter bar */}
      <div className="flex items-center gap-1.5 mb-7 flex-wrap">
        {tabs.map(t => {
          const count = tabCounts[t.id];
          const isActive = activeTab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all"
              style={isActive ? {
                background: 'rgba(201,151,31,0.18)',
                color: '#a16207',
                border: '1px solid rgba(201,151,31,0.3)',
              } : {
                background: '#151515',
                color: '#8a8a83',
                border: '1px solid #242424',
              }}
            >
              {t.label}
              {count > 0 && (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                  style={isActive ? { background: 'rgba(201,151,31,0.25)', color: '#a16207' } : { background: '#242424', color: '#8a8a83' }}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Card grid */}
      {filtered.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map(eng => (
            <EngagementCard
              key={eng.id}
              eng={eng}
              onClick={() => navigate(`/engagements/${eng.id}`)}
            />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-12 h-12 rounded-xl mb-4 flex items-center justify-center" style={{ background: '#151515', border: '1px solid #242424' }}>
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 4v12M4 10h12" stroke="#5c5c55" strokeWidth="1.5" strokeLinecap="round"/></svg>
          </div>
          <p className="text-[14px] text-[#8a8a83] mb-1">No engagements found</p>
          <p className="text-[12px] text-[#5c5c55]">Try a different filter or create a new engagement</p>
        </div>
      )}
    </div>
  );
}
