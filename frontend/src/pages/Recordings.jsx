import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { AudioLines, Upload, Loader2, CheckCircle2, AlertCircle, Clock } from 'lucide-react';
import ProviderBadge from '../components/ProviderBadge';

const API = '/api';

const STATUS_META = {
  queued:       { label: 'QUEUED',       color: '#64748b', bg: 'rgba(100,116,139,0.12)' },
  normalising:  { label: 'PREPARING',    color: '#0369a1', bg: 'rgba(14,165,233,0.12)' },
  transcribing: { label: 'TRANSCRIBING', color: '#a16207', bg: 'rgba(201,151,31,0.14)' },
  polishing:    { label: 'CLEANING UP',  color: '#7c3aed', bg: 'rgba(124,58,237,0.12)' },
  ready:        { label: 'READY',        color: '#047857', bg: 'rgba(16,185,129,0.12)' },
  attached:     { label: 'ATTACHED',     color: '#0369a1', bg: 'rgba(14,165,233,0.12)' },
  failed:       { label: 'FAILED',       color: '#e11d48', bg: 'rgba(225,29,72,0.12)' },
  cancelled:    { label: 'CANCELLED',    color: '#6e6e67', bg: 'rgba(110,110,103,0.12)' },
};

function humanSeconds(s) {
  if (!s && s !== 0) return null;
  if (s < 90) return `about ${Math.max(1, Math.round(s))} seconds`;
  return `about ${Math.round(s / 60)} minutes`;
}

