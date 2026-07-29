import { useCallback, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { SlidersHorizontal, History, RefreshCw } from 'lucide-react';
import DriverPicker from '../components/DriverPicker';

const API = '/api';

function timeAgo(isoString) {
  if (!isoString) return '';
  const diff = (Date.now() - new Date(isoString).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function ProviderSettings() {
  const { user } = useOutletContext();
  // Writes are Admin-only: these settings decide which vendor sees client data.
  const canEdit = user?.role === 'Admin';

  const [capabilities, setCapabilities] = useState([]);
  const [healthByDriver, setHealthByDriver] = useState({});
  const [history, setHistory] = useState([]);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [capRes, histRes] = await Promise.all([
        fetch(`${API}/providers`, { credentials: 'include' }),
        fetch(`${API}/providers/history`, { credentials: 'include' }),
      ]);
      if (!capRes.ok) {
        const err = await capRes.json().catch(() => ({}));
        setError(err.error || 'Could not load providers.');
        return;
      }
      setCapabilities(await capRes.json());
      if (histRes.ok) setHistory(await histRes.json());
    } catch (err) {
      console.error(err);
      setError('Connection failed. Is the backend running?');
    }
  }, []);

  const fetchHealth = useCallback(async (force = false) => {
    setRefreshing(true);
    try {
      const res = await fetch(`${API}/providers/health${force ? '?refresh=1' : ''}`, { credentials: 'include' });
      if (!res.ok) return;
      const rows = await res.json();
      setHealthByDriver(Object.fromEntries(rows.map(r => [`${r.capability}:${r.driver_key}`, r])));
    } catch (err) {
      console.error(err);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchAll(); fetchHealth(); }, [fetchAll, fetchHealth]);

  return (
    <div className="px-8 py-6">
      {/* Rendered inside the Settings shell, which owns the page's h1. */}
      <div className="flex items-start justify-between gap-4 flex-wrap mb-1.5">
        <div className="flex items-center gap-2.5">
          <SlidersHorizontal size={16} className="text-[#c9971f]" />
          <h2 className="text-[#f7f5ef] text-[17px] font-semibold">Engines</h2>
        </div>
        <button
          onClick={() => fetchHealth(true)}
          disabled={refreshing}
          className="flex items-center gap-1.5 text-[12px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors disabled:opacity-50"
        >
          <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
          {refreshing ? 'Checking…' : 'Re-check health'}
        </button>
      </div>
      <p className="text-sm text-[#8a8a83] mb-7 max-w-2xl">
        Every pluggable engine in the system. Switching one takes effect on the next request — no restart.
        {!canEdit && ' Viewing only; an Admin can change these.'}
      </p>

      {error && <p role="alert" className="text-sm text-rose-500 mb-4">{error}</p>}

      <div className="flex flex-col gap-4">
        {capabilities.map(cap => (
          <DriverPicker
            key={cap.capability}
            capability={cap}
            healthByDriver={healthByDriver}
            canEdit={canEdit}
            onChanged={() => { fetchAll(); fetchHealth(true); }}
          />
        ))}
      </div>

      {history.length > 0 && (
        <div className="mt-8 rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
          <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
            <History size={14} className="text-[#8a8a83]" />
            <span className="text-[14px] font-semibold text-[#f2f0e8]">Change History</span>
          </div>
          <div className="px-5 py-3 flex flex-col divide-y" style={{ borderColor: '#191919' }}>
            {history.map(h => (
              <div key={h.id} className="py-2.5">
                <p className="text-[12px] text-[#d6d4c9]">
                  <span className="font-mono text-[#8a8a83]">{h.capability}</span>
                  {' '}{h.from_driver || 'unset'} → <span className="text-[#e8c34a]">{h.to_driver}</span>
                </p>
                <p className="text-[10px] text-[#5c5c55] font-mono mt-0.5">
                  {timeAgo(h.changed_at)}{h.reason ? ` · ${h.reason}` : ''}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
