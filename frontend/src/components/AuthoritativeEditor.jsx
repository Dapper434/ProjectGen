import { useCallback, useEffect, useState } from 'react';
import { X, History, RotateCcw, Save } from 'lucide-react';

const API = '/api';

function timeAgo(isoString) {
  if (!isoString) return '';
  const diff = (Date.now() - new Date(isoString).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

const SCOPE_LABEL = { global: 'Global', client: 'Client', engagement: 'Engagement' };

// Raw editor + version history + rollback for one authoritative key at one
// scope. Embedded both by AuthoritativePanel's "Edit" affordance and by the
// admin AuthoritativeData page — see docs/THE_EXODUS_Master_Implementation_Blueprint.md WP-1 §1.6.
export default function AuthoritativeEditor({ keyName, registryEntry, scopeType, scopeId, canEdit, onClose, onSaved }) {
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [body, setBody] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  const fetchVersions = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ scope_type: scopeType });
      if (scopeId != null) params.set('scope_id', scopeId);
      const res = await fetch(`${API}/authoritative/${keyName}/versions?${params}`, { credentials: 'include' });
      if (!res.ok) {
        setError('Could not load version history.');
        return;
      }
      const data = await res.json();
      setVersions(data);
      const active = data.find(v => v.is_active);
      setBody(active ? active.body : '');
    } catch (err) {
      console.error(err);
      setError('Connection failed.');
    } finally {
      setLoading(false);
    }
  }, [keyName, scopeType, scopeId]);

  useEffect(() => { fetchVersions(); }, [fetchVersions]);

  async function handleSave() {
    setSaving(true);
    setError('');
    try {
      const res = await fetch(`${API}/authoritative`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          key: keyName,
          scope_type: scopeType,
          scope_id: scopeId,
          title: registryEntry?.title || keyName,
          fmt: registryEntry?.fmt || 'markdown',
          body,
          note: note || undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.error || 'Save failed.');
        return;
      }
      setNote('');
      await fetchVersions();
      onSaved?.();
    } catch (err) {
      console.error(err);
      setError('Connection failed.');
    } finally {
      setSaving(false);
    }
  }

  async function handleRollback(versionId) {
    setError('');
    try {
      const res = await fetch(`${API}/authoritative/${versionId}/activate`, { method: 'POST', credentials: 'include' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.error || 'Rollback failed.');
        return;
      }
      await fetchVersions();
      onSaved?.();
    } catch (err) {
      console.error(err);
      setError('Connection failed.');
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4" onClick={onClose}>
      <div
        role="dialog"
        aria-label={`Edit ${registryEntry?.title || keyName}`}
        onClick={e => e.stopPropagation()}
        className="w-full max-w-2xl max-h-[85vh] flex flex-col rounded-xl overflow-hidden"
        style={{ background: '#141414', border: '1px solid #242424' }}
      >
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
          <div>
            <p className="text-[14px] font-semibold text-[#f2f0e8]">{registryEntry?.title || keyName}</p>
            <p className="text-[10px] font-mono text-[#5c5c55] mt-0.5">
              {keyName} · {SCOPE_LABEL[scopeType] || scopeType}{scopeId != null ? ` #${scopeId}` : ''}
            </p>
          </div>
          <button aria-label="Close editor" onClick={onClose} className="text-[#8a8a83] hover:text-[#f7f5ef] transition-colors">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4">
          {error && <p role="alert" className="text-xs text-rose-500">{error}</p>}

          {canEdit ? (
            <div className="flex flex-col gap-2">
              <label htmlFor="auth-editor-body" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">
                {(registryEntry?.fmt || 'markdown').toUpperCase()} BODY
              </label>
              <textarea
                id="auth-editor-body"
                value={body}
                onChange={e => setBody(e.target.value)}
                rows={12}
                className="w-full rounded-lg px-3 py-2.5 text-[12px] font-mono text-[#d6d4c9] bg-[#0e0e0e] resize-y"
                style={{ border: '1px solid #262626' }}
              />
              <label htmlFor="auth-editor-note" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">CHANGELOG NOTE (OPTIONAL)</label>
              <input
                id="auth-editor-note"
                value={note}
                onChange={e => setNote(e.target.value)}
                placeholder="What changed and why"
                className="w-full rounded-lg px-3 py-2 text-[12px] text-[#d6d4c9] bg-[#0e0e0e]"
                style={{ border: '1px solid #262626' }}
              />
              <button
                onClick={handleSave}
                disabled={saving || !body.trim()}
                className="self-start flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-white text-[12px] font-medium transition-all hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}
              >
                <Save size={13} />
                {saving ? 'Saving…' : 'Save as new version'}
              </button>
            </div>
          ) : (
            <p className="text-xs text-[#8a8a83] whitespace-pre-wrap font-mono">{body || 'Nothing set at this scope yet.'}</p>
          )}

          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <History size={12} className="text-[#8a8a83]" />
              <span className="text-[10px] font-mono tracking-wider text-[#8a8a83]">VERSION HISTORY</span>
            </div>
            {loading ? (
              <p className="text-xs text-[#5c5c55]">Loading…</p>
            ) : versions.length === 0 ? (
              <p className="text-xs text-[#5c5c55]">Nothing saved at this scope yet.</p>
            ) : (
              <div className="flex flex-col divide-y" style={{ borderColor: '#191919' }}>
                {versions.map(v => (
                  <div key={v.id} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <p className="text-[12px] text-[#d6d4c9]">
                        v{v.version}{v.label ? ` (${v.label})` : ''}{v.is_active && <span className="ml-2 text-[10px] font-mono text-[#10b981]">ACTIVE</span>}
                      </p>
                      <p className="text-[10px] text-[#5c5c55] font-mono truncate">
                        {timeAgo(v.updated_at)}{v.note ? ` · ${v.note}` : ''}
                      </p>
                    </div>
                    {canEdit && !v.is_active && (
                      <button
                        onClick={() => handleRollback(v.id)}
                        className="shrink-0 flex items-center gap-1 text-[11px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors"
                      >
                        <RotateCcw size={11} />
                        Restore
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
