import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useOutletContext } from 'react-router-dom';
import { ChevronRight, Sparkles, Loader2, AlertTriangle, UserPlus, Send, Check, X } from 'lucide-react';
import ScoreBreakdown from '../components/ScoreBreakdown';

const API = '/api';

const STATUS_COLOR = {
  shortlisted: '#8a8a83', offered: '#f59e0b', accepted: '#10b981',
  declined: '#e11d48', expired: '#6e6e67', completed: '#0ea5e9',
  cancelled: '#6e6e67', no_show: '#e11d48',
};

export default function Casting() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useOutletContext();
  const canApprove = user?.role === 'Account Manager' || user?.role === 'Admin';

  const [run, setRun] = useState(null);
  const [assignments, setAssignments] = useState([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(null);
  const pollRef = useRef(null);

  const fetchAll = useCallback(async () => {
    try {
      const [runRes, aRes] = await Promise.all([
        fetch(`${API}/engagements/${id}/casting`, { credentials: 'include' }),
        fetch(`${API}/engagements/${id}/assignments`, { credentials: 'include' }),
      ]);
      if (runRes.ok) {
        const data = await runRes.json();
        setRun(data.run);
        if (data.run?.status === 'running') pollRef.current = setTimeout(fetchAll, 2500);
      }
      if (aRes.ok) setAssignments(await aRes.json());
    } catch { /* transient */ }
  }, [id]);

  useEffect(() => { fetchAll(); return () => clearTimeout(pollRef.current); }, [fetchAll]);

  async function runCasting() {
    setRunning(true); setError('');
    try {
      const res = await fetch(`${API}/engagements/${id}/casting`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError(err.error || 'Could not start the casting run.');
        return;
      }
      setTimeout(fetchAll, 1500);
    } finally { setRunning(false); }
  }

  async function shortlistToAssignment(roleKey, entry, roleLabel) {
    setError('');
    const res = await fetch(`${API}/assignments`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        engagement_id: Number(id), talent_id: entry.talent_id, role: roleLabel || roleKey,
        rate_kes: entry.day_rate_kes, score: entry.score, score_breakdown: entry.why,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError(data.error || 'Could not create the assignment.'); return; }
    fetchAll();
  }

  async function transition(assignmentId, status, extra = {}) {
    setError('');
    const res = await fetch(`${API}/assignments/${assignmentId}`, {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, ...extra }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError(data.error || 'That transition is not allowed.'); return; }
    fetchAll();
  }

  const assignedIds = new Set(assignments.map(a => a.talent_id));

  return (
    <div className="px-8 py-7">
      <div className="flex items-center gap-1.5 text-xs text-[#6e6e67] mb-6">
        <button onClick={() => navigate(`/engagements/${id}`)} className="hover:text-[#a3a39c] transition-colors">
          Engagement
        </button>
        <ChevronRight size={12} />
        <span className="text-[#f7f5ef]">Casting</span>
      </div>

      <div className="flex items-start justify-between gap-4 flex-wrap mb-5">
        <div>
          <h1 className="font-serif text-[#f7f5ef] text-2xl mb-1">Casting</h1>
          <p className="text-sm text-[#8a8a83] max-w-2xl">
            A deterministic score ranks the bench; the model only writes the reasoning. Nobody is
            contacted until an Account Manager approves them.
          </p>
        </div>
        <button onClick={runCasting} disabled={running}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-white text-[13px] font-medium transition-all hover:opacity-90 disabled:opacity-50"
          style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}>
          {running ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {running ? 'Starting…' : run ? 'Re-run casting' : 'Run casting'}
        </button>
      </div>

      {error && <p role="alert" className="text-sm text-rose-500 mb-4">{error}</p>}

      {run?.status === 'running' && (
        <p className="flex items-center gap-2 text-[13px] text-[#8a8a83] mb-5" aria-live="polite">
          <Loader2 size={13} className="animate-spin text-[#c9971f]" /> Scoring the bench…
        </p>
      )}

      {run?.status === 'needs_input' && (
        <div className="flex items-start gap-2 p-4 rounded-lg mb-5"
          style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)' }}>
          <AlertTriangle size={14} className="text-[#f59e0b] shrink-0 mt-0.5" />
          <p className="text-xs text-[#fcd34d]">
            No roles could be read from the brief or proposal yet. The agent will not invent roles —
            add a team shape to the proposal, then re-run.
          </p>
        </div>
      )}

      {assignments.length > 0 && (
        <div className="rounded-xl overflow-hidden mb-6" style={{ background: '#141414', border: '1px solid #242424' }}>
          <div className="px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
            <span className="text-[14px] font-semibold text-[#f2f0e8]">Crew</span>
          </div>
          <div className="divide-y" style={{ borderColor: '#191919' }}>
            {assignments.map(a => (
              <div key={a.id} className="px-5 py-3 flex items-center gap-3 flex-wrap">
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] text-[#d6d4c9]">
                    {a.talent?.name} <span className="text-[#5c5c55]">· {a.role}</span>
                  </p>
                  <p className="text-[10px] font-mono text-[#5c5c55]">
                    {a.rate_kes ? `KES ${a.rate_kes.toLocaleString()}/day` : 'rate not set'}
                    {a.score != null ? ` · score ${a.score.toFixed(3)}` : ''}
                  </p>
                </div>
                <span className="text-[10px] font-mono font-semibold px-2 py-1 rounded-md"
                  style={{ color: STATUS_COLOR[a.status], background: `${STATUS_COLOR[a.status]}1f` }}>
                  {a.status.replace('_', ' ').toUpperCase()}
                </span>
                {canApprove && a.status === 'shortlisted' && (
                  <button onClick={() => transition(a.id, 'offered')}
                    className="flex items-center gap-1 text-[11px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors">
                    <Send size={11} /> Send offer
                  </button>
                )}
                {canApprove && a.status === 'accepted' && (
                  <button onClick={() => transition(a.id, 'completed', { rating: 5 })}
                    className="flex items-center gap-1 text-[11px] text-[#a3a39c] hover:text-[#10b981] transition-colors">
                    <Check size={11} /> Mark complete
                  </button>
                )}
                {canApprove && ['shortlisted', 'offered', 'accepted'].includes(a.status) && (
                  <button onClick={() => transition(a.id, 'cancelled', { late: a.status === 'accepted' })}
                    className="flex items-center gap-1 text-[11px] text-[#a3a39c] hover:text-rose-500 transition-colors">
                    <X size={11} /> Cancel
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {run?.result && Object.entries(run.result).map(([roleKey, role]) => (
        <div key={roleKey} className="rounded-xl overflow-hidden mb-5"
          style={{ background: '#141414', border: '1px solid #242424' }}>
          <div className="px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
            <p className="text-[14px] font-semibold text-[#f2f0e8]">{role.label || roleKey}</p>
            <p className="text-[10px] font-mono text-[#5c5c55] mt-0.5">
              {role.shortlist.length} shortlisted of {role.pool_size} eligible
            </p>
          </div>

          {role.rationale && (
            <p className="px-5 py-3 text-[12px] text-[#a3a39c]" style={{ borderBottom: '1px solid #191919' }}>
              {role.rationale}
            </p>
          )}

          {(role.concerns || []).length > 0 && (
            <div className="px-5 py-3 flex flex-col gap-1" style={{ borderBottom: '1px solid #191919' }}>
              {role.concerns.map((c, i) => (
                <p key={i} className="flex items-start gap-1.5 text-[11px] text-[#fcd34d]">
                  <AlertTriangle size={11} className="shrink-0 mt-0.5" /> {c}
                </p>
              ))}
            </div>
          )}

          <div className="divide-y" style={{ borderColor: '#191919' }}>
            {role.shortlist.map(entry => (
              <div key={entry.talent_id} className="px-5 py-3.5">
                <div className="flex items-start gap-3 flex-wrap">
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px] font-medium text-[#d6d4c9]">
                      {entry.name}
                      <span className="text-[10px] font-mono text-[#5c5c55] ml-2">
                        {entry.engagement_type} · {entry.tokens} tokens · idle {entry.idle_days}d
                      </span>
                    </p>
                    <p className="text-[11px] text-[#8a8a83]">
                      {entry.title}{entry.day_rate_kes ? ` · KES ${entry.day_rate_kes.toLocaleString()}/day` : ''}
                    </p>
                  </div>
                  <button onClick={() => setExpanded(expanded === entry.talent_id ? null : entry.talent_id)}
                    className="text-[11px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors">
                    {expanded === entry.talent_id ? 'Hide why' : 'Why?'}
                  </button>
                  {canApprove && !assignedIds.has(entry.talent_id) && (
                    <button onClick={() => shortlistToAssignment(roleKey, entry, role.label)}
                      className="flex items-center gap-1 text-[11px] text-[#e8c34a] hover:underline">
                      <UserPlus size={11} /> Add to crew
                    </button>
                  )}
                </div>
                {expanded === entry.talent_id && (
                  <div className="mt-3 max-w-md">
                    <ScoreBreakdown why={entry.why} score={entry.score} />
                  </div>
                )}
              </div>
            ))}
            {role.shortlist.length === 0 && (
              <p className="px-5 py-6 text-[12px] text-[#5c5c55]">
                Nobody on the bench passes the hard filters for this role.
              </p>
            )}
          </div>
        </div>
      ))}

      {!run && !running && (
        <p className="text-[13px] text-[#8a8a83]">No casting run yet for this engagement.</p>
      )}
    </div>
  );
}
