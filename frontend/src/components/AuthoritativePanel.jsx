import { useCallback, useEffect, useState } from 'react';
import { BookOpen, Pencil } from 'lucide-react';
import AuthoritativeEditor from './AuthoritativeEditor';

const API = '/api';

const SCOPE_META = {
  global: { label: 'GLOBAL', color: '#64748b', bg: 'rgba(100,116,139,0.12)' },
  client: { label: 'CLIENT OVERRIDE', color: '#0ea5e9', bg: 'rgba(14,165,233,0.12)' },
  engagement: { label: 'ENGAGEMENT OVERRIDE', color: '#c9971f', bg: 'rgba(201,151,31,0.14)' },
};

function preview(body, fmt) {
  if (!body) return null;
  const text = fmt === 'json' ? JSON.stringify(body) : body;
  return text.length > 160 ? `${text.slice(0, 160)}…` : text;
}

// Embeddable read-only card + "Edit" affordance — the answer to the blueprint's
// "viewable for more sections of the system" requirement (WP-1 §1.6). Mounts
// wherever context demands: EngagementDetail, ClientDetail, admin screens.
// `keys` resolve against `engagementId`/`clientId` for display; edits always
// write to the explicit `editScopeType`/`editScopeId` the caller passes — e.g.
// ClientDetail edits create a client-scoped override rather than silently
// overwriting the global default.
export default function AuthoritativePanel({
  keys, title = 'Authoritative Data', engagementId, clientId,
  editScopeType = 'global', editScopeId = null, canEdit = false,
}) {
  const [registry, setRegistry] = useState({});
  const [entries, setEntries] = useState({});
  const [editingKey, setEditingKey] = useState(null);

  const fetchAll = useCallback(async () => {
    const regRes = await fetch(`${API}/authoritative/registry`, { credentials: 'include' });
    if (regRes.ok) setRegistry(await regRes.json());

    const results = {};
    await Promise.all(keys.map(async key => {
      const params = new URLSearchParams();
      if (engagementId) params.set('engagement_id', engagementId);
      if (clientId) params.set('client_id', clientId);
      try {
        const res = await fetch(`${API}/authoritative/resolve/${key}?${params}`, { credentials: 'include' });
        results[key] = res.ok ? await res.json() : { body: null, provenance: null };
      } catch {
        results[key] = { body: null, provenance: null };
      }
    }));
    setEntries(results);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys.join(','), engagementId, clientId]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  return (
    <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
      <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
        <BookOpen size={14} className="text-[#8a8a83]" />
        <span className="text-[14px] font-semibold text-[#f2f0e8]">{title}</span>
      </div>
      <div className="divide-y" style={{ borderColor: '#191919' }}>
        {keys.map(key => {
          const entry = entries[key];
          const regEntry = registry[key];
          const scopeMeta = entry?.provenance ? SCOPE_META[entry.provenance.scope] : null;
          return (
            <div key={key} className="flex items-start justify-between gap-3 px-5 py-3.5">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <p className="text-[12px] font-medium text-[#d6d4c9]">{regEntry?.title || key}</p>
                  {scopeMeta ? (
                    <span className="text-[9px] font-mono font-semibold px-1.5 py-0.5 rounded" style={{ color: scopeMeta.color, background: scopeMeta.bg }}>
                      {scopeMeta.label} · v{entry.provenance.version}
                    </span>
                  ) : (
                    <span className="text-[9px] font-mono text-[#5c5c55]">NOT SET</span>
                  )}
                </div>
                <p className="text-[11px] text-[#8a8a83] leading-relaxed">
                  {preview(entry?.body, regEntry?.fmt) || 'Nothing on file — falls back to hardcoded defaults.'}
                </p>
              </div>
              {canEdit && (
                <button
                  aria-label={`Edit ${regEntry?.title || key}`}
                  onClick={() => setEditingKey(key)}
                  className="shrink-0 flex items-center gap-1 text-[11px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors"
                >
                  <Pencil size={11} />
                  Edit
                </button>
              )}
            </div>
          );
        })}
      </div>

      {editingKey && (
        <AuthoritativeEditor
          keyName={editingKey}
          registryEntry={registry[editingKey]}
          scopeType={editScopeType}
          scopeId={editScopeId}
          canEdit={canEdit}
          onClose={() => setEditingKey(null)}
          onSaved={fetchAll}
        />
      )}
    </div>
  );
}
