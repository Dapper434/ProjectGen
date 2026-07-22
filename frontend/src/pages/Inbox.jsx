import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { Inbox as InboxIcon, ExternalLink, Users, Clock, Calendar, Sparkles, X, Link2, ChevronDown, ChevronUp } from 'lucide-react';
import { timeAgo } from '../lib/engagements';

const API = '/api';

// What attaching to an engagement in each state will trigger — mirrors
// _transcript_dispatch_for on the backend.
const STAGE_EFFECT = {
  awaiting_transcript: 'will generate the production brief',
  brief_ready: 'will refine the existing brief',
  awaiting_review_transcript: 'will generate the client proposal',
};

function MetaChip({ icon: Icon, children }) {
  if (!children) return null;
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-[#8a8a83]">
      <Icon size={11} className="text-[#5c5c55]" />
      {children}
    </span>
  );
}

function AttachPanel({ item, engagements, clients, onDone, onCancel }) {
  const [mode, setMode] = useState('existing'); // 'existing' | 'new'
  const [engId, setEngId] = useState('');
  const [clientId, setClientId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const attachable = engagements.filter(e => STAGE_EFFECT[e.status]);

  const handleAttach = async () => {
    const body = mode === 'existing'
      ? { engagement_id: Number(engId) }
      : { client_id: Number(clientId) };
    if (mode === 'existing' && !engId) { setError('Pick an engagement.'); return; }
    if (mode === 'new' && !clientId) { setError('Pick a client.'); return; }
    setBusy(true);
    setError('');
    try {
      const res = await fetch(`${API}/inbox/${item.id}/attach`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        credentials: 'include',
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        onDone();
        navigate(`/engagements/${data.engagement_id}`);
      } else {
        setError(data.error || 'Attach failed.');
        setBusy(false);
      }
    } catch {
      setError('Connection failed. Is the backend running?');
      setBusy(false);
    }
  };

  const selectedEng = attachable.find(e => e.id === Number(engId));

  return (
    <div className="mt-3 rounded-lg p-4 flex flex-col gap-3" style={{ background: '#1a1a1a', border: '1px solid #262626' }}>
      <div className="flex gap-2">
        {[['existing', 'Existing engagement'], ['new', 'New engagement']].map(([id, label]) => (
          <button
            key={id}
            onClick={() => { setMode(id); setError(''); }}
            className={`px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors ${
              mode === id ? 'bg-[#c9971f]/20 text-[#e8c34a] border border-[#c9971f]/40' : 'text-[#8a8a83] border border-[#262626] hover:text-[#d6d4c9]'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {mode === 'existing' ? (
        <div>
          <select
            value={engId}
            onChange={e => setEngId(e.target.value)}
            className="w-full bg-[#141414] border border-[#262626] rounded-lg px-3 py-2.5 text-sm text-[#f7f5ef] focus:outline-none focus:border-[#c9971f]/60"
          >
            <option value="">Select an engagement…</option>
            {attachable.map(e => (
              <option key={e.id} value={e.id}>
                #{e.id} · {e.client_name} · {e.status.replaceAll('_', ' ')}
              </option>
            ))}
          </select>
          {selectedEng && (
            <p className="text-[11px] text-[#c9971f] mt-1.5 flex items-center gap-1">
              <Sparkles size={11} /> Attaching here {STAGE_EFFECT[selectedEng.status]}.
            </p>
          )}
        </div>
      ) : (
        <div>
          <select
            value={clientId}
            onChange={e => setClientId(e.target.value)}
            className="w-full bg-[#141414] border border-[#262626] rounded-lg px-3 py-2.5 text-sm text-[#f7f5ef] focus:outline-none focus:border-[#c9971f]/60"
          >
            <option value="">Select a client…</option>
            {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <p className="text-[11px] text-[#8a8a83] mt-1.5">
            Creates a fresh engagement for this client — the transcript {STAGE_EFFECT.awaiting_transcript}.
          </p>
        </div>
      )}

      {error && <p role="alert" className="text-xs text-rose-500">{error}</p>}

      <div className="flex gap-2 justify-end">
        <button onClick={onCancel} className="px-3.5 py-2 rounded-lg text-[12px] text-[#8a8a83] border border-[#262626] hover:text-[#d6d4c9] transition-colors">
          Cancel
        </button>
        <button
          onClick={handleAttach}
          disabled={busy}
          className="px-4 py-2 rounded-lg bg-[#c9971f] hover:bg-[#a67a17] text-white text-[12px] font-medium transition-all disabled:opacity-50 disabled:cursor-wait"
        >
          {busy ? 'Attaching…' : 'Attach & Process'}
        </button>
      </div>
    </div>
  );
}

function InboxItem({ item, users, canAssign, engagements, clients, refresh }) {
  const [attaching, setAttaching] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [rawText, setRawText] = useState(null);

  const handleAssign = async (userId) => {
    await fetch(`${API}/inbox/${item.id}/assign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId ? Number(userId) : null }),
      credentials: 'include',
    });
    refresh();
  };

  const handleDismiss = async () => {
    await fetch(`${API}/inbox/${item.id}/dismiss`, { method: 'POST', credentials: 'include' });
    refresh();
  };

  const toggleTranscript = async () => {
    if (!expanded && rawText === null) {
      const res = await fetch(`${API}/inbox/${item.id}`, { credentials: 'include' });
      if (res.ok) setRawText((await res.json()).raw_text || '');
    }
    setExpanded(v => !v);
  };

  const isPending = item.status === 'pending';

  return (
    <div className="px-5 py-4">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-[14px] font-medium text-[#f2f0e8]">{item.title || 'Untitled meeting'}</p>
            {!item.is_external_meeting && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#262626] text-[#8a8a83]">internal</span>
            )}
            {item.status === 'processed' && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
                {item.auto_matched ? 'auto-matched' : 'attached'}
              </span>
            )}
            {item.status === 'dismissed' && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#262626] text-[#6e6e67]">dismissed</span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-1.5 flex-wrap">
            <MetaChip icon={Calendar}>{item.meeting_date}</MetaChip>
            <MetaChip icon={Clock}>{item.duration_minutes ? `${item.duration_minutes} min` : null}</MetaChip>
            <MetaChip icon={Users}>{(item.attendees || []).join(', ') || null}</MetaChip>
            {item.share_url && (
              <a href={item.share_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11px] text-[#c9971f] hover:text-[#e8c34a]">
                <ExternalLink size={11} /> Fathom recording
              </a>
            )}
          </div>
          {item.summary ? (
            <p className="text-[12px] text-[#a3a39c] mt-2 line-clamp-2 whitespace-pre-line">{item.summary}</p>
          ) : (
            <p className="text-[12px] text-[#6e6e67] mt-2 line-clamp-2 font-mono">{item.preview}</p>
          )}
          <div className="flex items-center gap-3 mt-2">
            <button onClick={toggleTranscript} className="inline-flex items-center gap-1 text-[11px] text-[#8a8a83] hover:text-[#d6d4c9] transition-colors">
              {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
              {expanded ? 'Hide transcript' : 'View transcript'}
            </button>
            <span className="text-[11px] text-[#5c5c55]">
              via Fathom{item.recorded_by ? ` · recorded by ${item.recorded_by}` : ''} · {timeAgo(item.received_at)}
            </span>
          </div>
          {expanded && (
            <pre className="mt-3 p-3 rounded-lg text-[11px] text-[#a3a39c] whitespace-pre-wrap max-h-64 overflow-y-auto font-mono" style={{ background: '#0d0d0d', border: '1px solid #262626' }}>
              {rawText === null ? 'Loading…' : rawText || 'Empty transcript.'}
            </pre>
          )}
        </div>

        {isPending && (
          <div className="flex items-center gap-2 shrink-0">
            <select
              value={item.assigned_to?.id || ''}
              onChange={e => handleAssign(e.target.value)}
              disabled={!canAssign}
              title={canAssign ? 'Assign to a teammate' : 'Only Account Managers and Admins can assign'}
              className="bg-[#1a1a1a] border border-[#262626] rounded-lg px-2.5 py-2 text-[12px] text-[#d6d4c9] focus:outline-none focus:border-[#c9971f]/60 disabled:opacity-60"
            >
              <option value="">Unassigned</option>
              {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
            </select>
            <button
              onClick={() => setAttaching(v => !v)}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-[#c9971f] hover:bg-[#a67a17] text-white text-[12px] font-medium transition-all"
            >
              <Link2 size={12} /> Attach
            </button>
            <button
              onClick={handleDismiss}
              title="Dismiss — not client work"
              className="w-8 h-8 rounded-md border border-[#262626] flex items-center justify-center text-[#6e6e67] hover:text-rose-500 hover:border-rose-500/40 transition-colors"
            >
              <X size={13} />
            </button>
          </div>
        )}
        {item.status === 'processed' && item.engagement_id && (
          <a href={`/engagements/${item.engagement_id}`} className="shrink-0 text-[12px] text-[#c9971f] hover:text-[#e8c34a] flex items-center gap-1">
            Open engagement #{item.engagement_id} →
          </a>
        )}
      </div>

      {attaching && isPending && (
        <AttachPanel
          item={item}
          engagements={engagements}
          clients={clients}
          onDone={refresh}
          onCancel={() => setAttaching(false)}
        />
      )}
    </div>
  );
}

export default function Inbox() {
  const { user } = useOutletContext();
  const canAssign = user?.role === 'Account Manager' || user?.role === 'Admin';

  const [items, setItems] = useState([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [users, setUsers] = useState([]);
  const [engagements, setEngagements] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchInbox = useCallback(async (all = showAll) => {
    try {
      const res = await fetch(`${API}/inbox?status=${all ? 'all' : 'pending'}`, { credentials: 'include' });
      if (res.ok) {
        const data = await res.json();
        setItems(data.items);
        setPendingCount(data.pending_count);
      }
    } catch (err) {
      console.error(err);
    }
    setLoading(false);
  }, [showAll]);

  useEffect(() => { fetchInbox(); }, [fetchInbox]);

  useEffect(() => {
    (async () => {
      try {
        const [u, e, c] = await Promise.all([
          fetch(`${API}/users`, { credentials: 'include' }),
          fetch(`${API}/engagements`, { credentials: 'include' }),
          fetch(`${API}/clients`, { credentials: 'include' }),
        ]);
        if (u.ok) setUsers(await u.json());
        if (e.ok) setEngagements(await e.json());
        if (c.ok) setClients(await c.json());
      } catch (err) {
        console.error(err);
      }
    })();
  }, []);

  return (
    <div className="max-w-4xl mx-auto px-8 py-8">
      <div className="mb-8 flex items-end justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <InboxIcon size={18} className="text-[#c9971f]" />
            <h1 className="font-serif text-[#f7f5ef] text-2xl">Transcript Inbox</h1>
            {pendingCount > 0 && (
              <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-[#c9971f]/15 text-[#e8c34a] border border-[#c9971f]/30">
                {pendingCount} pending
              </span>
            )}
          </div>
          <p className="text-sm text-[#a3a39c]">
            Meeting transcripts arrive here automatically from Fathom when a Zoom call ends. Meetings that clearly match a client are processed on the spot — the rest wait here to be assigned and attached.
          </p>
        </div>
        <button
          onClick={() => { setShowAll(v => !v); setLoading(true); fetchInbox(!showAll); }}
          className="text-[12px] text-[#8a8a83] hover:text-[#d6d4c9] transition-colors shrink-0"
        >
          {showAll ? 'Show pending only' : 'Show all (incl. handled)'}
        </button>
      </div>

      <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
        {loading ? (
          <div className="px-5 py-10 text-center text-[13px] text-[#8a8a83]">Loading…</div>
        ) : items.length === 0 ? (
          <div className="px-5 py-10 text-center text-[13px] text-[#8a8a83]">
            {showAll
              ? 'Nothing has arrived from Fathom yet. Register the webhook (backend/fathom.py) and finish a recorded Zoom meeting.'
              : 'Inbox zero — no pending transcripts.'}
          </div>
        ) : (
          <div className="divide-y" style={{ borderColor: '#191919' }}>
            {items.map(item => (
              <InboxItem
                key={item.id}
                item={item}
                users={users}
                canAssign={canAssign}
                engagements={engagements}
                clients={clients}
                refresh={() => fetchInbox()}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
