import { useCallback, useEffect, useRef, useState } from 'react';
import { X, Save, Trash2, Upload } from 'lucide-react';

const API = '/api';

export const DOC_TYPES = [
  { id: 'brief', label: 'Production Briefs' },
  { id: 'proposal', label: 'Client Proposals' },
  { id: 'general', label: 'Both' },
];

export const DOC_TYPE_LABEL = Object.fromEntries(DOC_TYPES.map(t => [t.id, t.label]));

// Create or edit one requirement document — the corpus the completeness checker
// grades generated briefs and proposals against. Sibling of AuthoritativeEditor,
// deliberately simpler: these are free text, not versioned agent instructions,
// so there is no history pane and no rollback.
export default function RequirementEditor({ docId, canEdit, onClose, onSaved }) {
  const isNew = docId == null;
  const [title, setTitle] = useState('');
  const [docType, setDocType] = useState('brief');
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const fileInputRef = useRef(null);

  const fetchDoc = useCallback(async () => {
    if (isNew) return;
    try {
      const res = await fetch(`${API}/requirements/${docId}`, { credentials: 'include' });
      if (!res.ok) { setError('Could not load that document.'); return; }
      const data = await res.json();
      setTitle(data.title || '');
      setDocType(data.doc_type || 'brief');
      setText(data.raw_text || '');
    } catch {
      setError('Connection failed. Is the backend running?');
    } finally {
      setLoading(false);
    }
  }, [docId, isNew]);

  useEffect(() => { fetchDoc(); }, [fetchDoc]);

  const readFile = useCallback((file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setText(String(reader.result || ''));
    reader.readAsText(file);
  }, []);

  async function handleSave() {
    if (!title.trim() || !text.trim()) {
      setError('A title and the document text are both required.');
      return;
    }
    setSaving(true); setError('');
    try {
      const res = await fetch(isNew ? `${API}/requirements` : `${API}/requirements/${docId}`, {
        method: isNew ? 'POST' : 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), doc_type: docType, raw_text: text }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setError(data.error || 'Save failed.'); return; }
      onSaved?.();
      onClose?.();
    } catch {
      setError('Connection failed. Is the backend running?');
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove() {
    setRemoving(true); setError('');
    try {
      const res = await fetch(`${API}/requirements/${docId}/deactivate`, {
        method: 'POST', credentials: 'include',
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.error || 'Could not remove that document.');
        return;
      }
      onSaved?.();
      onClose?.();
    } catch {
      setError('Connection failed. Is the backend running?');
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4" onClick={onClose}>
      <div
        role="dialog"
        aria-label={isNew ? 'New requirement document' : `Edit ${title}`}
        onClick={e => e.stopPropagation()}
        className="w-full max-w-2xl max-h-[85vh] flex flex-col rounded-xl overflow-hidden"
        style={{ background: '#141414', border: '1px solid #242424' }}
      >
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
          <div>
            <p className="text-[14px] font-semibold text-[#f2f0e8]">
              {isNew ? 'New requirement document' : title || 'Requirement document'}
            </p>
            <p className="text-[10px] font-mono text-[#5c5c55] mt-0.5">
              Graded against every generated {docType === 'general' ? 'brief and proposal' : docType}
            </p>
          </div>
          <button aria-label="Close editor" onClick={onClose} className="text-[#8a8a83] hover:text-[#f7f5ef] transition-colors">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4">
          {error && <p role="alert" className="text-xs text-rose-500">{error}</p>}
          {loading ? (
            <p className="text-xs text-[#5c5c55]">Loading…</p>
          ) : (
            <>
              <div className="grid sm:grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="req-title" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">TITLE</label>
                  <input
                    id="req-title"
                    value={title}
                    onChange={e => setTitle(e.target.value)}
                    disabled={!canEdit}
                    placeholder="e.g. Brief Requirements Checklist"
                    className="rounded-lg px-3 py-2 text-[13px] text-[#d6d4c9] bg-[#0e0e0e] placeholder:text-[#5c5c55] disabled:opacity-60"
                    style={{ border: '1px solid #262626' }}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="req-type" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">APPLIES TO</label>
                  <select
                    id="req-type"
                    value={docType}
                    onChange={e => setDocType(e.target.value)}
                    disabled={!canEdit}
                    className="rounded-lg px-3 py-2 text-[13px] text-[#d6d4c9] bg-[#0e0e0e] disabled:opacity-60"
                    style={{ border: '1px solid #262626' }}
                  >
                    {DOC_TYPES.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
                  </select>
                </div>
              </div>

              {canEdit && (
                <div
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={e => { e.preventDefault(); setDragging(true); }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={e => { e.preventDefault(); setDragging(false); readFile(e.dataTransfer.files?.[0]); }}
                  className={`border-2 border-dashed rounded-lg py-3 text-center transition-all cursor-pointer ${
                    dragging ? 'border-[#c9971f]/60 bg-[#c9971f]/10' : 'border-[#262626] hover:border-[#333333]'
                  }`}
                >
                  <Upload size={15} className="mx-auto text-[#5c5c55] mb-1" />
                  <p className="text-[11px] text-[#8a8a83]">
                    Drop a .txt/.md file to replace the text below, or <span className="text-[#c9971f]">browse</span>
                  </p>
                  <input ref={fileInputRef} type="file" accept=".txt,.md,text/plain,text/markdown"
                    className="hidden" onChange={e => readFile(e.target.files?.[0])} />
                </div>
              )}

              <div className="flex flex-col gap-1.5">
                <label htmlFor="req-body" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">DOCUMENT TEXT</label>
                <textarea
                  id="req-body"
                  value={text}
                  onChange={e => setText(e.target.value)}
                  disabled={!canEdit}
                  rows={14}
                  placeholder="What must a complete document contain? Write it the way you'd brief a new hire — the checker only flags things this text actually asks for."
                  className="rounded-lg px-3 py-2.5 text-[12px] font-mono text-[#d6d4c9] bg-[#0e0e0e] placeholder:text-[#5c5c55] resize-y disabled:opacity-60"
                  style={{ border: '1px solid #262626' }}
                />
                <p className="text-[10px] text-[#5c5c55]">{text.length.toLocaleString()} characters</p>
              </div>
            </>
          )}
        </div>

        {canEdit && !loading && (
          <div className="flex items-center gap-3 px-5 py-3.5" style={{ borderTop: '1px solid #242424' }}>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-white text-[12px] font-medium transition-all hover:opacity-90 disabled:opacity-50"
              style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}
            >
              <Save size={13} />
              {saving ? 'Saving…' : isNew ? 'Add document' : 'Save changes'}
            </button>
            {!isNew && (
              <button
                onClick={handleRemove}
                disabled={removing}
                className="ml-auto flex items-center gap-1.5 text-[12px] text-[#8a8a83] hover:text-rose-500 transition-colors disabled:opacity-50"
              >
                <Trash2 size={12} />
                {removing ? 'Removing…' : 'Remove from the Playbook'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
