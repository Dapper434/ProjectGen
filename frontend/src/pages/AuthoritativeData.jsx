import { useCallback, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { BookOpen, Pencil, ChevronRight } from 'lucide-react';
import AuthoritativeEditor from '../components/AuthoritativeEditor';

const API = '/api';

// Admin list: every registered authoritative key, its global-scope version,
// and an editor. Client/engagement overrides are managed from AuthoritativePanel
// on their own detail pages instead — this page is the "system knowledge" home,
// mainly the five agent prompts (see docs/THE_EXODUS_Master_Implementation_Blueprint.md WP-1).
export default function AuthoritativeData() {
  const { user } = useOutletContext();
  const canEdit = user?.role === 'Account Manager' || user?.role === 'Admin';

  const [entries, setEntries] = useState([]);
  const [error, setError] = useState('');
  const [editingKey, setEditingKey] = useState(null);

  const fetchAll = useCallback(async () => {
    try {
      const res = await fetch(`${API}/authoritative?scope_type=global`, { credentials: 'include' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError(err.error || 'Could not load authoritative data.');
        return;
      }
      setEntries(await res.json());
    } catch (err) {
      console.error(err);
      setError('Connection failed. Is the backend running?');
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const editingEntry = entries.find(e => e.key === editingKey);

  return (
    <div className="px-8 py-7">
      <div className="flex items-center gap-2.5 mb-1.5">
        <BookOpen size={18} className="text-[#c9971f]" />
        <h1 className="font-serif text-[#f7f5ef] text-2xl">Authoritative Data</h1>
      </div>
      <p className="text-sm text-[#8a8a83] mb-7 max-w-2xl">
        Versioned system knowledge every agent reads instead of a hardcoded constant — prompts today,
        rate cards and protocols as later work packages land. Editing creates a new version; nothing
        is ever overwritten in place.
      </p>

      {error && <p role="alert" className="text-sm text-rose-500 mb-4">{error}</p>}

      <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
        <div className="divide-y" style={{ borderColor: '#191919' }}>
          {entries.map(entry => {
            const active = entry.active_docs?.[0];
            return (
              <div
                key={entry.key}
                onClick={() => canEdit && setEditingKey(entry.key)}
                className={`flex items-center gap-3 px-5 py-3.5 ${canEdit ? 'cursor-pointer hover:bg-[#1a1a1a]' : ''} transition-colors group`}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-[13px] font-medium text-[#d6d4c9]">{entry.title}</p>
                    <span className="text-[9px] font-mono text-[#5c5c55] uppercase">{entry.fmt}</span>
                    {entry.variants && <span className="text-[9px] font-mono text-[#a78bfa]">VARIANTS</span>}
                  </div>
                  <p className="text-[10px] text-[#5c5c55] font-mono mt-0.5">
                    {entry.key} · scopes: {entry.scopes.join(', ')}
                    {entry.consumers.length > 0 ? ` · used by ${entry.consumers.join(', ')}` : ''}
                  </p>
                </div>
                {active ? (
                  <span className="text-[10px] font-mono font-semibold px-2 py-1 rounded-md shrink-0" style={{ color: '#10b981', background: 'rgba(16,185,129,0.12)' }}>
                    v{active.version} ACTIVE
                  </span>
                ) : (
                  <span className="text-[10px] font-mono text-[#5c5c55] shrink-0">NOT SET</span>
                )}
                {canEdit && <Pencil size={12} className="text-[#5c5c55] group-hover:text-[#c9971f] transition-colors shrink-0" />}
                {canEdit && <ChevronRight size={13} className="text-[#5c5c55] group-hover:text-[#c9971f] transition-colors shrink-0" />}
              </div>
            );
          })}
        </div>
      </div>

      {editingKey && (
        <AuthoritativeEditor
          keyName={editingKey}
          registryEntry={editingEntry}
          scopeType="global"
          scopeId={null}
          canEdit={canEdit}
          onClose={() => setEditingKey(null)}
          onSaved={fetchAll}
        />
      )}
    </div>
  );
}
