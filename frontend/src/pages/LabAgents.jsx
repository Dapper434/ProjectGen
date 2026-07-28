import { useCallback, useEffect, useRef, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { FlaskConical, Play, Loader2 } from 'lucide-react';
import ComparisonTable from '../components/ComparisonTable';

const API = '/api';

// Model / prompt bake-off on a transcript already in the system. This is how you
// decide whether Nemotron is worth it over a local model for brief generation —
// on your own data, before committing.
export default function LabAgents() {
  const { user } = useOutletContext();
  const canRun = user?.role === 'Account Manager' || user?.role === 'Admin';
  const canAdopt = user?.role === 'Admin';

  const [drivers, setDrivers] = useState([]);
  const [selected, setSelected] = useState([]);
  const [text, setText] = useState('');
  const [run, setRun] = useState(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const pollRef = useRef(null);

  useEffect(() => {
    fetch(`${API}/providers`, { credentials: 'include' })
      .then(res => (res.ok ? res.json() : []))
      .then(caps => {
        const agent = caps.find(c => c.capability === 'agent_llm');
        const available = (agent?.drivers || []).filter(d => d.available);
        setDrivers(available);
        setSelected(available.slice(0, 2).map(d => d.key));
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
        pollRef.current = setTimeout(() => pollRun(runId), 2000);
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
    if (!text.trim()) {
      setError('Paste a transcript to run the comparison against.');
      return;
    }
    if (selected.length === 0) {
      setError('Pick at least one model.');
      return;
    }
    setStarting(true);
    setError('');
    setRun(null);
    try {
      const res = await fetch(`${API}/lab/generate`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ drivers: selected, text }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.error || 'Could not start the comparison.');
        return;
      }
      pollRun(data.run_id);
    } catch (err) {
      console.error(err);
      setError('Connection failed.');
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="px-8 py-7">
      <div className="flex items-center gap-2.5 mb-1.5">
        <FlaskConical size={18} className="text-[#c9971f]" />
        <h1 className="font-serif text-[#f7f5ef] text-2xl">Lab · Agents</h1>
      </div>
      <p className="text-sm text-[#8a8a83] mb-7 max-w-2xl">
        Run the same transcript through several models side by side, then adopt the winner.
        Models run one at a time so a bake-off never starves the agent pool.
      </p>

      {error && <p role="alert" className="text-sm text-rose-500 mb-4">{error}</p>}

      <div className="rounded-xl overflow-hidden mb-6" style={{ background: '#141414', border: '1px solid #242424' }}>
        <div className="px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
          <span className="text-[14px] font-semibold text-[#f2f0e8]">Input</span>
        </div>
        <div className="px-5 py-4 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="lab-text" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">
              TRANSCRIPT
            </label>
            <textarea
              id="lab-text"
              rows={6}
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder="Paste a meeting transcript to compare models against…"
              className="w-full rounded-lg px-3 py-2.5 text-[12px] text-[#d6d4c9] bg-[#0e0e0e] resize-y"
              style={{ border: '1px solid #262626' }}
            />
          </div>

          <fieldset>
            <legend className="text-[10px] font-mono tracking-wider text-[#8a8a83] mb-2">MODELS</legend>
            <div className="flex flex-wrap gap-3">
              {drivers.map(d => (
                <label key={d.key} htmlFor={`lab-${d.key}`} className="flex items-center gap-2 text-[12px] text-[#d6d4c9] cursor-pointer">
                  <input
                    id={`lab-${d.key}`}
                    type="checkbox"
                    checked={selected.includes(d.key)}
                    onChange={() => toggle(d.key)}
                    className="accent-[#c9971f]"
                  />
                  {d.label}
                </label>
              ))}
              {drivers.length === 0 && (
                <p className="text-[12px] text-[#5c5c55]">No available models — check Providers.</p>
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
            {starting ? 'Starting…' : 'Run comparison'}
          </button>
          {!canRun && (
            <p className="text-[11px] text-[#6e6e67]">The Lab is available to Account Managers and Admins.</p>
          )}
        </div>
      </div>

      {run && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-[14px] font-semibold text-[#f2f0e8]">Results</span>
            {run.status === 'running' && (
              <span className="flex items-center gap-1 text-[11px] text-[#8a8a83]" aria-live="polite">
                <Loader2 size={11} className="animate-spin" /> running…
              </span>
            )}
          </div>
          <ComparisonTable run={run} canAdopt={canAdopt} onAdopted={() => pollRun(run.id)} />
        </div>
      )}
    </div>
  );
}
