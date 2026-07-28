import { useCallback, useEffect, useRef, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { FlaskConical, Upload, Play, Loader2, GitCompare } from 'lucide-react';
import ComparisonTable from '../components/ComparisonTable';
import DiffView from '../components/DiffView';

const API = '/api';

// Audio bake-off: drop a recording, tick engines, run. This is how "is local
// good enough?" gets answered on the agency's own audio rather than on a vendor
// benchmark.
export default function LabTranscription() {
  const { user } = useOutletContext();
  const canRun = user?.role === 'Account Manager' || user?.role === 'Admin';
  const canAdopt = user?.role === 'Admin';

  const [drivers, setDrivers] = useState([]);
  const [selected, setSelected] = useState([]);
  const [file, setFile] = useState(null);
  const [run, setRun] = useState(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const [diffAgainst, setDiffAgainst] = useState(null);
  const pollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    fetch(`${API}/providers`, { credentials: 'include' })
      .then(res => (res.ok ? res.json() : []))
      .then(caps => {
        const batch = caps.find(c => c.capability === 'stt_batch');
        const usable = (batch?.drivers || []).filter(d => d.available && d.key !== 'off');
        setDrivers(usable);
        setSelected(usable.slice(0, 2).map(d => d.key));
      })
      .catch(err => console.error(err));
  }, []);

  const pollRun = useCallback(async (runId) => {
    try {
      const res = await fetch(`${API}/lab/runs/${runId}`, { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      setRun(data);
      if (data.status === 'running') {
        pollRef.current = setTimeout(() => pollRun(runId), 3000);
      }
    } catch (err) {
      console.error(err);
    }
  }, []);

  useEffect(() => () => clearTimeout(pollRef.current), []);

  function toggle(key) {
    setSelected(prev => (prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]));
  }

  async function start() {
    if (!file) { setError('Choose an audio or video file first.'); return; }
    if (selected.length === 0) { setError('Pick at least one engine.'); return; }
    setStarting(true); setError(''); setRun(null); setDiffAgainst(null);
    try {
      const body = new FormData();
      body.append('audio', file);
      body.append('drivers', selected.join(','));
      const res = await fetch(`${API}/lab/transcribe`, { method: 'POST', credentials: 'include', body });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setError(data.error || 'Could not start the comparison.'); return; }
      pollRun(data.run_id);
    } catch (err) {
      console.error(err);
      setError('Connection failed.');
    } finally {
      setStarting(false);
    }
  }

  const okResults = (run?.results || []).filter(r => r.status === 'ok' && r.output);
  const reference = okResults.find(r => r.metrics?.is_reference) || okResults[0];
  const candidate = okResults.find(r => r.id === diffAgainst);

  return (
    <div className="px-8 py-7">
      <div className="flex items-center gap-2.5 mb-1.5">
        <FlaskConical size={18} className="text-[#c9971f]" />
        <h1 className="font-serif text-[#f7f5ef] text-2xl">Lab · Transcription</h1>
      </div>
      <p className="text-sm text-[#8a8a83] mb-7 max-w-2xl">
        Run one recording through several speech engines and compare them word by word.
        Engines run one at a time, so a bake-off never starves the agent pool.
      </p>

      {error && <p role="alert" className="text-sm text-rose-500 mb-4">{error}</p>}

      <div className="rounded-xl overflow-hidden mb-6" style={{ background: '#141414', border: '1px solid #242424' }}>
        <div className="px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
          <span className="text-[14px] font-semibold text-[#f2f0e8]">Recording</span>
        </div>
        <div className="px-5 py-4 flex flex-col gap-4">
          <div>
            <input
              ref={inputRef}
              id="lab-audio"
              type="file"
              accept="audio/*,video/*"
              onChange={e => setFile(e.target.files?.[0] || null)}
              className="sr-only"
            />
            <button
              onClick={() => inputRef.current?.click()}
              className="flex items-center gap-2 px-3.5 py-2 rounded-lg text-[13px] text-[#d6d4c9] transition-colors hover:bg-[#1a1a1a]"
              style={{ border: '1px dashed #333' }}
            >
              <Upload size={14} className="text-[#8a8a83]" />
              {file ? file.name : 'Choose an audio or video file'}
            </button>
            {file && (
              <p className="text-[10px] font-mono text-[#5c5c55] mt-1.5">
                {(file.size / 1e6).toFixed(1)} MB · split into ~10-minute pieces server-side
              </p>
            )}
          </div>

          <fieldset>
            <legend className="text-[10px] font-mono tracking-wider text-[#8a8a83] mb-2">ENGINES</legend>
            <div className="flex flex-wrap gap-3">
              {drivers.map(d => (
                <label key={d.key} htmlFor={`stt-${d.key}`} className="flex items-center gap-2 text-[12px] text-[#d6d4c9] cursor-pointer">
                  <input
                    id={`stt-${d.key}`}
                    type="checkbox"
                    checked={selected.includes(d.key)}
                    onChange={() => toggle(d.key)}
                    className="accent-[#c9971f]"
                  />
                  {d.label}
                  <span className="text-[9px] font-mono text-[#5c5c55]">{d.is_local ? 'LOCAL' : 'CLOUD'}</span>
                </label>
              ))}
              {drivers.length === 0 && (
                <p className="text-[12px] text-[#5c5c55]">
                  No speech engine is available — check Providers. Groq needs an API key; local Whisper needs its server running.
                </p>
              )}
            </div>
          </fieldset>

          <button
            onClick={start}
            disabled={!canRun || starting}
            className="self-start flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-white text-[13px] font-medium transition-all hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}
          >
            {starting ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {starting ? 'Uploading…' : 'Run comparison'}
          </button>
          {!canRun && <p className="text-[11px] text-[#6e6e67]">The Lab is available to Account Managers and Admins.</p>}
        </div>
      </div>

      {run && (
        <div className="flex flex-col gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[14px] font-semibold text-[#f2f0e8]">Results</span>
              {run.status === 'running' && (
                <span className="flex items-center gap-1 text-[11px] text-[#8a8a83]" aria-live="polite">
                  <Loader2 size={11} className="animate-spin" /> transcribing…
                </span>
              )}
            </div>
            <ComparisonTable run={run} canAdopt={canAdopt} onAdopted={() => pollRun(run.id)} />
          </div>

          {okResults.length > 1 && reference && (
            <div>
              <div className="flex items-center gap-2 mb-3 flex-wrap">
                <GitCompare size={14} className="text-[#8a8a83]" />
                <span className="text-[14px] font-semibold text-[#f2f0e8]">Word-by-word diff</span>
                <div className="flex gap-2 flex-wrap ml-2">
                  {okResults.filter(r => r.id !== reference.id).map(r => (
                    <button
                      key={r.id}
                      onClick={() => setDiffAgainst(r.id === diffAgainst ? null : r.id)}
                      className={`text-[11px] px-2 py-1 rounded transition-colors ${
                        r.id === diffAgainst ? 'text-[#e8c34a] bg-[#c9971f]/15' : 'text-[#a3a39c] hover:text-[#e8c34a]'
                      }`}
                    >
                      vs {r.label}
                    </button>
                  ))}
                </div>
              </div>
              {candidate ? (
                <DiffView
                  referenceLabel={reference.label}
                  reference={reference.output}
                  candidateLabel={candidate.label}
                  candidate={candidate.output}
                />
              ) : (
                <p className="text-[12px] text-[#5c5c55]">Pick an engine above to diff it against {reference.label}.</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
