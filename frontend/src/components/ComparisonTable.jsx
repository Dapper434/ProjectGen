import { useState } from 'react';
import { Check, Loader2, AlertCircle } from 'lucide-react';

const API = '/api';

function Metric({ label, value }) {
  return (
    <div className="flex flex-col">
      <span className="text-[9px] font-mono tracking-wider text-[#5c5c55]">{label}</span>
      <span className="text-[12px] text-[#d6d4c9]">{value ?? '—'}</span>
    </div>
  );
}

// Side-by-side bake-off results with a "Use this one" button that writes the
// runtime setting, so a comparison is never wasted work.
export default function ComparisonTable({ run, canAdopt, onAdopted }) {
  const [adopting, setAdopting] = useState(null);
  const [error, setError] = useState('');

  async function adopt(driverKey) {
    setAdopting(driverKey);
    setError('');
    try {
      const res = await fetch(`${API}/lab/runs/${run.id}/adopt`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ driver_key: driverKey, capability: run.capability }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.error || 'Could not adopt this driver.');
        return;
      }
      onAdopted?.(data);
    } catch (err) {
      console.error(err);
      setError('Connection failed.');
    } finally {
      setAdopting(null);
    }
  }

  return (
    <div>
      {error && <p role="alert" className="text-xs text-rose-500 mb-3">{error}</p>}
      <div className="overflow-x-auto">
        <div className="flex gap-4 min-w-min">
          {run.results.map(result => {
            const similarity = result.metrics?.similarity_to_reference;
            const isReference = result.metrics?.is_reference;
            return (
              <div
                key={result.id}
                className="w-[340px] shrink-0 rounded-xl overflow-hidden flex flex-col"
                style={{ background: '#141414', border: '1px solid #242424' }}
              >
                <div className="px-4 py-3" style={{ borderBottom: '1px solid #242424' }}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-[13px] font-medium text-[#f2f0e8]">{result.label}</p>
                    {isReference && (
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded"
                        style={{ color: '#0ea5e9', background: 'rgba(14,165,233,0.12)' }}>REFERENCE</span>
                    )}
                  </div>
                  <p className="text-[10px] font-mono text-[#5c5c55] mt-0.5">{result.driver_key}</p>
                </div>

                <div className="px-4 py-3 grid grid-cols-3 gap-3" style={{ borderBottom: '1px solid #191919' }}>
                  <Metric label="LATENCY" value={result.latency_ms != null ? `${(result.latency_ms / 1000).toFixed(1)}s` : null} />
                  <Metric label="WORDS" value={result.word_count} />
                  <Metric label="TOKENS" value={result.tokens_used} />
                  <Metric label="EST. COST" value={result.est_cost_usd != null ? `~$${result.est_cost_usd.toFixed(4)}` : null} />
                  <Metric
                    label="AGREES"
                    value={similarity != null && !isReference ? `${(similarity * 100).toFixed(0)}%` : null}
                  />
                </div>

                <div className="px-4 py-3 flex-1 min-h-[140px]">
                  {result.status === 'pending' && (
                    <p className="flex items-center gap-1.5 text-[12px] text-[#8a8a83]" aria-live="polite">
                      <Loader2 size={12} className="animate-spin" /> Running…
                    </p>
                  )}
                  {result.status === 'error' && (
                    <p className="flex items-start gap-1.5 text-[11px] text-[#f43f5e]">
                      <AlertCircle size={12} className="shrink-0 mt-0.5" /> {result.error}
                    </p>
                  )}
                  {result.status === 'ok' && (
                    <pre className="text-[11px] text-[#a3a39c] whitespace-pre-wrap font-mono max-h-64 overflow-y-auto">
                      {result.output}
                    </pre>
                  )}
                </div>

                {canAdopt && result.status === 'ok' && (
                  <div className="px-4 py-3" style={{ borderTop: '1px solid #191919' }}>
                    <button
                      onClick={() => adopt(result.driver_key)}
                      disabled={adopting === result.driver_key}
                      className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg text-white text-[12px] font-medium transition-all hover:opacity-90 disabled:opacity-50"
                      style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}
                    >
                      <Check size={12} />
                      {adopting === result.driver_key ? 'Adopting…' : 'Use this one'}
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <p className="text-[10px] text-[#5c5c55] mt-3">
        “Agrees” is similarity to the first successful column, not accuracy — there is no ground truth here.
        Cost is an estimate from a per-driver rate, not a bill.
      </p>
    </div>
  );
}
