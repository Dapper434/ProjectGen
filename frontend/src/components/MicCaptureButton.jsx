import { useCallback, useEffect, useRef, useState } from 'react';
import { Mic, Square, Loader2 } from 'lucide-react';
import ProviderBadge from './ProviderBadge';

const API = '/api';

// Rolling chunk length. 8s balances responsiveness against the Groq free tier:
// ~450 requests per audio-hour, comfortably inside the 2,000/day ceiling.
const CHUNK_MS = 8000;

/**
 * Push-to-dictate. Writes into the same setter the file-drop and paste paths
 * use, so nothing downstream knows or cares that the text was spoken.
 *
 * Three tiers, in order: the selected server driver → whatever the server fails
 * over to → the browser's own SpeechRecognition. The browser tier is the only
 * one that survives a dead connection, which is why it stays even though it is
 * the weakest.
 */
export default function MicCaptureButton({ engagementId, onText, onError, className = '' }) {
  const [state, setState] = useState('idle');   // idle | starting | recording | flushing
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [provider, setProvider] = useState(null);
  const [announcement, setAnnouncement] = useState('');

  const mediaRef = useRef(null);
  const streamRef = useRef(null);
  const audioCtxRef = useRef(null);
  const rafRef = useRef(null);
  const timerRef = useRef(null);
  // Only the first blob from a MediaRecorder carries the WebM/EBML header;
  // later blobs are undecodable alone. Keep it and prepend it to every
  // subsequent chunk. (Restarting the recorder each interval instead would drop
  // audio at every boundary.)
  const headerRef = useRef(null);
  const wordsRef = useRef(0);
  const browserRecRef = useRef(null);

  const cleanup = useCallback(() => {
    clearInterval(timerRef.current);
    cancelAnimationFrame(rafRef.current);
    try { mediaRef.current?.state !== 'inactive' && mediaRef.current?.stop(); } catch { /* already stopped */ }
    streamRef.current?.getTracks().forEach(t => t.stop());
    audioCtxRef.current?.close?.().catch(() => {});
    try { browserRecRef.current?.stop(); } catch { /* not running */ }
    mediaRef.current = null;
    streamRef.current = null;
    audioCtxRef.current = null;
    browserRecRef.current = null;
    headerRef.current = null;
  }, []);

  useEffect(() => cleanup, [cleanup]);

  async function uploadChunk(blob) {
    const body = new FormData();
    body.append('audio', blob, 'chunk.webm');
    if (engagementId) body.append('engagement_id', engagementId);
    const res = await fetch(`${API}/stt/chunk`, { method: 'POST', credentials: 'include', body });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Transcription failed (${res.status})`);
    }
    return res.json();
  }

  function startBrowserFallback() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) return false;
    const rec = new Recognition();
    rec.continuous = true;
    rec.interimResults = false;
    rec.lang = 'en-US';
    rec.onresult = e => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (!e.results[i].isFinal) continue;
        const text = e.results[i][0].transcript.trim();
        if (text) {
          wordsRef.current += text.split(/\s+/).length;
          onText(text);
        }
      }
    };
    rec.onerror = () => {};
    browserRecRef.current = rec;
    rec.start();
    setProvider({ label: 'Browser (offline)', isLocal: true, degraded: true });
    return true;
  }

  async function start() {
    setState('starting');
    onError?.('');
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setState('idle');
      // Name the actual fix rather than reporting a generic failure.
      const message = err?.name === 'NotAllowedError'
        ? 'Microphone access was blocked. Allow it for this site in your browser’s address-bar permissions, then try again.'
        : err?.name === 'NotFoundError'
          ? 'No microphone was found. Plug one in or pick a different input device, then try again.'
          : window.isSecureContext === false
            ? 'The microphone needs a secure connection. Open this page over HTTPS (or on localhost) and try again.'
            : `Could not start the microphone: ${err?.message || err}`;
      onError?.(message);
      return;
    }

    streamRef.current = stream;
    wordsRef.current = 0;
    headerRef.current = null;

    // Input level meter — a muted mic should be obvious in seconds, not after
    // ten silent minutes.
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      audioCtxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
        setLevel(Math.min(1, peak / 90));
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch { /* meter is a nicety; never block recording on it */ }

    const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm';
    const recorder = new MediaRecorder(stream, { mimeType: mime });
    mediaRef.current = recorder;

    recorder.ondataavailable = async e => {
      if (!e.data || e.data.size === 0) return;
      if (!headerRef.current) {
        headerRef.current = e.data;               // first blob holds the EBML header
      }
      const payload = headerRef.current === e.data
        ? e.data
        : new Blob([headerRef.current, e.data], { type: mime });
      try {
        const result = await uploadChunk(payload);
        setProvider({ label: result.provider_label, isLocal: result.is_local, degraded: result.degraded });
        if (result.text) {
          wordsRef.current += result.text.split(/\s+/).length;
          onText(result.text);
        }
      } catch (err) {
        // Server tier is gone — switch to the browser for the rest of the take
        // rather than dropping audio silently.
        if (!browserRecRef.current && startBrowserFallback()) {
          onError?.('Lost the connection to the speech service — switched to the browser’s own recognition.');
        } else {
          onError?.(err.message);
        }
      }
    };

    recorder.start(CHUNK_MS);
    setState('recording');
    setElapsed(0);
    timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000);
    setAnnouncement('Recording started');
  }

  async function stop() {
    setState('flushing');
    setAnnouncement('');
    const recorder = mediaRef.current;
    if (recorder && recorder.state !== 'inactive') {
      // requestData before stop flushes the trailing partial chunk, so the last
      // sentence spoken is not lost.
      await new Promise(resolve => {
        recorder.addEventListener('stop', resolve, { once: true });
        try { recorder.requestData(); } catch { /* not all browsers */ }
        recorder.stop();
      });
    }
    cleanup();
    setLevel(0);
    setState('idle');
    setAnnouncement(`Recording stopped, ${wordsRef.current} words added`);
  }

  const recording = state === 'recording';
  const busy = state === 'starting' || state === 'flushing';
  const mmss = `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`;

  return (
    <div className={`flex items-center gap-2.5 flex-wrap ${className}`}>
      <button
        type="button"
        onClick={recording ? stop : start}
        disabled={busy}
        aria-pressed={recording}
        aria-label={recording ? 'Stop dictation' : 'Start dictation'}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all disabled:opacity-60 ${
          recording ? 'text-white' : 'text-[#d6d4c9] hover:bg-[#1a1a1a]'
        }`}
        style={recording
          ? { background: '#e11d48', boxShadow: '0 0 12px rgba(225,29,72,0.35)' }
          : { border: '1px solid #333' }}
      >
        {busy ? <Loader2 size={13} className="animate-spin" />
          : recording ? <Square size={12} /> : <Mic size={13} />}
        {busy ? (state === 'starting' ? 'Starting…' : 'Finishing…') : recording ? `Stop · ${mmss}` : 'Dictate'}
      </button>

      {recording && (
        <div className="flex items-center gap-1.5" aria-hidden="true">
          <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: '#262626' }}>
            <div
              className="h-full transition-[width] duration-75"
              style={{ width: `${Math.round(level * 100)}%`, background: level > 0.05 ? '#10b981' : '#5c5c55' }}
            />
          </div>
          {level <= 0.02 && <span className="text-[10px] text-[#f59e0b]">no input</span>}
        </div>
      )}

      {provider && (
        <ProviderBadge driverLabel={provider.label} isLocal={provider.isLocal} />
      )}
      {provider?.degraded && (
        <span className="text-[10px] font-mono text-[#f59e0b]">DEGRADED</span>
      )}

      <span aria-live="polite" className="sr-only">{announcement}</span>
    </div>
  );
}
