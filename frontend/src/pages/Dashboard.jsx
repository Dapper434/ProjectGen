import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const PIPELINE_STAGES = ['awaiting_transcript', 'brief_ready', 'awaiting_review_transcript', 'proposal_ready', 'in_review', 'approved'];

const STAGE_LABELS = {
  awaiting_transcript: 'Awaiting Transcript',
  brief_ready: 'Brief Ready',
  awaiting_review_transcript: 'Awaiting Review',
  proposal_ready: 'Proposal Ready',
  in_review: 'In Review',
  approved: 'Approved',
};

export default function Dashboard() {
  const [engagements, setEngagements] = useState([]);
  const [statusFilter, setStatusFilter] = useState('all');
  const navigate = useNavigate();

  useEffect(() => {
    fetch('http://localhost:5000/api/engagements', { credentials: 'include' })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error('Unable to load dashboard data');
        }
        setEngagements(await response.json());
      })
      .catch(err => console.error(err));
  }, []);

  const counts = useMemo(() => {
    const c = { all: engagements.length };
    for (const stage of PIPELINE_STAGES) c[stage] = 0;
    for (const eng of engagements) c[eng.status] = (c[eng.status] || 0) + 1;
    return c;
  }, [engagements]);

  const filteredEngagements = statusFilter === 'all'
    ? engagements
    : engagements.filter((eng) => eng.status === statusFilter);

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-white tracking-tight">Engagements</h1>
          <p className="text-zinc-400 mt-1">Manage your active client engagements</p>
        </div>
        <button
          onClick={() => navigate('/engagements/new')}
          className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-md font-medium text-sm transition-colors shadow-sm"
        >
          New Engagement
        </button>
      </div>

      {/* Status filter */}
      <div className="flex flex-wrap gap-2 mb-8">
        <button
          onClick={() => setStatusFilter('all')}
          className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${statusFilter === 'all' ? 'bg-indigo-600 text-white' : 'bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-white hover:border-zinc-700'}`}
        >
          All <span className="opacity-70">({counts.all})</span>
        </button>
        {PIPELINE_STAGES.map((stage) => (
          <button
            key={stage}
            onClick={() => setStatusFilter(stage)}
            disabled={counts[stage] === 0}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${statusFilter === stage ? 'bg-indigo-600 text-white' : 'bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-white hover:border-zinc-700'}`}
          >
            {STAGE_LABELS[stage]} <span className="opacity-70">({counts[stage]})</span>
          </button>
        ))}
      </div>

      {filteredEngagements.length === 0 ? (
        <div className="h-48 border border-dashed border-zinc-800 rounded-xl flex items-center justify-center text-zinc-500 text-sm">
          No engagements {statusFilter === 'all' ? '' : `in "${STAGE_LABELS[statusFilter]}" `}yet.
        </div>
      ) : (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredEngagements.map(eng => (
          <div 
            key={eng.id}
            onClick={() => navigate(`/engagements/${eng.id}`)}
            className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 hover:border-zinc-700 transition-colors cursor-pointer group"
          >
            <div className="flex items-start justify-between mb-4">
              <div className="w-10 h-10 rounded-full bg-zinc-800 flex items-center justify-center text-zinc-400 group-hover:bg-zinc-700 group-hover:text-zinc-200 transition-colors">
                {eng.client_name.charAt(0)}
              </div>
              <span className="px-2.5 py-1 rounded-full text-[10px] font-medium tracking-wide uppercase bg-zinc-800 text-zinc-300">
                {eng.status.replace(/_/g, ' ')}
              </span>
            </div>
            <h3 className="text-lg font-medium text-white group-hover:text-indigo-400 transition-colors">{eng.client_name}</h3>
            <p className="text-zinc-500 text-sm mt-1">ID: #{eng.id.toString().padStart(4, '0')}</p>
          </div>
        ))}
      </div>
      )}
    </div>
  );
}
