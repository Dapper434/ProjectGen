import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ChevronRight, Loader2, Save, Send, RotateCcw, Download, AlertCircle } from 'lucide-react';
import ProviderBadge from '../components/ProviderBadge';

const API = '/api';

function stamp(ms) {
  const total = Math.max(0, Math.round((ms || 0) / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

export default function RecordingDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [engagements, setEngagements] = useState([]);
  const [view, setView] = useState('polished');   // polished | raw | segments
  const [draft, setDraft] = useState(null);       // null until the user edits
  const [engagementId, setEngagementId] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [attaching, setAttaching] = useState(false);
  const pollRef = useRef(null);

  const fetchJob = useCallback(async () => {
    try {
      const res = await fetch(`${API}/recordings/${id}`, { credentials: 'include' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError(err.error || 'Could not load this recording.');
        return;
      }
      const data = await res.json();
      setJob(data);
      setEngagementId(prev => prev || (data.engagement_id ? String(data.engagement_id) : ''));
      if (!['ready', 'attached', 'failed', 'cancelled'].includes(data.status)) {
        pollRef.current = setTimeout(fetchJob, 3000);
      }
    } catch (err) {
      console.error(err);
      setError('Connection failed.');
    }
  }, [id]);

  useEffect(() => {
    fetchJob();
    fetch(`${API}/engagements`, { credentials: 'include' })
      .then(r => (r.ok ? r.json() : [])).then(setEngagements).catch(err => console.error(err));
    return () => clearTimeout(pollRef.current);
  }, [fetchJob]);

  if (error && !job) return <div className="px-8 py-7 text-sm text-rose-500">{error}</div>;
  if (!job) return <div className="px-8 py-7 text-sm text-[#8a8a83]">Loading…</div>;

  const baseText = job.edited_text ?? (view === 'raw' ? job.raw_text : job.polished_text) ?? '';
  const text = draft ?? baseText;
  const active = !['ready', 'attached', 'failed', 'cancelled'].includes(job.status);

  async function save() {
    setSaving(true); setError('');
    try {
      const res = await fetch(`${API}/recordings/${id}`, {
        method: 'PATCH', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ edited_text: text }),
      });
      if (!res.ok) { setError('Could not save your edits.'); return; }
      setDraft(null);
      fetchJob();
    } finally { setSaving(false); }
  }

  async function attach() {
    if (!engagementId) { setError('Choose an engagement to attach this to.'); return; }
    setAttaching(true); setError('');
    try {
      if (draft !== null) await save();
      const res = await fetch(`${API}/recordings/${id}/attach`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ engagement_id: Number(engagementId) }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setError(data.error || 'Could not attach this transcript.'); return; }
      navigate(`/engagements/${engagementId}`);
    } catch (err) {
      console.error(err);
      setError('Connection failed.');
    } finally { setAttaching(false); }
  }

  async function retry() {
    await fetch(`${API}/recordings/${id}/retry`, { method: 'POST', credentials: 'include' });
    fetchJob();
  }

  return (
    <div className="px-8 py-7">
      <div className="flex items-center gap-1.5 text-xs text-[#6e6e67] mb-6">
        <button onClick={() => navigate('/recordings')} className="hover:text-[#a3a39c] transition-colors">
          Recording Studio
        </button>
        <ChevronRight size={12} />
        <span className="text-[#f7f5ef]">{job.title || job.source_name}</span>
      </div>

      <div className="flex items-start justify-between gap-4 flex-wrap mb-5">
        <div>
          <h1 className="font-serif text-[#f7f5ef] text-2xl mb-1">{job.title || job.source_name}</h1>
          <div className="flex items-center gap-2 flex-wrap">
            <ProviderBadge driverLabel={job.driver_label} isLocal={job.is_local} latencyMs={job.latency_ms} />
            {job.duration_sec ? (
              <span className="text-[10px] font-mono text-[#5c5c55]">{Math.round(job.duration_sec / 60)} min of audio</span>
            ) : null}
          </div>
        </div>
        {job.status === 'failed' && (
          <button onClick={retry}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors"
            style={{ border: '1px solid #333' }}>
            <RotateCcw size={12} /> Retry
          </button>
        )}
      </div>

      {error && <p role="alert" className="text-sm text-rose-500 mb-4">{error}</p>}

      {job.status === 'failed' && (
        <div className="flex items-start gap-2 p-4 rounded-lg mb-5"
          style={{ background: 'rgba(225,29,72,0.08)', border: '1px solid rgba(225,29,72,0.25)' }}>
          <AlertCircle size={14} className="text-[#e11d48] shrink-0 mt-0.5" />
          <p className="text-xs text-[#fda4af]">{job.error}</p>
        </div>
      )}

      {active && (
        <div className="rounded-xl p-5 mb-5" style={{ background: '#141414', border: '1px solid #242424' }}>
          <p className="flex items-center gap-2 text-[13px] text-[#d6d4c9] mb-3" aria-live="polite">
            <Loader2 size={13} className="animate-spin text-[#c9971f]" />
            {job.status === 'transcribing' && job.pieces_total
              ? `Transcribing — piece ${job.pieces_done} of ${job.pieces_total}`
              : job.status === 'normalising' ? 'Preparing the audio…'
              : job.status === 'polishing' ? 'Cleaning up the transcript…'
              : 'Queued — waiting for a free slot…'}
          </p>
          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: '#262626' }}>
            <div className="h-full transition-[width] duration-500"
              style={{ width: `${job.progress_pct || 0}%`, background: '#c9971f' }} />
          </div>
        </div>
      )}

      {(job.raw_text || job.polished_text) && (
        <div className="rounded-xl overflow-hidden mb-5" style={{ background: '#141414', border: '1px solid #242424' }}>
          <div className="flex items-center justify-between gap-3 px-5 py-3.5 flex-wrap" style={{ borderBottom: '1px solid #242424' }}>
            <div className="flex gap-1">
              {[['polished', 'Cleaned up'], ['raw', 'Raw'], ['segments', 'Timestamps']].map(([key, label]) => (
                <button key={key} onClick={() => { setView(key); setDraft(null); }}
                  className={`px-3 py-1.5 rounded text-xs font-medium transition-all ${
                    view === key ? 'bg-[#c9971f]/15 text-[#e8c34a]' : 'text-[#a3a39c] hover:text-[#f7f5ef]'}`}>
                  {label}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              {['txt', 'md', 'srt'].map(fmt => (
                <a key={fmt} href={`${API}/recordings/${id}/export?format=${fmt}`}
                  className="flex items-center gap-1 text-[11px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors">
                  <Download size={11} />{fmt.toUpperCase()}
                </a>
              ))}
            </div>
          </div>

          <div className="px-5 py-4">
            {view === 'segments' ? (
              <div className="flex flex-col gap-2 max-h-[26rem] overflow-y-auto">
                {(job.segments || []).map(s => (
                  <div key={s.seq} className="flex gap-3">
                    <span className="text-[10px] font-mono text-[#5c5c55] shrink-0 pt-0.5">{stamp(s.start_ms)}</span>
                    <span className="text-[12px] text-[#d6d4c9]">{s.text}</span>
                  </div>
                ))}
                {(job.segments || []).length === 0 && (
                  <p className="text-[12px] text-[#5c5c55]">No timestamped segments were stored for this job.</p>
                )}
              </div>
            ) : (
              <>
                <textarea
                  aria-label="Transcript"
                  rows={14}
                  value={text}
                  onChange={e => setDraft(e.target.value)}
                  className="w-full rounded-lg px-3 py-2.5 text-[12px] text-[#d6d4c9] bg-[#0e0e0e] resize-y font-mono"
                  style={{ border: '1px solid #262626' }}
                />
                {job.edited_text && (
                  <p className="text-[10px] text-[#5c5c55] mt-1.5">
                    Showing your edited version. Switch tabs to see the original.
                  </p>
                )}
                {draft !== null && (
                  <button onClick={save} disabled={saving}
                    className="mt-3 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] text-[#d6d4c9] transition-colors hover:bg-[#1a1a1a] disabled:opacity-50"
                    style={{ border: '1px solid #333' }}>
                    {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                    {saving ? 'Saving…' : 'Save edits'}
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {job.status === 'ready' && (
        <div className="rounded-xl p-5" style={{ background: '#141414', border: '1px solid #242424' }}>
          <p className="text-[14px] font-semibold text-[#f2f0e8] mb-1">Send into the pipeline</p>
          <p className="text-xs text-[#8a8a83] mb-4">
            This creates a normal transcript on the engagement and runs the same agents a pasted or
            Fathom-sourced transcript would.
          </p>
          <div className="flex gap-2 flex-wrap items-end">
            <div className="flex flex-col gap-1.5 min-w-[16rem]">
              <label htmlFor="attach-eng" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">ENGAGEMENT</label>
              <select id="attach-eng" value={engagementId} onChange={e => setEngagementId(e.target.value)}
                className="rounded-lg px-3 py-2 text-[12px] text-[#d6d4c9] bg-[#0e0e0e]"
                style={{ border: '1px solid #262626' }}>
                <option value="">Choose an engagement…</option>
                {engagements.map(e => (
                  <option key={e.id} value={e.id}>
                    {e.client_name} · #{String(e.id).padStart(4, '0')} ({e.status.replace(/_/g, ' ')})
                  </option>
                ))}
              </select>
            </div>
            <button onClick={attach} disabled={attaching || !engagementId}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-white text-[13px] font-medium transition-all hover:opacity-90 disabled:opacity-50"
              style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}>
              {attaching ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              {attaching ? 'Attaching…' : 'Attach & generate'}
            </button>
          </div>
        </div>
      )}

      {job.status === 'attached' && (
        <div className="rounded-xl p-5 flex items-center gap-3"
          style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.25)' }}>
          <p className="text-xs text-[#7dd3fc]">
            Attached to engagement #{String(job.engagement_id).padStart(4, '0')}.
          </p>
          <button onClick={() => navigate(`/engagements/${job.engagement_id}`)}
            className="text-[12px] text-[#e8c34a] hover:underline">Open the engagement</button>
        </div>
      )}
    </div>
  );
}
