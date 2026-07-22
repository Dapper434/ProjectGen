import { useCallback, useEffect, useRef, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { ClipboardCheck, Upload, Trash2, FileText } from 'lucide-react';
import { timeAgo } from '../lib/engagements';

const API = '/api';

const DOC_TYPES = [
  { id: 'brief', label: 'Brief Requirements' },
  { id: 'proposal', label: 'Proposal Structure' },
  { id: 'general', label: 'General (applies to both)' },
];

const DOC_TYPE_LABEL = Object.fromEntries(DOC_TYPES.map(t => [t.id, t.label]));

export default function Requirements() {
  const { user } = useOutletContext();
  const canManage = user?.role === 'Account Manager' || user?.role === 'Admin';

  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState('');
  const [docType, setDocType] = useState('brief');
  const [text, setText] = useState('');
  const [dragging, setDragging] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const fileInputRef = useRef(null);

  const fetchDocs = useCallback(async () => {
    try {
      const res = await fetch(`${API}/requirements`, { credentials: 'include' });
      if (res.ok) setDocs(await res.json());
    } catch (err) {
      console.error(err);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  const readFile = useCallback((file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setText(String(reader.result || ''));
    reader.readAsText(file);
  }, []);

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!title.trim() || !text.trim()) {
      setError('A title and the document text are both required.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const res = await fetch(`${API}/requirements`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), doc_type: docType, raw_text: text }),
        credentials: 'include',
      });
      if (res.ok) {
        setTitle('');
        setText('');
        await fetchDocs();
      } else {
        const err = await res.json().catch(() => ({}));
        setError(err.error || 'Upload failed.');
      }
    } catch (err) {
      console.error(err);
      setError('Connection failed. Is the backend running?');
    }
    setSaving(false);
  };

  const handleDeactivate = async (id) => {
    try {
      const res = await fetch(`${API}/requirements/${id}/deactivate`, { method: 'POST', credentials: 'include' });
      if (res.ok) await fetchDocs();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-8 py-8">
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <ClipboardCheck size={18} className="text-[#c9971f]" />
          <h1 className="font-serif text-[#f7f5ef] text-2xl">Requirements</h1>
        </div>
        <p className="text-sm text-[#a3a39c]">
          Authoritative documents describing what a complete brief or proposal must contain. The Exodus checks generated documents against these and flags what's missing.
        </p>
      </div>

      {canManage && (
        <form onSubmit={handleUpload} className="bg-[#141414] border border-[#262626] rounded-xl p-5 mb-7 flex flex-col gap-4">
          <p className="text-xs font-mono text-[#6e6e67] uppercase tracking-widest">Add a Requirements Document</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-[#a3a39c] mb-1.5">Title</label>
              <input
                type="text"
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="e.g. Brief Requirements Checklist"
                className="w-full bg-[#1a1a1a] border border-[#262626] rounded-lg px-3 py-2.5 text-sm text-[#f7f5ef] placeholder:text-[#6e6e67] focus:outline-none focus:border-[#c9971f]/60 transition-colors"
              />
            </div>
            <div>
              <label className="block text-xs text-[#a3a39c] mb-1.5">Applies to</label>
              <select
                value={docType}
                onChange={e => setDocType(e.target.value)}
                className="w-full bg-[#1a1a1a] border border-[#262626] rounded-lg px-3 py-2.5 text-sm text-[#f7f5ef] focus:outline-none focus:border-[#c9971f]/60 transition-colors"
              >
                {DOC_TYPES.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select>
            </div>
          </div>

          <div
            onClick={() => fileInputRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => { e.preventDefault(); setDragging(false); readFile(e.dataTransfer.files?.[0]); }}
            className={`border-2 border-dashed rounded-lg p-5 text-center transition-all cursor-pointer ${
              dragging ? 'border-[#c9971f]/60 bg-[#c9971f]/10' : 'border-[#262626] hover:border-[#333333]'
            }`}
          >
            <Upload size={18} className="mx-auto text-[#6e6e67] mb-1.5" />
            <p className="text-xs text-[#a3a39c]">Drop a .txt/.md file here, or <span className="text-[#c9971f]">browse</span></p>
            <input ref={fileInputRef} type="file" accept=".txt,.md,text/plain,text/markdown" className="hidden" onChange={e => readFile(e.target.files?.[0])} />
          </div>

          <textarea
            rows={6}
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="Or paste the requirements document text here…"
            className="w-full bg-[#1a1a1a] border border-[#262626] rounded-lg px-3 py-2.5 text-xs text-[#f7f5ef] placeholder:text-[#6e6e67] focus:outline-none focus:border-[#c9971f]/50 resize-none font-mono"
          />

          {error && <p role="alert" className="text-xs text-rose-500">{error}</p>}

          <button
            type="submit"
            disabled={saving}
            className="self-end flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[#c9971f] hover:bg-[#a67a17] text-white text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-wait"
          >
            {saving ? 'Uploading…' : 'Upload Document'}
          </button>
        </form>
      )}

      <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
        <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
          <FileText size={14} className="text-[#8a8a83]" />
          <span className="text-[14px] font-semibold text-[#f2f0e8]">On File</span>
        </div>
        {loading ? (
          <div className="px-5 py-8 text-center text-[13px] text-[#8a8a83]">Loading…</div>
        ) : docs.length === 0 ? (
          <div className="px-5 py-8 text-center text-[13px] text-[#8a8a83]">
            No requirements documents uploaded yet — completeness checks are inactive until at least one exists.
          </div>
        ) : (
          <div className="divide-y" style={{ borderColor: '#191919' }}>
            {docs.map(d => (
              <div key={d.id} className="flex items-center gap-3 px-5 py-3.5">
                <div className="flex-1 min-w-0">
                  <p className="text-[13px] font-medium text-[#d6d4c9] truncate">{d.title}</p>
                  <p className="text-[11px] text-[#5c5c55] font-mono">
                    {DOC_TYPE_LABEL[d.doc_type] || d.doc_type} · {d.length.toLocaleString()} chars · {d.uploaded_by || 'unknown'} · {timeAgo(d.uploaded_at)}
                  </p>
                </div>
                {canManage && (
                  <button
                    onClick={() => handleDeactivate(d.id)}
                    title="Remove from the requirements corpus"
                    className="w-8 h-8 rounded-md border border-[#262626] flex items-center justify-center text-[#6e6e67] hover:text-rose-500 hover:border-rose-500/40 transition-colors shrink-0"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