export default function Recordings() {
  const navigate = useNavigate();
  const { user } = useOutletContext();
  const [jobs, setJobs] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [engagements, setEngagements] = useState([]);
  const [file, setFile] = useState(null);
  const [durationSec, setDurationSec] = useState(null);
  const [driverKey, setDriverKey] = useState('');
  const [engagementId, setEngagementId] = useState('');
  const [compare, setCompare] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef(null);
  const pollRef = useRef(null);

  const fetchJobs = useCallback(async () => {
    try {
      const res = await fetch(`${API}/recordings`, { credentials: 'include' });
      if (res.ok) setJobs(await res.json());
    } catch (err) { console.error(err); }
  }, []);

  useEffect(() => {
    fetchJobs();
    fetch(`${API}/providers`, { credentials: 'include' })
      .then(r => (r.ok ? r.json() : []))
      .then(caps => {
        const batch = caps.find(c => c.capability === 'stt_batch');
        const usable = (batch?.drivers || []).filter(d => d.available && d.key !== 'off');
        setDrivers(usable);
        setDriverKey(batch?.selected && usable.some(d => d.key === batch.selected)
          ? batch.selected : usable[0]?.key || '');
      })
      .catch(err => console.error(err));
    fetch(`${API}/engagements`, { credentials: 'include' })
      .then(r => (r.ok ? r.json() : []))
      .then(setEngagements)
      .catch(err => console.error(err));
  }, [fetchJobs]);

  // Poll while anything is in flight — progress must visibly advance or people
  // assume it hung and upload again.
  useEffect(() => {
    const active = jobs.some(j => !['ready', 'attached', 'failed', 'cancelled'].includes(j.status));
    clearTimeout(pollRef.current);
    if (active) pollRef.current = setTimeout(fetchJobs, 3000);
    return () => clearTimeout(pollRef.current);
  }, [jobs, fetchJobs]);

  function chooseFile(f) {
    setFile(f || null);
    setDurationSec(null);
    if (!f) return;
    // Probe duration client-side so the estimate appears before uploading.
    const el = document.createElement('video');
    el.preload = 'metadata';
    el.onloadedmetadata = () => {
      if (Number.isFinite(el.duration)) setDurationSec(el.duration);
      URL.revokeObjectURL(el.src);
    };
    el.src = URL.createObjectURL(f);
  }

  async function submit() {
    if (!file) { setError('Choose a recording first.'); return; }
    setBusy(true); setError('');
    try {
      const body = new FormData();
      body.append('audio', file);
      if (engagementId) body.append('engagement_id', engagementId);

      if (compare) {
        body.append('drivers', drivers.map(d => d.key).join(','));
        const res = await fetch(`${API}/recordings/compare`, { method: 'POST', credentials: 'include', body });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { setError(data.error || 'Could not start the comparison.'); return; }
        navigate('/lab/transcription');
        return;
      }

      body.append('driver_key', driverKey);
      const res = await fetch(`${API}/recordings`, { method: 'POST', credentials: 'include', body });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setError(data.error || 'Upload failed.'); return; }
      setFile(null); setDurationSec(null);
      if (inputRef.current) inputRef.current.value = '';
      fetchJobs();
      navigate(`/recordings/${data.id}`);
    } catch (err) {
      console.error(err);
      setError('Connection failed. Is the backend running?');
    } finally {
      setBusy(false);
    }
  }

  const chosen = drivers.find(d => d.key === driverKey);
  // The single most useful thing on this page: cloud-vs-local as a number.
  const estimate = durationSec && chosen
    ? humanSeconds(durationSec * (chosen.key.startsWith('groq') ? 0.033 : 1.05) + 5)
    : null;

  return (
    <div className="px-8 py-7">
      <div className="flex items-center gap-2.5 mb-1.5">
        <AudioLines size={18} className="text-[#c9971f]" />
        <h1 className="font-serif text-[#f7f5ef] text-2xl">Recording Studio</h1>
      </div>
      <p className="text-sm text-[#8a8a83] mb-7 max-w-2xl">
        Upload a meeting recording and get a transcript — fast in the cloud, or free and fully private
        on this machine. Review it, then send it into the same pipeline everything else uses.
      </p>

      {error && <p role="alert" className="text-sm text-rose-500 mb-4">{error}</p>}

      <div className="rounded-xl overflow-hidden mb-7" style={{ background: '#141414', border: '1px solid #242424' }}>
        <div className="px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
          <span className="text-[14px] font-semibold text-[#f2f0e8]">New recording</span>
        </div>
        <div className="px-5 py-4 flex flex-col gap-4">
          <div>
            <input
              ref={inputRef} id="rec-file" type="file" accept="audio/*,video/*"
              onChange={e => chooseFile(e.target.files?.[0])} className="sr-only"
            />
            <button
              onClick={() => inputRef.current?.click()}
              className="flex items-center gap-2 px-3.5 py-2.5 rounded-lg text-[13px] text-[#d6d4c9] transition-colors hover:bg-[#1a1a1a] w-full"
              style={{ border: '1px dashed #333' }}
            >
              <Upload size={14} className="text-[#8a8a83]" />
              {file ? file.name : 'Choose an audio or video file (mp3, m4a, wav, mp4, mov, webm)'}
            </button>
            {file && (
              <p className="text-[10px] font-mono text-[#5c5c55] mt-1.5">
                {(file.size / 1e6).toFixed(1)} MB
                {durationSec ? ` · ${Math.floor(durationSec / 60)}m ${Math.round(durationSec % 60)}s` : ''}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="rec-driver" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">ENGINE</label>
            <select
              id="rec-driver" value={driverKey} onChange={e => setDriverKey(e.target.value)}
              disabled={compare}
              className="rounded-lg px-3 py-2 text-[12px] text-[#d6d4c9] bg-[#0e0e0e] disabled:opacity-50"
              style={{ border: '1px solid #262626' }}
            >
              {drivers.map(d => <option key={d.key} value={d.key}>{d.label}</option>)}
              {drivers.length === 0 && <option value="">No engine available — check Providers</option>}
            </select>
            {chosen && (
              <p className="text-[11px] text-[#8a8a83]">
                {chosen.blurb}{' '}
                {estimate && <span className="text-[#e8c34a]">— {estimate}.</span>}
                {chosen.is_local && <span className="text-[#10b981]"> Nothing leaves this machine.</span>}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="rec-eng" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">
              ATTACH TO (OPTIONAL — CAN DECIDE LATER)
            </label>
            <select
              id="rec-eng" value={engagementId} onChange={e => setEngagementId(e.target.value)}
              className="rounded-lg px-3 py-2 text-[12px] text-[#d6d4c9] bg-[#0e0e0e]"
              style={{ border: '1px solid #262626' }}
            >
              <option value="">Decide later</option>
              {engagements.map(e => (
                <option key={e.id} value={e.id}>
                  {e.client_name} · #{String(e.id).padStart(4, '0')} ({e.status.replace(/_/g, ' ')})
                </option>
              ))}
            </select>
          </div>

          {drivers.length > 1 && (
            <label htmlFor="rec-compare" className="flex items-center gap-2 text-[12px] text-[#d6d4c9] cursor-pointer">
              <input id="rec-compare" type="checkbox" checked={compare}
                onChange={e => setCompare(e.target.checked)} className="accent-[#c9971f]" />
              Transcribe with every engine and compare them side by side
            </label>
          )}

          <button
            onClick={submit} disabled={busy || !file}
            className="self-start flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-white text-[13px] font-medium transition-all hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <AudioLines size={14} />}
            {busy ? 'Uploading…' : compare ? 'Transcribe & compare' : 'Transcribe'}
          </button>
        </div>
      </div>

      <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
        <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
          <Clock size={14} className="text-[#8a8a83]" />
          <span className="text-[14px] font-semibold text-[#f2f0e8]">Recordings</span>
        </div>
        {jobs.length === 0 ? (
          <p className="px-5 py-10 text-center text-[13px] text-[#8a8a83]">No recordings yet.</p>
        ) : (
          <div className="divide-y" style={{ borderColor: '#191919' }}>
            {jobs.map(job => {
              const meta = STATUS_META[job.status] || STATUS_META.queued;
              const active = !['ready', 'attached', 'failed', 'cancelled'].includes(job.status);
              return (
                <div key={job.id}
                  onClick={() => navigate(`/recordings/${job.id}`)}
                  className="px-5 py-3.5 cursor-pointer hover:bg-[#1a1a1a] transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-medium text-[#d6d4c9] truncate">{job.title || job.source_name}</p>
                      <p className="text-[10px] text-[#5c5c55] font-mono mt-0.5">
                        {job.duration_sec ? `${Math.round(job.duration_sec / 60)}m · ` : ''}
                        {job.driver_label}
                        {active && job.pieces_total ? ` · piece ${job.pieces_done} of ${job.pieces_total}` : ''}
                      </p>
                    </div>
                    {job.status === 'ready' && <CheckCircle2 size={13} className="text-[#10b981] shrink-0" />}
                    {job.status === 'failed' && <AlertCircle size={13} className="text-[#e11d48] shrink-0" />}
                    <span className="text-[10px] font-mono font-semibold px-2 py-1 rounded-md shrink-0"
                      style={{ color: meta.color, background: meta.bg }}>{meta.label}</span>
                  </div>
                  {active && (
                    <div className="mt-2 h-1 rounded-full overflow-hidden" style={{ background: '#262626' }}>
                      <div className="h-full transition-[width] duration-500"
                        style={{ width: `${job.progress_pct || 0}%`, background: '#c9971f' }} />
                    </div>
                  )}
                  {job.status === 'ready' && (
                    <div className="mt-1.5">
                      <ProviderBadge driverLabel={job.driver_label} isLocal={job.is_local} latencyMs={job.latency_ms} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
