import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useOutletContext } from 'react-router-dom';
import {
  ChevronRight, Upload, Zap, FileText, CheckCircle2, Clock,
  RotateCcw, Eye, Download, X, AlertCircle,
  Target, Users, Package, Calendar, Wallet, Briefcase, AlertTriangle, HelpCircle,
  BookOpen, ChevronDown, Trash2, Copy, Check, Mail, Sparkles,
} from 'lucide-react';
import { stageMeta, formatId, timeAgo } from '../lib/engagements';
import { useConfig } from '../lib/config.jsx';
import AuthoritativePanel from '../components/AuthoritativePanel';
import MicCaptureButton from '../components/MicCaptureButton';

const API = '/api';

// Stage 2's transcript box only opens once the producer explicitly advances past the
// brief — brief_ready allows more intake transcripts (refining the brief) instead.
const REVIEW_UPLOAD_STATUSES = ['awaiting_review_transcript'];
const APPROVAL_STATUSES = ['proposal_ready', 'in_review'];

// Document previews mirror the PDF export exactly (same accent colors, same
// structured_json fields the backend's WeasyPrint builders read) so "View" in
// the sidebar shows what the downloaded PDF will actually look like.
function ReportSection({ icon: Icon, title, children }) {
  return (
    <div>
      <h3 className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">
        <Icon size={12} />
        {title}
      </h3>
      <div className="text-xs text-zinc-700 leading-relaxed">{children}</div>
    </div>
  );
}

function BulletList({ items, tone = 'default', emptyText = 'None noted' }) {
  if (!items || items.length === 0) return <p className="text-zinc-400 italic text-xs">{emptyText}</p>;
  return (
    <ul className="space-y-1.5">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2">
          <span className={`mt-1.5 w-1 h-1 rounded-full shrink-0 ${tone === 'warn' ? 'bg-amber-500' : 'bg-indigo-400'}`} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function BriefReport({ brief, clientName }) {
  const data = brief.structured_json || {};
  return (
    <div className="bg-white text-zinc-900 rounded-lg overflow-hidden shadow-lg">
      <div className="bg-gradient-to-br from-indigo-600 to-indigo-800 px-6 py-6">
        <p className="text-indigo-200 text-[10px] font-semibold tracking-[0.15em] uppercase mb-1.5">The Exodus · Production Brief</p>
        <div className="flex items-end justify-between gap-3 flex-wrap">
          <h2 className="text-xl font-bold text-white">{clientName}</h2>
          {data.work_type && (
            <span className="inline-block bg-white/15 text-white text-[10px] font-medium px-2.5 py-1 rounded-full capitalize">
              {data.work_type.replace(/-/g, ' ')}
            </span>
          )}
        </div>
      </div>

      <div className="px-6 py-6 space-y-6">
        <ReportSection icon={Target} title="Objectives">
          <BulletList items={data.objectives} />
        </ReportSection>

        <ReportSection icon={Users} title="Audience">
          <p>{data.audience || 'Not specified'}</p>
        </ReportSection>

        <ReportSection icon={Package} title="Deliverables">
          <BulletList items={data.deliverables} />
        </ReportSection>

        <div className="grid grid-cols-2 gap-3">
          <div className="bg-zinc-50 border border-zinc-200 rounded-lg p-3">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">
              <Calendar size={12} className="text-zinc-400" />
              Timeline
            </div>
            <p className="text-xs text-zinc-800">{data.timeline_signals || 'TBD'}</p>
          </div>
          <div className="bg-zinc-50 border border-zinc-200 rounded-lg p-3">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">
              <Wallet size={12} className="text-zinc-400" />
              Budget
            </div>
            <p className="text-xs text-zinc-800">{data.budget_signals || 'TBD'}</p>
          </div>
        </div>

        <ReportSection icon={Briefcase} title="Key Stakeholders">
          {data.key_stakeholders && data.key_stakeholders.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {data.key_stakeholders.map((s, i) => (
                <span key={i} className="text-[11px] font-medium bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full border border-indigo-100">
                  {s}
                </span>
              ))}
            </div>
          ) : <p className="text-zinc-400 italic text-xs">None noted</p>}
        </ReportSection>

        {data.risks && data.risks.length > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-amber-900">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-amber-700 mb-1.5">
              <AlertTriangle size={12} />
              Risks
            </div>
            <BulletList items={data.risks} tone="warn" />
          </div>
        )}

        {data.open_questions && data.open_questions.length > 0 && (
          <ReportSection icon={HelpCircle} title="Open Questions">
            <BulletList items={data.open_questions} />
          </ReportSection>
        )}
      </div>
    </div>
  );
}

