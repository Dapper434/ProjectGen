import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams, useOutletContext } from 'react-router-dom';
import { Mic, Square, Send, Loader2, AlertCircle, ShieldCheck, Clock, Download } from 'lucide-react';
import AgendaChecklist from '../components/AgendaChecklist';
import ProviderBadge from '../components/ProviderBadge';

const API = '/api';
const CHUNK_MS = 15000;          // 15s: ~240 requests per meeting-hour on the Groq free tier
const POLL_MS = 2500;
const COVERAGE_MS = 45000;       // the server enforces the protocol's own debounce anyway

export default function Boardroom() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useOutletContext();

  const [session, setSession] = useState(null);
  const [segments, setSegments] = useState([]);
  const [error, setError] = useState('');
  const [recording, setRecording] = useState(false);
  const [provider, setProvider] = useState(null);
  const [typed, setTyped] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [nudged, setNudged] = useState(false);
  const [ending, setEnding] = useState(false);

  // Consent gate — nothing starts until the producer confirms the room was told.
  const [consented, setConsented] = useState(Boolean(id));
  const [title, setTitle] = useState('Client meeting');
  const [plannedMinutes, setPlannedMinutes] = useState(45);

  const mediaRef = useRef(null);
  const streamRef = useRef(null);
  const headerRef = useRef(null);
  const pollRef = useRef(null);
  const coverageRef = useRef(null);
  const tickRef = useRef(null);
  const scrollRef = useRef(null);
  const pinnedRef = useRef(true);
  const lastSeqRef = useRef(0);
  const engagementId = params.get('engagement_id');

  const poll = useCallback(async (sessionId) => {
    try {
      const res = await fetch(`${API}/boardroom/sessions/${sessionId}?since_seq=${lastSeqRef.current}`,
        { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      setSession(data);
      if (data.segments?.length) {
        setSegments(prev => [...prev, ...data.segments]);
        lastSeqRef.current = Math.max(lastSeqRef.current, ...data.segments.map(s => s.seq));
      }
    } catch { /* transient — the next poll retries */ }
  }, []);

  useEffect(() => {
    if (!id) return;
    poll(id);
    pollRef.current = setInterval(() => poll(id), POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [id, poll]);

  // Auto-scroll, but pause the moment the producer scrolls up to read back.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight;
  }, [segments]);

  useEffect(() => {
    if (!recording) return;
    tickRef.current = setInterval(() => setElapsed(s => s + 1), 1000);
    return () => clearInterval(tickRef.current);
  }, [recording]);

  // T-5 nudge: the moment this feature earns its keep.
  const plannedSec = (session?.planned_minutes || 0) * 60;
  const missingRequired = (session?.protocol?.items || []).filter(i => {
    const c = (session?.coverage || []).find(x => x.key === i.key);
    return i.required && (c?.status ?? 'missing') !== 'covered';
  });
  useEffect(() => {
    if (!nudged && plannedSec && elapsed >= plannedSec - 300 && missingRequired.length) setNudged(true);
  }, [elapsed, plannedSec, missingRequired.length, nudged]);

  async function createSession() {
    setError('');
    try {
      const res = await fetch(`${API}/boardroom/sessions`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          engagement_id: engagementId ? Number(engagementId) : null,
          title, meeting_kind: 'intake',
          planned_minutes: Number(plannedMinutes) || null,
          consent_ack: true,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setError(data.error || 'Could not start the session.'); return; }
      navigate(`/boardroom/${data.id}${engagementId ? `?engagement_id=${engagementId}` : ''}`, { replace: true });
    } catch {
      setError('Connection failed. Is the backend running?');
    }
  }

  async function startRecording() {
    setError('');
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setError(err?.name === 'NotAllowedError'
        ? 'Microphone access was blocked. Allow it for this site in your browser’s address-bar permissions, then try again.'
        : window.isSecureContext === false
          ? 'The microphone needs a secure connection — open this page over HTTPS (or on localhost).'
          : `Could not start the microphone: ${err?.message || err}`);
      return;
    }
    streamRef.current = stream;
    headerRef.current = null;

    const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
    const recorder = new MediaRecorder(stream, { mimeType: mime });
    mediaRef.current = recorder;

    recorder.ondataavailable = async e => {
      if (!e.data?.size) return;
      if (!headerRef.current) headerRef.current = e.data;   // only blob 0 has the EBML header
      const payload = headerRef.current === e.data ? e.data : new Blob([headerRef.current, e.data], { type: mime });
      const body = new FormData();
      body.append('audio', payload, 'chunk.webm');
      body.append('seconds', String(CHUNK_MS / 1000));
      try {
        const res = await fetch(`${API}/boardroom/sessions/${id}/chunk`, {
          method: 'POST', credentials: 'include', body,
        });
        if (res.ok) {
          const data = await res.json();
          setProvider({ label: data.provider_label, isLocal: data.is_local, degraded: data.degraded });
        }
      } catch { setError('Lost the connection — captured audio will resume when it returns.'); }
    };

    recorder.start(CHUNK_MS);
    setRecording(true);
    coverageRef.current = setInterval(() => {
      fetch(`${API}/boardroom/sessions/${id}/coverage`, { method: 'POST', credentials: 'include' })
        .catch(() => {});
    }, COVERAGE_MS);
  }

  function stopRecording() {
    clearInterval(coverageRef.current);
    try { mediaRef.current?.state !== 'inactive' && mediaRef.current?.stop(); } catch { /* stopped */ }
    streamRef.current?.getTracks().forEach(t => t.stop());
    setRecording(false);
  }

  async function addTyped() {
    if (!typed.trim()) return;
    await fetch(`${API}/boardroom/sessions/${id}/segments`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: typed, source: 'typed' }),
    });
    setTyped('');
    poll(id);
  }

  async function endSession() {
    stopRecording();
    setEnding(true);
    await fetch(`${API}/boardroom/sessions/${id}/end`, { method: 'POST', credentials: 'include' });
    setTimeout(() => { poll(id); setEnding(false); }, 3000);
  }

  async function promote() {
    const target = session?.engagement_id || engagementId;
    if (!target) { setError('This session is not linked to an engagement.'); return; }
    const res = await fetch(`${API}/boardroom/sessions/${id}/promote`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ engagement_id: Number(target) }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError(data.error || 'Could not promote this transcript.'); return; }
    navigate(`/engagements/${target}`);
  }

  // --- consent gate ---------------------------------------------------------
  if (!id) {
    return (
      <div className="px-8 py-7 max-w-xl">
        <h1 className="font-serif text-[#f7f5ef] text-2xl mb-1.5">Start a Boardroom session</h1>
        <p className="text-sm text-[#8a8a83] mb-6">
          Live transcription with an agenda checklist, so nothing important is missed before the client hangs up.
        </p>
        {error && <p role="alert" className="text-sm text-rose-500 mb-4">{error}</p>}

        <div className="rounded-xl p-5 flex flex-col gap-4" style={{ background: '#141414', border: '1px solid #242424' }}>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="br-title" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">TITLE</label>
            <input id="br-title" value={title} onChange={e => setTitle(e.target.value)}
              className="rounded-lg px-3 py-2 text-[12px] text-[#d6d4c9] bg-[#0e0e0e]"
              style={{ border: '1px solid #262626' }} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="br-mins" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">
              PLANNED LENGTH (MINUTES)
            </label>
            <input id="br-mins" type="number" value={plannedMinutes}
              onChange={e => setPlannedMinutes(e.target.value)}
              className="rounded-lg px-3 py-2 text-[12px] text-[#d6d4c9] bg-[#0e0e0e] w-32"
              style={{ border: '1px solid #262626' }} />
            <p className="text-[10px] text-[#5c5c55]">Used for the five-minutes-remaining reminder.</p>
          </div>

          <label htmlFor="br-consent" className="flex items-start gap-2.5 cursor-pointer">
            <input id="br-consent" type="checkbox" checked={consented}
              onChange={e => setConsented(e.target.checked)} className="mt-0.5 accent-[#c9971f]" />
            <span className="text-[12px] text-[#d6d4c9]">
              Everyone present has been told this meeting is being transcribed.
              <span className="block text-[10px] text-[#8a8a83] mt-0.5">
                Recorded against your name and time-stamped. Audio is not stored unless the server is
                configured to keep it; the transcript is.
              </span>
            </span>
          </label>

          <button onClick={createSession} disabled={!consented}
            className="self-start flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-white text-[13px] font-medium transition-all hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}>
            <ShieldCheck size={14} /> Start session
          </button>
        </div>
      </div>
    );
  }

  if (!session) return <div className="px-8 py-7 text-sm text-[#8a8a83]">Loading…</div>;

  const live = session.status === 'live';
  const mmss = `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`;

  return (
    <div className="flex flex-col h-full">
      <div className="px-8 pt-7 pb-4 flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-serif text-[#f7f5ef] text-2xl mb-1">{session.title}</h1>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-mono px-2 py-0.5 rounded"
              style={live ? { color: '#e11d48', background: 'rgba(225,29,72,0.12)' }
                : { color: '#8a8a83', background: '#1a1a1a' }}>
              {session.status.toUpperCase()}
            </span>
            {provider && <ProviderBadge driverLabel={provider.label} isLocal={provider.isLocal} />}
            {session.protocol_version && (
              <span className="text-[10px] font-mono text-[#5c5c55]">
                protocol v{session.protocol_version} (frozen)
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <a href={`${API}/boardroom/sessions/${id}/export`}
            className="flex items-center gap-1 text-[11px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors">
            <Download size={11} /> Export
          </a>
          {live && (
            <button onClick={endSession} disabled={ending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] text-[#d6d4c9] transition-colors hover:bg-[#1a1a1a] disabled:opacity-50"
              style={{ border: '1px solid #333' }}>
              {ending ? <Loader2 size={12} className="animate-spin" /> : <Square size={11} />}
              {ending ? 'Wrapping up…' : 'End meeting'}
            </button>
          )}
        </div>
      </div>

      {error && <p role="alert" className="px-8 text-sm text-rose-500 mb-3">{error}</p>}

      {nudged && missingRequired.length > 0 && (
        <div className="mx-8 mb-3 flex items-start gap-2 p-3 rounded-lg" role="status"
          style={{ background: 'rgba(245,158,11,0.10)', border: '1px solid rgba(245,158,11,0.3)' }}>
          <Clock size={14} className="text-[#f59e0b] shrink-0 mt-0.5" />
          <div>
            <p className="text-xs text-[#fcd34d]">Five minutes left — still uncovered:</p>
            <p className="text-xs text-[#fcd34d] mt-0.5">{missingRequired.map(i => i.label).join(', ')}</p>
            {session.protocol?.closing_script && (
              <p className="text-[11px] text-[#a3a39c] mt-1.5 italic">
                “{session.protocol.closing_script.replace('{missing}', missingRequired.map(i => i.label).join(', '))}”
              </p>
            )}
          </div>
        </div>
      )}

      <div className="flex-1 flex gap-5 px-8 pb-7 min-h-0 flex-col lg:flex-row">
        {/* Transcript — deliberately NOT an aria-live region: a continuously
            updating one is unusable with a screen reader. */}
        <div className="lg:w-[58%] flex flex-col min-h-0">
          <span className="text-[14px] font-semibold text-[#f2f0e8] mb-2">Transcript</span>
          <div
            ref={scrollRef}
            onScroll={e => {
              const el = e.currentTarget;
              pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
            }}
            aria-live="off"
            className="flex-1 min-h-[16rem] overflow-y-auto rounded-xl px-4 py-3 flex flex-col gap-2"
            style={{ background: '#141414', border: '1px solid #242424' }}
          >
            {segments.map(s => (
              <div key={s.seq} id={`seg-${s.seq}`} className="flex gap-2.5">
                <span className="text-[9px] font-mono text-[#5c5c55] shrink-0 pt-1">{s.seq}</span>
                <p className="text-[12px] text-[#d6d4c9]">
                  {s.speaker_label && <span className="text-[#e8c34a]">{s.speaker_label}: </span>}
                  {s.text}
                  {s.source === 'typed' && <span className="text-[9px] font-mono text-[#5c5c55] ml-1.5">TYPED</span>}
                </p>
              </div>
            ))}
            {segments.length === 0 && (
              <p className="text-[12px] text-[#5c5c55]">
                Nothing captured yet. Start recording, or type a note below — the agenda check works either way.
              </p>
            )}
          </div>

          {live && (
            <div className="mt-3 flex flex-col gap-2">
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  onClick={recording ? stopRecording : startRecording}
                  aria-pressed={recording}
                  aria-label={recording ? 'Stop recording' : 'Start recording'}
                  className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[13px] font-medium transition-all"
                  style={recording
                    ? { background: '#e11d48', color: 'white', boxShadow: '0 0 12px rgba(225,29,72,0.35)' }
                    : { border: '1px solid #333', color: '#d6d4c9' }}
                >
                  {recording ? <Square size={12} /> : <Mic size={13} />}
                  {recording ? `Stop · ${mmss}` : 'Start recording'}
                </button>
                <span aria-live="polite" className="sr-only">
                  {recording ? 'Recording started' : ''}
                </span>
              </div>
              <div className="flex gap-2">
                <label htmlFor="br-typed" className="sr-only">Type a note</label>
                <input
                  id="br-typed" value={typed} onChange={e => setTyped(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addTyped()}
                  placeholder="Type anything the mic missed…"
                  className="flex-1 rounded-lg px-3 py-2 text-[12px] text-[#d6d4c9] bg-[#0e0e0e]"
                  style={{ border: '1px solid #262626' }}
                />
                <button onClick={addTyped} aria-label="Add note"
                  className="px-3 rounded-lg text-[#a3a39c] hover:text-[#e8c34a] transition-colors"
                  style={{ border: '1px solid #333' }}>
                  <Send size={13} />
                </button>
              </div>
            </div>
          )}

          {session.status === 'ended' && (
            <div className="mt-3 rounded-xl p-4" style={{ background: '#141414', border: '1px solid #242424' }}>
              <p className="text-[13px] text-[#d6d4c9] mb-2">Meeting ended.</p>
              {session.polished_transcript ? (
                <button onClick={promote}
                  className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-white text-[13px] font-medium hover:opacity-90"
                  style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}>
                  <Send size={13} /> Generate Production Brief
                </button>
              ) : (
                <p className="flex items-center gap-1.5 text-[12px] text-[#8a8a83]" aria-live="polite">
                  <Loader2 size={12} className="animate-spin" /> Running the final coverage check and cleanup…
                </p>
              )}
            </div>
          )}

          {session.status === 'promoted' && (
            <div className="mt-3 rounded-xl p-4 flex items-center gap-2"
              style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.25)' }}>
              <AlertCircle size={13} className="text-[#7dd3fc]" />
              <p className="text-xs text-[#7dd3fc]">Promoted — the brief is generating on the engagement.</p>
            </div>
          )}
        </div>

        {/* Agenda */}
        <div className="lg:w-[42%] overflow-y-auto">
          <AgendaChecklist
            protocol={session.protocol}
            coverage={session.coverage}
            onJumpToSeq={seq => document.getElementById(`seg-${seq}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
          />
        </div>
      </div>
    </div>
  );
}