function ProposalReport({ proposal, clientName }) {
  const data = proposal.structured_json || {};
  const pricingItems = proposal.pricing_line_items || [];
  const grandTotal = pricingItems.reduce((sum, item) => sum + (item.qty || 1) * (item.rate_kes || 0), 0);

  return (
    <div className="bg-white text-zinc-900 rounded-lg overflow-hidden shadow-lg">
      <div className="bg-gradient-to-br from-emerald-600 to-emerald-800 px-6 py-6">
        <p className="text-emerald-200 text-[10px] font-semibold tracking-[0.15em] uppercase mb-1.5">The Exodus · Client Proposal</p>
        <div className="flex items-end justify-between gap-3 flex-wrap">
          <h2 className="text-xl font-bold text-white">{clientName}</h2>
          {proposal.status === 'approved' && (
            <span className="inline-block bg-white/15 text-white text-[10px] font-medium px-2.5 py-1 rounded-full">Approved</span>
          )}
        </div>
      </div>

      <div className="px-6 py-6 space-y-6">
        <ReportSection icon={Target} title="Approach">
          <p>{data.approach || 'Not specified'}</p>
        </ReportSection>

        <ReportSection icon={Package} title="Scoped Deliverables">
          <BulletList items={data.scoped_deliverables} />
        </ReportSection>

        <ReportSection icon={Calendar} title="Phased Timeline">
          <BulletList items={data.phased_timeline} />
        </ReportSection>

        <ReportSection icon={Users} title="Team Shape">
          {data.team_shape && data.team_shape.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {data.team_shape.map((t, i) => (
                <span key={i} className="text-[11px] font-medium bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-full border border-emerald-100">
                  {t}
                </span>
              ))}
            </div>
          ) : <p className="text-zinc-400 italic text-xs">Not specified</p>}
        </ReportSection>

        {pricingItems.length > 0 && (
          <div>
            <h3 className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">
              <Wallet size={12} />
              Pricing Structure
            </h3>
            <div className="rounded-lg border border-zinc-200 overflow-hidden">
              <table className="w-full text-[10.5px] border-collapse table-fixed tabular-nums">
                <thead>
                  <tr className="bg-zinc-50">
                    <th className="w-[52%] px-2 py-2 text-left font-medium text-zinc-500 border-b border-zinc-200">Item</th>
                    <th className="w-[10%] px-1 py-2 text-center font-medium text-zinc-500 border-b border-zinc-200">Qty</th>
                    <th className="w-[19%] px-1.5 py-2 text-right font-medium text-zinc-500 border-b border-zinc-200">Rate</th>
                    <th className="w-[19%] px-2 py-2 text-right font-medium text-zinc-500 border-b border-zinc-200">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {pricingItems.map((item, i) => (
                    <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-zinc-50/50'}>
                      <td className="px-2 py-2 border-b border-zinc-100">
                        <p className="text-zinc-800 font-medium leading-tight">{item.category}</p>
                        <p className="text-zinc-500 leading-tight">{item.description}</p>
                      </td>
                      <td className="px-1 py-2 border-b border-zinc-100 text-center text-zinc-600 align-top">{item.qty || 1}</td>
                      <td className="px-1.5 py-2 border-b border-zinc-100 text-right text-zinc-700 align-top">{(item.rate_kes || 0).toLocaleString()}</td>
                      <td className="px-2 py-2 border-b border-zinc-100 text-right font-medium text-zinc-900 align-top">{((item.qty || 1) * (item.rate_kes || 0)).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="bg-zinc-50">
                    <td colSpan={3} className="px-2 py-2.5 text-right font-semibold text-zinc-800 border-t-2 border-zinc-800">Total (KES)</td>
                    <td className="px-2 py-2.5 text-right font-bold text-zinc-900 border-t-2 border-zinc-800">{grandTotal.toLocaleString()}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function buildStages(engagement) {
  const status = engagement.status;
  return [
    {
      id: 'brief',
      step: 1,
      title: 'Initial Meeting Brief',
      subtitle: 'Add the first client meeting transcript to generate a Production Brief',
      agent: 'Brief Generator',
      docType: 'Production Brief',
      status: engagement.brief ? 'complete' : status === 'awaiting_transcript' ? 'active' : 'pending',
    },
    {
      id: 'proposal',
      step: 2,
      title: 'Proposal Generation',
      subtitle: 'Add the brief review meeting transcript to generate the Client Proposal',
      agent: 'Proposal Generator',
      docType: 'Client Proposal',
      status: engagement.proposal ? 'complete' : REVIEW_UPLOAD_STATUSES.includes(status) ? 'active' : 'pending',
    },
    {
      id: 'approval',
      step: 3,
      title: 'Account Manager Review',
      subtitle: 'Review the generated proposal and approve, or ask the AI to revise it',
      docType: 'Approval',
      status: ['approved', 'accepted'].includes(status) ? 'complete' : APPROVAL_STATUSES.includes(status) ? 'active' : 'pending',
    },
    {
      id: 'production',
      step: 4,
      title: 'Client Acceptance & Team Assembly',
      subtitle: 'Record the client\'s acceptance — The Exodus assembles the crew, tools, and kickoff plan from the talent pool',
      agent: 'Resource Planner',
      docType: 'Production Plan',
      status: status === 'accepted' ? 'complete' : status === 'approved' ? 'active' : 'pending',
    },
  ];
}

// Recap of what actually happened in a specific meeting — distinct from the
// document (brief/proposal) that meeting produced. Duration/date are only ever
// shown when the agent found them explicitly stated in the transcript; a missing
// meeting_date falls back to the upload timestamp, which is real (not a guess).
function MeetingSummaryCard({ transcript }) {
  if (!transcript) return null;
  const hasContent = transcript.summary || transcript.duration_minutes != null || transcript.meeting_date || (transcript.attendees && transcript.attendees.length > 0);
  if (!hasContent) return null;

  return (
    <div className="mb-3 p-3 rounded-lg bg-[#1a1a1a] border border-[#262626]">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-[#6e6e67] mb-1.5">
        <FileText size={11} />
        Meeting Summary
      </div>
      {transcript.summary && (
        <p className="text-xs text-[#a3a39c] leading-relaxed mb-2">{transcript.summary}</p>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[10px] text-[#6e6e67]">
        <span className="font-mono">{transcript.meeting_date || `Recorded ${timeAgo(transcript.uploaded_at)}`}</span>
        {transcript.duration_minutes != null && <span className="font-mono">{transcript.duration_minutes} min</span>}
        {transcript.attendees && transcript.attendees.length > 0 && (
          <span className="flex flex-wrap gap-1">
            {transcript.attendees.map((a, i) => (
              <span key={i} className="px-1.5 py-0.5 rounded bg-[#242424] text-[#8a8a83]">{a}</span>
            ))}
          </span>
        )}
      </div>
    </div>
  );
}

// Passive completeness badge — checks a generated brief/proposal against agency-
// uploaded requirement documents (the Playbook's "Definition of Done"). Fetches lazily after the
// engagement itself has already loaded, so it never blocks the main page render, and
// polls only while a check is actually in flight. Never blocks any action — purely
// informational.
function CompletenessBadge({ engagementId, docType, refreshKey }) {
  const [result, setResult] = useState(null);
  const pollRef = useRef(null);

  const fetchOnce = useCallback(async (force) => {
    try {
      const url = `${API}/engagements/${engagementId}/${docType}/completeness${force ? '?refresh=1' : ''}`;
      const res = await fetch(url, { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      setResult(data);
      if (data.pending) {
        if (!pollRef.current) {
          pollRef.current = setInterval(async () => {
            const r2 = await fetch(`${API}/engagements/${engagementId}/${docType}/completeness`, { credentials: 'include' });
            if (r2.ok) {
              const d2 = await r2.json();
              setResult(d2);
              if (!d2.pending) {
                clearInterval(pollRef.current);
                pollRef.current = null;
              }
            }
          }, 2000);
        }
      }
    } catch (err) {
      console.error(err);
    }
  }, [engagementId, docType]);

  useEffect(() => {
    fetchOnce(false);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engagementId, docType, refreshKey]);

  if (!result || !result.available) return null;

  if (result.pending) {
    return (
      <div className="flex items-center gap-2 mt-2 text-[10px] text-[#6e6e67]">
        <div className="w-3 h-3 rounded-full border-2 border-[#c9971f]/30 border-t-[#c9971f] animate-spin" />
        Checking against requirements…
      </div>
    );
  }

  if (result.complete === null) {
    return <p className="mt-2 text-[10px] text-[#6e6e67]">Completeness check unavailable.</p>;
  }

  const isComplete = result.complete;
  return (
    <div className={`mt-2 p-2.5 rounded-lg border text-[11px] ${isComplete ? 'bg-[#10b981]/10 border-[#10b981]/20 text-[#10b981]' : 'bg-[#f59e0b]/10 border-[#f59e0b]/20 text-[#b45309]'}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">
          {isComplete ? '✓ Meets known requirements' : `⚠ ${result.missing.length} item${result.missing.length === 1 ? '' : 's'} may be missing`}
          {result.stale && <span className="text-[#6e6e67] font-normal"> · requirements changed since this check</span>}
        </span>
        <button onClick={() => fetchOnce(true)} className="text-[10px] underline decoration-dotted text-[#6e6e67] hover:text-[#a3a39c] shrink-0">
          Recheck
        </button>
      </div>
      {!isComplete && result.missing.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 list-disc list-inside text-[#a16207]">
          {result.missing.map((item, i) => <li key={i}>{item}</li>)}
        </ul>
      )}
    </div>
  );
}

const REF_PURPOSES = [
  { id: 'structure', label: 'Structure / template' },
  { id: 'content', label: 'Content / background' },
];
const REF_PURPOSE_LABEL = Object.fromEntries(REF_PURPOSES.map(p => [p.id, p.label]));

// The "any reference documents?" ask — optional engagement-scoped material (proposal
// templates, client RFPs, brand guidelines) fed into the generation prompts to shape
// structure and enrich content. Auto-expanded while the engagement is waiting on a
// transcript (the moment references still influence the next generation); generation
// runs identically when none are uploaded.
function ReferenceDocumentsCard({ engagementId, status }) {
  const [docs, setDocs] = useState(null);
  const [open, setOpen] = useState(status === 'awaiting_transcript' || REVIEW_UPLOAD_STATUSES.includes(status));
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState('');
  const [purpose, setPurpose] = useState('structure');
  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef(null);

  const fetchDocs = useCallback(async () => {
    try {
      const res = await fetch(`${API}/engagements/${engagementId}/references`, { credentials: 'include' });
      if (res.ok) setDocs(await res.json());
    } catch (err) {
      console.error(err);
    }
  }, [engagementId]);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  const readFile = (file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setText(String(reader.result || ''));
    reader.readAsText(file);
  };

  const handleAdd = async () => {
    if (!title.trim() || !text.trim()) {
      setError('A title and the document text are both required.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const res = await fetch(`${API}/engagements/${engagementId}/references`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), purpose, raw_text: text }),
        credentials: 'include',
      });
      if (res.ok) {
        setTitle('');
        setText('');
        setShowForm(false);
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

  const handleRemove = async (docId) => {
    try {
      const res = await fetch(`${API}/references/${docId}/deactivate`, { method: 'POST', credentials: 'include' });
      if (res.ok) await fetchDocs();
    } catch (err) {
      console.error(err);
    }
  };

  const count = docs?.length ?? 0;

  return (
    <div className="mb-6 rounded-xl" style={{ background: '#141414', border: '1px solid #242424' }}>
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center gap-2 px-5 py-3.5 text-left">
        <BookOpen size={14} className="text-[#8a8a83]" />
        <span className="text-[14px] font-semibold text-[#f2f0e8]">Reference Documents</span>
        <span className="text-[10px] font-mono text-[#6e6e67]">{count > 0 ? `${count} on file` : 'optional'}</span>
        <ChevronDown size={14} className={`ml-auto text-[#6e6e67] transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="px-5 pb-4" style={{ borderTop: '1px solid #242424' }}>
          <p className="text-[11px] text-[#6e6e67] leading-relaxed pt-3 mb-3">
            Have a proposal template, the client's RFP, or brand guidelines? The Exodus uses them to shape structure
            and enrich content when generating documents — add them before generating for best results.
          </p>

          {count > 0 && (
            <div className="flex flex-col mb-3">
              {docs.map(d => (
                <div key={d.id} className="flex items-center gap-3 py-2" style={{ borderBottom: '1px solid #191919' }}>
                  <FileText size={13} className="text-[#6e6e67] shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-[12px] font-medium text-[#d6d4c9] truncate">{d.title}</p>
                    <p className="text-[10px] text-[#5c5c55] font-mono">
                      {REF_PURPOSE_LABEL[d.purpose] || d.purpose} · {d.length.toLocaleString()} chars · {timeAgo(d.uploaded_at)}
                    </p>
                  </div>
                  <button
                    onClick={() => handleRemove(d.id)}
                    title="Remove this reference"
                    className="w-7 h-7 rounded-md border border-[#262626] flex items-center justify-center text-[#6e6e67] hover:text-rose-500 hover:border-rose-500/40 transition-colors shrink-0"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {showForm ? (
            <div className="flex flex-col gap-3 p-3 rounded-lg bg-[#0e0e0e] border border-[#262626]">
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="text"
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  placeholder="Title, e.g. Client RFP"
                  className="w-full bg-[#1a1a1a] border border-[#262626] rounded-lg px-3 py-2 text-xs text-[#f7f5ef] placeholder:text-[#6e6e67] focus:outline-none focus:border-[#c9971f]/60 transition-colors"
                />
                <select
                  value={purpose}
                  onChange={e => setPurpose(e.target.value)}
                  className="w-full bg-[#1a1a1a] border border-[#262626] rounded-lg px-3 py-2 text-xs text-[#f7f5ef] focus:outline-none focus:border-[#c9971f]/60 transition-colors"
                >
                  {REF_PURPOSES.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
              </div>
              <div
                onClick={() => fileInputRef.current?.click()}
                onDragOver={e => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={e => { e.preventDefault(); setDragging(false); readFile(e.dataTransfer.files?.[0]); }}
                className={`border-2 border-dashed rounded-lg p-3 text-center transition-all cursor-pointer ${
                  dragging ? 'border-[#c9971f]/60 bg-[#c9971f]/10' : 'border-[#262626] hover:border-[#333333]'
                }`}
              >
                <p className="text-[11px] text-[#a3a39c]">Drop a .txt/.md file here, or <span className="text-[#c9971f]">browse</span></p>
                <input ref={fileInputRef} type="file" accept=".txt,.md,text/plain,text/markdown" className="hidden" onChange={e => readFile(e.target.files?.[0])} />
              </div>
              <textarea
                rows={4}
                value={text}
                onChange={e => setText(e.target.value)}
                placeholder="Or paste the document text here…"
                className="w-full bg-[#1a1a1a] border border-[#262626] rounded-lg px-3 py-2 text-xs text-[#f7f5ef] placeholder:text-[#6e6e67] focus:outline-none focus:border-[#c9971f]/50 resize-none font-mono"
              />
              {error && <p role="alert" className="text-xs text-rose-500">{error}</p>}
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => { setShowForm(false); setError(''); }}
                  className="px-3 py-1.5 rounded-lg border border-[#262626] text-xs text-[#a3a39c] hover:border-[#333333] hover:text-[#f7f5ef] transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleAdd}
                  disabled={saving}
                  className="px-4 py-1.5 rounded-lg bg-[#c9971f] hover:bg-[#a67a17] text-white text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-wait"
                >
                  {saving ? 'Adding…' : 'Add Document'}
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setShowForm(true)}
              className="w-full py-2 rounded-lg border border-dashed border-[#262626] text-xs text-[#a3a39c] hover:border-[#c9971f]/40 hover:text-[#e8c34a] transition-colors"
            >
              + Add Reference Document
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function TranscriptDropArea({ stage, transcript, setTranscript, busy, onGenerate, error, engagementId }) {
  const { flags } = useConfig();
  const [dragging, setDragging] = useState(false);
  const [dictationError, setDictationError] = useState('');
  const fileInputRef = useRef(null);

  const readFile = useCallback((file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setTranscript(String(reader.result || ''));
    reader.readAsText(file);
  }, [setTranscript]);

  if (busy) {
    return (
      <div className="flex items-center gap-3 p-4 rounded-lg bg-[#c9971f]/10 border border-[#c9971f]/20">
        <div className="w-6 h-6 rounded-full border-2 border-[#c9971f]/30 border-t-[#c9971f] animate-spin" />
        <div>
          <p className="text-xs font-medium text-[#e8c34a]">{stage.agent} is processing…</p>
          <p className="text-[10px] text-[#6e6e67]">Parsing transcript · Building structure · Cross-referencing rate card</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        onClick={() => fileInputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); readFile(e.dataTransfer.files?.[0]); }}
        className={`border-2 border-dashed rounded-lg p-6 text-center transition-all cursor-pointer ${
          dragging ? 'border-[#c9971f]/60 bg-[#c9971f]/10' : 'border-[#262626] hover:border-[#333333]'
        }`}
      >
        <Upload size={20} className="mx-auto text-[#6e6e67] mb-2" />
        <p className="text-xs text-[#a3a39c] mb-1">Drop transcript here, or <span className="text-[#c9971f]">browse</span></p>
        <p className="text-[10px] text-[#6e6e67]">.txt · .md accepted</p>
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.md,text/plain,text/markdown"
          className="hidden"
          onChange={e => readFile(e.target.files?.[0])}
        />
      </div>
      <div className="flex items-center gap-2">
        <div className="flex-1 h-px bg-[#262626]" />
        <span className="text-[10px] text-[#6e6e67]">or dictate / paste directly</span>
        <div className="flex-1 h-px bg-[#262626]" />
      </div>
      {flags.voice && (
        <MicCaptureButton
          engagementId={engagementId}
          // Same setter the drop and paste paths use — dictation is just another
          // way of filling this textarea.
          onText={text => setTranscript(prev => (prev ? `${prev} ` : '') + text)}
          onError={setDictationError}
        />
      )}
      {dictationError && <p role="alert" className="text-xs text-amber-500">{dictationError}</p>}
      <textarea
        rows={4}
        value={transcript}
        onChange={e => setTranscript(e.target.value)}
        placeholder="Paste raw meeting transcript here…"
        className="w-full bg-[#1a1a1a] border border-[#262626] rounded-lg px-3 py-2.5 text-xs text-[#f7f5ef] placeholder:text-[#6e6e67] focus:outline-none focus:border-[#c9971f]/50 resize-none font-mono"
      />
      {error && <p role="alert" className="text-xs text-rose-600">{error}</p>}
      <button
        onClick={onGenerate}
        disabled={!transcript.trim()}
        className="flex items-center justify-center gap-2 w-full py-2.5 rounded-lg bg-[#c9971f] hover:bg-[#a67a17] text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <Zap size={14} />
        Generate {stage.docType}
      </button>
    </div>
  );
}

// Producer-facing affordance for WP-8's zero-click path: pasting this tag into a
// calendar invite title makes the Fathom transcript attach to *this* engagement,
// which also disambiguates a client that has several open engagements.
function EngTagHint({ tag }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(tag);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error(err);
    }
  }

  return (
    <div className="flex items-center gap-2 mt-2.5 flex-wrap">
      <code className="text-[11px] font-mono text-[#e8c34a] bg-[#c9971f]/10 border border-[#c9971f]/25 px-2 py-1 rounded">
        {tag}
      </code>
      <button
        onClick={copy}
        aria-label={`Copy ${tag} to clipboard`}
        className="flex items-center gap-1 text-[11px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors"
      >
        {copied ? <Check size={11} /> : <Copy size={11} />}
        {copied ? 'Copied' : 'Copy'}
      </button>
      <span aria-live="polite" className="sr-only">{copied ? 'Copied to clipboard' : ''}</span>
      <span className="text-[11px] text-[#6e6e67]">
        Paste this into the calendar invite title and the transcript attaches itself.
      </span>
    </div>
  );
}


// WP-12: the same approval gate as the PDF download, plus the one thing the
// backend cannot supply — a human confirming the address before it leaves.
function SendProposalModal({ engagement, onClose, onSent }) {
  const [to, setTo] = useState(engagement.client_contact_email || '');
  const [contactName, setContactName] = useState(engagement.client_contact_name || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  async function send() {
    if (!to.trim()) { setError('Enter the client contact email.'); return; }
    setBusy(true); setError('');
    try {
      const res = await fetch(`${API}/engagements/${engagement.id}/proposal/send-email`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to: to.trim(), contact_name: contactName.trim() || null }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setError(data.error || 'Could not send the proposal.'); return; }
      setResult(data);
      setTimeout(onSent, 1800);
    } catch {
      setError('Connection failed.');
    } finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4" onClick={onClose}>
      <div role="dialog" aria-label="Send proposal by email" onClick={e => e.stopPropagation()}
        className="w-full max-w-md rounded-xl overflow-hidden"
        style={{ background: '#141414', border: '1px solid #242424' }}>
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
          <span className="text-[14px] font-semibold text-[#f2f0e8]">Send proposal</span>
          <button onClick={onClose} aria-label="Close" className="text-[#8a8a83] hover:text-[#f7f5ef]">
            <X size={16} />
          </button>
        </div>
        <div className="px-5 py-4 flex flex-col gap-3">
          {result ? (
            <p className="text-[13px] text-[#10b981]" aria-live="polite">
              Sent to {result.to} via {result.driver_label}. {result.detail}
            </p>
          ) : (
            <>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="em-to" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">TO</label>
                <input id="em-to" type="email" value={to} onChange={e => setTo(e.target.value)}
                  className="rounded-lg px-3 py-2 text-[12px] text-[#d6d4c9] bg-[#0e0e0e]"
                  style={{ border: '1px solid #262626' }} />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="em-name" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">
                  CONTACT NAME (OPTIONAL)
                </label>
                <input id="em-name" value={contactName} onChange={e => setContactName(e.target.value)}
                  className="rounded-lg px-3 py-2 text-[12px] text-[#d6d4c9] bg-[#0e0e0e]"
                  style={{ border: '1px solid #262626' }} />
              </div>
              <p className="text-[11px] text-[#8a8a83]">
                The approved proposal PDF is attached automatically.
              </p>
              {error && <p role="alert" className="text-xs text-rose-500">{error}</p>}
              <button onClick={send} disabled={busy}
                className="self-start flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-white text-[13px] font-medium hover:opacity-90 disabled:opacity-50"
                style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}>
                <Mail size={13} /> {busy ? 'Sending…' : 'Send'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function EngagementDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useOutletContext();
  const { flags } = useConfig();
  const isAccountManager = user?.role === 'Account Manager';
  const canEditAuthData = user?.role === 'Account Manager' || user?.role === 'Admin';

  const [engagement, setEngagement] = useState(null);
  const [showEmail, setShowEmail] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [generatingStage, setGeneratingStage] = useState(null); // 'brief' | 'proposal' | null
  const [generateError, setGenerateError] = useState('');

  const [activeDoc, setActiveDoc] = useState(null); // 'brief' | 'proposal'
  const [showDoc, setShowDoc] = useState(true);
  const [isDownloading, setIsDownloading] = useState(null);

  const [amNote, setAmNote] = useState('');
  const [isReviewing, setIsReviewing] = useState(false); // approve or revise in flight
  const [isRevising, setIsRevising] = useState(false);
  const [reviewError, setReviewError] = useState('');
  const [revisionMessage, setRevisionMessage] = useState('');

  const [showRefineBox, setShowRefineBox] = useState(false);
  const [isAdvancing, setIsAdvancing] = useState(false);
  const [advanceError, setAdvanceError] = useState('');
  const [isStartingNextRound, setIsStartingNextRound] = useState(false);

  const [isAccepting, setIsAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState('');
  const canAccept = ['Account Manager', 'Admin'].includes(user?.role);

  const pollRef = useRef(null);

  const fetchEngagement = useCallback(async () => {
    try {
      const res = await fetch(`${API}/engagements/${id}`, { credentials: 'include' });
      const data = await res.json();
      setEngagement(data);
      // Default the document panel to the furthest artifact along the pipeline.
      setActiveDoc(prev => prev ?? (data.proposal ? 'proposal' : data.brief ? 'brief' : null));
      return data;
    } catch (err) {
      console.error(err);
      return null;
    }
  }, [id]);

  // Agent calls now run in a background thread on the backend — the upload/review
  // POSTs return almost immediately (202 processing), so completion is detected by
  // polling the engagement until `is_processing` clears, rather than awaiting the
  // original request.
  const pollUntilDone = useCallback((onDone) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      const data = await fetchEngagement();
      if (data && !data.is_processing) {
        clearInterval(pollRef.current);
        pollRef.current = null;
        onDone(data);
      }
    }, 2000);
  }, [fetchEngagement]);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // If the page loads (or reloads) mid-processing — e.g. the producer refreshed
  // during a long agent call — resume the busy UI and polling instead of showing
  // a stale idle state.
  useEffect(() => {
    fetchEngagement().then(data => {
      if (!data?.is_processing) return;
      const stageId = data.status === 'awaiting_transcript' ? 'brief'
        : (data.status === 'brief_ready' || data.status === 'awaiting_review_transcript') ? 'proposal'
        : 'approval';
      if (stageId === 'approval') {
        setIsReviewing(true);
        setIsRevising(true);
      } else {
        setGeneratingStage(stageId);
      }
      pollUntilDone(finalData => {
        setGeneratingStage(null);
        setIsReviewing(false);
        setIsRevising(false);
        if (finalData.processing_error) {
          if (stageId === 'approval') setReviewError(finalData.processing_error);
          else setGenerateError(finalData.processing_error);
        }
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const handleGenerate = async (stageId) => {
    if (!transcript.trim()) return;
    setGeneratingStage(stageId);
    setGenerateError('');
    try {
      // One endpoint for both stages; the backend dispatches on engagement.status.
      const res = await fetch(`${API}/engagements/${id}/transcripts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_text: transcript }),
        credentials: 'include',
      });
      if (res.status === 202) {
        setTranscript('');
        setActiveDoc(stageId);
        setShowDoc(true);
        pollUntilDone(data => {
          setGeneratingStage(null);
          if (data.processing_error) setGenerateError(data.processing_error);
          else if (stageId === 'brief') setShowRefineBox(false);
        });
        return;
      }
      const err = await res.json().catch(() => ({}));
      setGenerateError(err.error || 'Generation failed. Please try again.');
    } catch (err) {
      console.error(err);
      setGenerateError('Connection failed. Is the backend running?');
    }
    setGeneratingStage(null);
  };

  const handleAdvanceToProposal = async () => {
    setIsAdvancing(true);
    setAdvanceError('');
    try {
      const res = await fetch(`${API}/engagements/${id}/advance`, {
        method: 'POST',
        credentials: 'include',
      });
      if (res.ok) {
        await fetchEngagement();
      } else {
        const err = await res.json().catch(() => ({}));
        setAdvanceError(err.error || 'Could not advance to the proposal stage.');
      }
    } catch (err) {
      console.error(err);
      setAdvanceError('Connection failed. Is the backend running?');
    }
    setIsAdvancing(false);
  };

  const handleStartNextRound = async () => {
    setIsStartingNextRound(true);
    try {
      const res = await fetch(`${API}/engagements`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: engagement.client_id }),
        credentials: 'include',
      });
      if (res.ok) {
        const next = await res.json();
        navigate(`/engagements/${next.id}`);
        return;
      }
    } catch (err) {
      console.error(err);
    }
    setIsStartingNextRound(false);
  };

  const handleApprove = async () => {
    setIsReviewing(true);
    setReviewError('');
    try {
      const res = await fetch(`${API}/engagements/${id}/proposals/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'approve', notes: amNote.trim() }),
        credentials: 'include',
      });
      if (res.ok) {
        setAmNote('');
        setRevisionMessage('');
        await fetchEngagement();
      } else {
        const err = await res.json().catch(() => ({}));
        setReviewError(err.error || 'Approval failed.');
      }
    } catch (err) {
      console.error(err);
      setReviewError('Connection failed. Is the backend running?');
    }
    setIsReviewing(false);
  };

  const handleRequestChanges = async () => {
    const request = amNote.trim();
    if (!request) {
      setReviewError('Add the changes you would like the AI to make before sending this request.');
      return;
    }
    setIsReviewing(true);
    setIsRevising(true);
    setReviewError('');
    try {
      const res = await fetch(`${API}/engagements/${id}/proposals/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'send_back', notes: request }),
        credentials: 'include',
      });
      if (res.status === 202) {
        setActiveDoc('proposal');
        setShowDoc(true);
        pollUntilDone(data => {
          setIsReviewing(false);
          setIsRevising(false);
          if (data.processing_error) {
            setReviewError(data.processing_error);
          } else {
            setRevisionMessage(`AI revision applied: ${request}`);
            setAmNote('');
          }
        });
        return;
      }
      const err = await res.json().catch(() => ({}));
      setReviewError(err.error || 'Revision failed.');
    } catch (err) {
      console.error(err);
      setReviewError('Connection failed. Is the backend running?');
    }
    setIsReviewing(false);
    setIsRevising(false);
  };

  // Part 2 mock: recording the client's acceptance triggers the Resource Planner,
  // which matches the proposal's team shape against the seeded talent pool — a
  // deterministic DB match, not an LLM call, so it lands instantly.
  const handleAccept = async () => {
    setIsAccepting(true);
    setAcceptError('');
    try {
      const res = await fetch(`${API}/engagements/${id}/accept`, {
        method: 'POST',
        credentials: 'include',
      });
      if (res.ok) {
        navigate(`/engagements/${id}/production`);
        return;
      }
      const err = await res.json().catch(() => ({}));
      setAcceptError(err.error || 'Could not record the acceptance.');
    } catch (err) {
      console.error(err);
      setAcceptError('Connection failed. Is the backend running?');
    }
    setIsAccepting(false);
  };

  const proposalApproved = engagement?.proposal?.status === 'approved';

  const downloadPDF = async (doc) => {
    if (doc === 'proposal' && !proposalApproved) return;
    setIsDownloading(doc);
    try {
      const endpoint = doc === 'brief' ? 'brief/pdf' : 'proposal/pdf';
      const res = await fetch(`${API}/engagements/${id}/${endpoint}`, { credentials: 'include' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.error || 'Download failed');
        setIsDownloading(null);
        return;
      }
      const disposition = res.headers.get('Content-Disposition');
      let filename = `${engagement.client_name}_${doc === 'brief' ? 'Production_Brief' : 'Client_Proposal'}.pdf`;
      if (disposition) {
        const match = disposition.match(/filename="?([^"]+)"?/);
        if (match) filename = match[1];
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('PDF download failed:', err);
      alert('Could not download PDF. Please try again.');
    }
    setIsDownloading(null);
  };

  if (!engagement) {
    return <div className="px-8 py-7 text-sm text-[#8a8a83]">Loading…</div>;
  }

  const stages = buildStages(engagement);
  const meta = stageMeta(engagement.status);
  const STAGE_TRANSCRIPT_KIND = { brief: 'client_meeting', proposal: 'brief_review_meeting' };
  const transcriptsForStage = stageId =>
    (engagement.transcripts || []).filter(t => t.kind === STAGE_TRANSCRIPT_KIND[stageId]);
  const hasAnyDoc = Boolean(engagement.brief || engagement.proposal);
  const events = engagement.events || [];
  const carryForward = engagement.carry_forward || [];

  return (
    <div className="flex h-full">
      {/* Left: pipeline */}
      <div className="flex-1 min-w-0 overflow-y-auto px-8 py-7">
        {/* Breadcrumb */}
        <div className="flex items-center gap-1.5 text-xs text-[#6e6e67] mb-6">
          <button onClick={() => navigate('/dashboard')} className="hover:text-[#a3a39c] transition-colors">Dashboard</button>
          <ChevronRight size={12} />
          <button onClick={() => navigate('/engagements')} className="hover:text-[#a3a39c] transition-colors">Engagements</button>
          <ChevronRight size={12} />
          <span className="text-[#f7f5ef]">{engagement.client_name}</span>
        </div>

        {/* Hero header — company details */}
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-mono text-[#6e6e67] bg-[#1a1a1a] border border-[#262626] px-2 py-0.5 rounded">{formatId(engagement.id)}</span>
            <span className="text-xs font-mono px-2 py-0.5 rounded" style={{ color: meta.color, background: meta.bg, border: `1px solid ${meta.color}30` }}>
              {meta.label}
            </span>
          </div>
          <h1 className="font-serif text-[#f7f5ef] text-2xl mb-1">
            <button onClick={() => navigate(`/clients/${engagement.client_id}`)} className="hover:text-[#e8c34a] transition-colors text-left">
              {engagement.client_name}
            </button>
          </h1>
          <p className="text-sm text-[#a3a39c]">
            {engagement.client_industry ? `${engagement.client_industry} · ` : ''}Engagement {formatId(engagement.id)}
          </p>
          {engagement.client_notes && (
            <p className="text-xs text-[#6e6e67] mt-1 max-w-xl">{engagement.client_notes}</p>
          )}
          {engagement.eng_tag && <EngTagHint tag={engagement.eng_tag} />}
          {flags.talent && (
            <button
              onClick={() => navigate(`/engagements/${engagement.id}/casting`)}
              className="mt-2.5 flex items-center gap-1.5 text-[12px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors"
            >
              <Sparkles size={12} /> Casting &amp; crew
            </button>
          )}
        </div>

        <ReferenceDocumentsCard engagementId={engagement.id} status={engagement.status} />

        {/* Pipeline */}
        <div className="flex flex-col gap-4">
          {stages.map((stage, i) => (
            <div key={stage.id} className="relative">
              {/* Connector line */}
              {i < stages.length - 1 && (
                <div className={`absolute left-5 top-full w-px h-4 z-10 ${stage.status === 'complete' ? 'bg-[#10b981]/40' : 'bg-[#262626]'}`} />
              )}

              <div
                className={`rounded-xl border transition-all ${
                  stage.status === 'active'
                    ? 'border-[#c9971f]/40 bg-[#141414]'
                    : stage.status === 'complete'
                    ? 'border-[#10b981]/20 bg-[#141414]'
                    : 'border-[#262626] bg-[#0e0e0e] opacity-60'
                }`}
              >
                {/* Stage header */}
                <div className="flex items-center gap-3 px-5 py-4">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                    stage.status === 'complete' ? 'bg-[#10b981]/15' : stage.status === 'active' ? 'bg-[#c9971f]/15' : 'bg-[#1a1a1a]'
                  }`}>
                    {stage.status === 'complete'
                      ? <CheckCircle2 size={15} className="text-[#10b981]" />
                      : stage.status === 'active'
                      ? <Zap size={15} className="text-[#c9971f]" />
                      : <Clock size={15} className="text-[#6e6e67]" />
                    }
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-[10px] font-mono text-[#6e6e67]">STEP {stage.step}</span>
                      {stage.agent && (
                        <span className="text-[10px] font-mono text-[#c9971f] bg-[#c9971f]/10 px-1.5 py-0.5 rounded">
                          {stage.agent}
                        </span>
                      )}
                    </div>
                    <p className="text-sm font-semibold text-[#f7f5ef]">{stage.title}</p>
                    <p className="text-xs text-[#a3a39c] mt-0.5">{stage.subtitle}</p>
                  </div>
                  <div className="shrink-0">
                    {stage.status === 'complete' && (
                      <span className="text-xs text-[#10b981] font-mono">Complete</span>
                    )}
                    {stage.status === 'pending' && (
                      <span className="text-xs text-[#6e6e67] font-mono">Waiting</span>
                    )}
                  </div>
                </div>

                {/* Stage body — brief & proposal steps */}
                {stage.status !== 'pending' && stage.id !== 'approval' && stage.id !== 'production' && (
                  <div className="px-5 pb-5 border-t border-[#262626] pt-4">
                    {stage.status === 'complete' ? (
                      <div>
                        {transcriptsForStage(stage.id).map(t => (
                          <MeetingSummaryCard key={t.id} transcript={t} />
                        ))}
                        <div className="flex items-center gap-3">
                          <div className="flex-1 flex items-center gap-3 p-3 rounded-lg bg-[#1a1a1a] border border-[#262626]">
                            <div className="w-8 h-8 rounded-md bg-[#10b981]/10 border border-[#10b981]/20 flex items-center justify-center">
                              <FileText size={14} className="text-[#10b981]" />
                            </div>
                            <div>
                              <p className="text-xs font-medium text-[#f7f5ef]">{stage.docType}</p>
                              <p className="text-[10px] text-[#6e6e67] font-mono">Generated by {stage.agent}</p>
                            </div>
                          </div>
                          <button
                            onClick={() => { setShowDoc(true); setActiveDoc(stage.id); }}
                            className="flex items-center gap-1.5 px-3 py-2 text-xs text-[#e8c34a] border border-[#c9971f]/30 rounded-lg hover:bg-[#c9971f]/10 transition-colors"
                          >
                            <Eye size={13} />
                            View
                          </button>
                          <button
                            onClick={() => downloadPDF(stage.id)}
                            disabled={(stage.id === 'proposal' && !proposalApproved) || isDownloading === stage.id}
                            title={stage.id === 'proposal' && !proposalApproved ? 'Approve the proposal before downloading' : 'Download PDF'}
                            className="flex items-center gap-1.5 px-3 py-2 text-xs text-[#a3a39c] border border-[#262626] rounded-lg hover:border-[#333333] transition-colors disabled:cursor-not-allowed disabled:opacity-45"
                          >
                            <Download size={13} />
                            {isDownloading === stage.id ? 'Preparing…' : 'Download'}
                          </button>
                          {/* Same approval gate as the PDF download — deliberately
                              not a new rule. */}
                          {stage.id === 'proposal' && flags.email && isAccountManager && (
                            <button
                              onClick={() => setShowEmail(true)}
                              disabled={!proposalApproved}
                              title={proposalApproved ? 'Email this proposal to the client' : 'Approve the proposal before emailing'}
                              className="flex items-center gap-1.5 px-3 py-2 text-xs text-[#a3a39c] border border-[#262626] rounded-lg hover:border-[#333333] transition-colors disabled:cursor-not-allowed disabled:opacity-45"
                            >
                              <Mail size={13} />
                              Send
                            </button>
                          )}
                        </div>

                        <CompletenessBadge engagementId={engagement.id} docType={stage.id} refreshKey={stage.id === 'brief' ? engagement.brief?.id : engagement.proposal?.id} />

                        {/* A brief stays refinable — more than one intake meeting is
                            common — until the producer explicitly moves on. */}
                        {stage.id === 'brief' && engagement.status === 'brief_ready' && (
                          <div className="mt-3 pt-3 border-t border-[#262626]">
                            {showRefineBox ? (
                              <TranscriptDropArea
                                stage={{ ...stage, agent: 'Brief Generator', docType: 'Production Brief' }}
                                transcript={transcript}
                                setTranscript={setTranscript}
                                busy={generatingStage === 'brief'}
                                onGenerate={() => handleGenerate('brief')}
                                error={generateError}
                                engagementId={engagement.id}
                              />
                            ) : (
                              <div className="flex gap-2">
                                <button
                                  onClick={() => setShowRefineBox(true)}
                                  className="flex-1 py-2 rounded-lg border border-[#262626] text-xs text-[#a3a39c] hover:border-[#333333] hover:text-[#f7f5ef] transition-colors"
                                >
                                  + Add Another Meeting
                                </button>
                                <button
                                  onClick={handleAdvanceToProposal}
                                  disabled={isAdvancing}
                                  className="flex-1 py-2 rounded-lg bg-[#c9971f] hover:bg-[#a67a17] text-white text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-wait"
                                >
                                  {isAdvancing ? 'Advancing…' : 'Move to Proposal Stage →'}
                                </button>
                              </div>
                            )}
                            {advanceError && <p role="alert" className="mt-1.5 text-xs text-rose-600">{advanceError}</p>}
                          </div>
                        )}
                      </div>
                    ) : (
                      <TranscriptDropArea
                        stage={stage}
                        transcript={transcript}
                        setTranscript={setTranscript}
                        busy={generatingStage === stage.id}
                        onGenerate={() => handleGenerate(stage.id)}
                        error={generateError}
                        engagementId={engagement.id}
                      />
                    )}
                  </div>
                )}

                {/* Approval stage body */}
                {stage.id === 'approval' && stage.status !== 'pending' && (
                  <div className="px-5 pb-5 border-t border-[#262626] pt-4">
                    {stage.status === 'complete' ? (
                      <div className="flex flex-col gap-3">
                        <div className="flex items-center gap-3 p-4 rounded-lg bg-[#10b981]/10 border border-[#10b981]/20">
                          <CheckCircle2 size={18} className="text-[#10b981] shrink-0" />
                          <div>
                            <p className="text-sm font-medium text-[#10b981]">Proposal Approved</p>
                            <p className="text-xs text-[#6e6e67]">Ready to send to the client — download the PDF from the proposal panel.</p>
                          </div>
                        </div>
                        <button
                          onClick={handleStartNextRound}
                          disabled={isStartingNextRound}
                          className="flex items-center justify-center gap-1.5 py-2.5 rounded-lg border border-[#c9971f]/40 text-[#a16207] hover:bg-[#c9971f]/10 text-sm font-medium transition-colors disabled:cursor-wait disabled:opacity-60"
                        >
                          <Zap size={13} />
                          {isStartingNextRound ? 'Starting…' : `Start Next Round for ${engagement.client_name}`}
                        </button>
                      </div>
                    ) : !isAccountManager ? (
                      <div className="flex items-start gap-3 p-3 rounded-lg bg-[#f59e0b]/10 border border-[#f59e0b]/20">
                        <AlertCircle size={14} className="text-[#b45309] shrink-0 mt-0.5" />
                        <p className="text-xs text-[#b45309]">The proposal is with the Account Manager for review. You will see the outcome here.</p>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-3">
                        <div className="flex items-start gap-3 p-3 rounded-lg bg-[#f59e0b]/10 border border-[#f59e0b]/20">
                          <AlertCircle size={14} className="text-[#b45309] shrink-0 mt-0.5" />
                          <p className="text-xs text-[#b45309]">Review the generated proposal before approving. Ensure pricing and deliverables match client expectations.</p>
                        </div>
                        <div>
                          <label htmlFor="proposal-revision" className="block text-xs font-medium text-[#d6d4c9] mb-1.5">Changes for the AI <span className="text-[#6e6e67] font-normal">(optional if approving)</span></label>
                          <textarea
                            id="proposal-revision"
                            value={amNote}
                            onChange={e => { setAmNote(e.target.value); setReviewError(''); }}
                            rows={3}
                            placeholder="e.g. Revise the radio scope to two stations and update the related pricing."
                            className="w-full bg-[#1a1a1a] border border-[#262626] rounded-lg px-3 py-2.5 text-xs text-[#f7f5ef] placeholder:text-[#6e6e67] focus:outline-none focus:border-[#c9971f]/50 resize-none"
                          />
                          {reviewError && <p role="alert" className="mt-1.5 text-xs text-rose-600">{reviewError}</p>}
                          {revisionMessage && <p className="mt-1.5 text-xs text-[#10b981]">{revisionMessage}</p>}
                        </div>
                        <div className="flex gap-2">
                          <button
                            onClick={handleApprove}
                            disabled={isReviewing}
                            className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-lg bg-[#10b981] hover:bg-[#059669] text-white text-sm font-medium transition-colors disabled:cursor-wait disabled:opacity-60"
                          >
                            <CheckCircle2 size={14} />
                            Approve Proposal
                          </button>
                          <button
                            onClick={handleRequestChanges}
                            disabled={isReviewing}
                            className="flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg border border-[#c9971f]/40 text-[#a16207] hover:bg-[#c9971f]/10 text-sm font-medium transition-colors disabled:cursor-wait disabled:opacity-60"
                          >
                            {isRevising ? <Zap size={13} className="animate-pulse" /> : <RotateCcw size={13} />}
                            {isRevising ? 'AI Revising…' : 'Ask AI to Revise'}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Production kickoff stage body (Part 2) */}
                {stage.id === 'production' && stage.status !== 'pending' && (
                  <div className="px-5 pb-5 border-t border-[#262626] pt-4">
                    {stage.status === 'complete' ? (
                      <div className="flex items-center gap-3">
                        <div className="flex-1 flex items-center gap-3 p-4 rounded-lg bg-[#7c3aed]/10 border border-[#7c3aed]/20">
                          <CheckCircle2 size={18} className="text-[#a78bfa] shrink-0" />
                          <div>
                            <p className="text-sm font-medium text-[#a78bfa]">Client Accepted — Crew Assembled</p>
                            <p className="text-xs text-[#6e6e67]">The Resource Planner matched the proposal's team shape against the talent pool.</p>
                          </div>
                        </div>
                        <button
                          onClick={() => navigate(`/engagements/${id}/production`)}
                          className="flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium text-[#a78bfa] border border-[#7c3aed]/40 rounded-lg hover:bg-[#7c3aed]/10 transition-colors shrink-0"
                        >
                          <Users size={13} />
                          View Production Plan →
                        </button>
                      </div>
                    ) : !canAccept ? (
                      <div className="flex items-start gap-3 p-3 rounded-lg bg-[#7c3aed]/10 border border-[#7c3aed]/20">
                        <AlertCircle size={14} className="text-[#a78bfa] shrink-0 mt-0.5" />
                        <p className="text-xs text-[#a78bfa]">Waiting on the client's decision. Once they accept, the Account Manager records it here and The Exodus assembles the production team.</p>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-3">
                        <div className="flex items-start gap-3 p-3 rounded-lg bg-[#7c3aed]/10 border border-[#7c3aed]/20">
                          <AlertCircle size={14} className="text-[#a78bfa] shrink-0 mt-0.5" />
                          <p className="text-xs text-[#a78bfa]">
                            Proposal sent — when the client confirms, mark it accepted. The Exodus will match the
                            proposed team shape against the talent pool and pull together tools and a kickoff plan.
                          </p>
                        </div>
                        {acceptError && <p role="alert" className="text-xs text-rose-600">{acceptError}</p>}
                        <button
                          onClick={handleAccept}
                          disabled={isAccepting}
                          className="flex items-center justify-center gap-2 w-full py-2.5 rounded-lg bg-[#7c3aed] hover:bg-[#6d28d9] text-white text-sm font-medium transition-colors disabled:cursor-wait disabled:opacity-60"
                        >
                          <Users size={14} />
                          {isAccepting ? 'Assembling Team…' : 'Mark as Client-Accepted & Assemble Team'}
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Carry into next meeting — open items pulled forward from the brief, the
            proposal, and the review-meeting signal extraction, deduped, so nothing
            gets lost between stages. */}
        {carryForward.length > 0 && (
          <div className="mt-8 rounded-xl" style={{ background: '#141414', border: '1px solid #242424' }}>
            <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
              <HelpCircle size={14} className="text-[#8a8a83]" />
              <span className="text-[14px] font-semibold text-[#f2f0e8]">Carry Into Next Meeting</span>
            </div>
            <div className="px-5 py-3 flex flex-col">
              {carryForward.map((item, i) => (
                <div key={i} className="flex gap-3 py-3" style={i < carryForward.length - 1 ? { borderBottom: '1px solid #191919' } : {}}>
                  <div className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 bg-[#f59e0b]" />
                  <div className="min-w-0">
                    <p className="text-[12px] text-[#d6d4c9]">{item.text}</p>
                    <p className="text-[10px] text-[#5c5c55] font-mono mt-0.5">{item.source}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Activity log */}
        {events.length > 0 && (
          <div className="mt-8 rounded-xl" style={{ background: '#141414', border: '1px solid #242424' }}>
            <div className="flex items-center gap-2 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
              <Clock size={14} className="text-[#8a8a83]" />
              <span className="text-[14px] font-semibold text-[#f2f0e8]">Activity Log</span>
            </div>
            <div className="px-5 py-3 flex flex-col">
              {events.map((ev, i) => (
                <div key={i} className="flex gap-3 py-3" style={i < events.length - 1 ? { borderBottom: '1px solid #191919' } : {}}>
                  <div className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 bg-[#c9971f]" />
                  <div className="min-w-0">
                    <div className="flex items-baseline gap-2">
                      <p className="text-[12px] font-medium text-[#a16207]">{ev.agent}</p>
                      <p className="text-[10px] text-[#5c5c55]">{timeAgo(ev.created_at)}</p>
                    </div>
                    <p className="text-[11px] text-[#8a8a83] mt-0.5">{ev.reasoning_summary}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {flags.auth_data && (
          <div className="mt-8">
            <AuthoritativePanel
              title="Authoritative Data for This Engagement"
              keys={['brand_voice', 'email_cover_note']}
              engagementId={engagement.id}
              editScopeType="client"
              editScopeId={engagement.client_id}
              canEdit={canEditAuthData}
            />
          </div>
        )}
      </div>

      {showEmail && (
        <SendProposalModal
          engagement={engagement}
          onClose={() => setShowEmail(false)}
          onSent={() => { setShowEmail(false); fetchEngagement(); }}
        />
      )}

      {/* Right: document preview — half the screen, since this is the PDF stand-in */}
      {hasAnyDoc && showDoc && (
        <div className="w-1/2 shrink-0 border-l border-[#262626] flex flex-col bg-[#0e0e0e] overflow-hidden">
          {/* Doc viewer header */}
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-[#262626]">
            <div className="flex gap-1">
              {['brief', 'proposal'].map(d => {
                const available = d === 'brief' ? Boolean(engagement.brief) : Boolean(engagement.proposal);
                return (
                  <button
                    key={d}
                    onClick={() => setActiveDoc(d)}
                    disabled={!available}
                    className={`px-3 py-1.5 rounded text-xs font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
                      activeDoc === d
                        ? 'bg-[#c9971f]/15 text-[#e8c34a]'
                        : 'text-[#a3a39c] hover:text-[#f7f5ef]'
                    }`}
                  >
                    {d === 'brief' ? 'Production Brief' : 'Client Proposal'}
                  </button>
                );
              })}
            </div>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => downloadPDF(activeDoc)}
                disabled={(activeDoc === 'proposal' && !proposalApproved) || isDownloading === activeDoc}
                title={activeDoc === 'proposal' && !proposalApproved ? 'Approve the proposal before downloading' : 'Download PDF'}
                className="w-7 h-7 rounded-md border border-[#262626] flex items-center justify-center text-[#a3a39c] hover:text-[#f7f5ef] transition-colors disabled:cursor-not-allowed disabled:opacity-45"
              >
                <Download size={13} />
              </button>
              <button
                onClick={() => setShowDoc(false)}
                className="w-7 h-7 rounded-md border border-[#262626] flex items-center justify-center text-[#a3a39c] hover:text-[#f7f5ef] transition-colors"
              >
                <X size={13} />
              </button>
            </div>
          </div>

          {/* Doc content — rendered exactly like the PDF export, since this is a preview of it */}
          <div className="flex-1 overflow-y-auto px-8 py-8">
            <div className="max-w-2xl mx-auto">
              {activeDoc === 'brief' && engagement.brief ? (
                <BriefReport brief={engagement.brief} clientName={engagement.client_name} />
              ) : activeDoc === 'proposal' && engagement.proposal ? (
                <ProposalReport proposal={engagement.proposal} clientName={engagement.client_name} />
              ) : (
                <p className="text-xs text-[#6e6e67]">No content yet.</p>
              )}
            </div>
          </div>

          {/* AI provenance footer */}
          <div className="px-5 py-3 border-t border-[#262626] flex items-center gap-2 bg-[#0a0a0a]">
            <div className="w-5 h-5 rounded bg-[#c9971f]/20 flex items-center justify-center">
              <Zap size={11} className="text-[#c9971f]" />
            </div>
            <p className="text-[10px] text-[#6e6e67] font-mono">
              Generated by The Exodus · {activeDoc === 'brief' ? 'Brief Generator' : 'Proposal Generator'} · Always verify before sending
            </p>
          </div>
        </div>
      )}

      {/* Show doc toggle when hidden */}
      {hasAnyDoc && !showDoc && (
        <div className="w-10 shrink-0 border-l border-[#262626] flex flex-col items-center pt-4 bg-[#0e0e0e]">
          <button
            onClick={() => setShowDoc(true)}
            className="w-8 h-8 rounded-md border border-[#262626] flex items-center justify-center text-[#6e6e67] hover:text-[#e8c34a] hover:border-[#c9971f]/40 transition-all"
            title="Show document"
          >
            <FileText size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
