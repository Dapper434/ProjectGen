import { useCallback, useEffect, useState } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';
import {
  Coins, Calendar, Award, Ticket, Briefcase, HelpCircle, LogOut, Loader2, Check, X,
} from 'lucide-react';

const API = '/api';

const TABS = [
  { key: 'dashboard', label: 'Dashboard', icon: Coins },
  { key: 'offers', label: 'Offers', icon: Briefcase },
  { key: 'certifications', label: 'Certifications', icon: Award },
  { key: 'events', label: 'Events', icon: Ticket },
  { key: 'availability', label: 'Availability', icon: Calendar },
  { key: 'picked', label: 'How I get picked', icon: HelpCircle },
];

function Card({ children, className = '' }) {
  return (
    <div className={`rounded-xl p-5 ${className}`} style={{ background: '#141414', border: '1px solid #242424' }}>
      {children}
    </div>
  );
}

// --- How I get picked --------------------------------------------------------
// Renders the authoritative policy documents live. A hand-written copy would
// drift from the real weights within one edit, and the moment a talent notices,
// the whole mechanism loses legitimacy.
function HowIGetPicked({ policies }) {
  if (!policies) return <p className="text-[13px] text-[#8a8a83]">Loading…</p>;
  const token = policies.talent_token_policy || {};
  const casting = policies.casting_policy || {};
  const earn = token.earn || {};
  const spend = token.spend || {};
  const idle = token.idle_accrual || {};
  const weights = casting.weights || {};
  const mine = policies.my_balance || {};

  const earnLabel = (k, v) => {
    const value = typeof v === 'object' ? v.default : v;
    const text = {
      event_attendance: 'Attend an industry event or workshop',
      certification_completed: 'Complete a certification',
      assignment_completed_on_time: 'Finish an assignment on time',
      client_rating_5: 'Get a 5-star rating from a client',
      referral_hired: 'Refer someone who gets hired',
    }[k] || k.replace(/_/g, ' ');
    return [text, value];
  };

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <p className="text-[15px] font-semibold text-[#f2f0e8] mb-1">Where you stand</p>
        <div className="flex items-baseline gap-3 flex-wrap">
          <span className="text-[28px] font-semibold text-[#e8c34a]">{mine.total ?? 0}</span>
          <span className="text-[12px] text-[#8a8a83]">
            = {mine.ledger ?? 0} earned and spent + {mine.idle ?? 0} from {mine.idle_days ?? 0} days
            since your last assignment
          </span>
        </div>
        {policies.next_best_action && (
          <p className="mt-3 text-[12px] text-[#10b981]">
            Best next step: {policies.next_best_action.text}
          </p>
        )}
      </Card>

      <Card>
        <p className="text-[15px] font-semibold text-[#f2f0e8] mb-2">How you earn tokens</p>
        <ul className="flex flex-col gap-1.5">
          {Object.entries(earn).map(([k, v]) => {
            const [text, value] = earnLabel(k, v);
            return (
              <li key={k} className="flex justify-between gap-3 text-[12px]">
                <span className="text-[#a3a39c]">{text}</span>
                <span className="font-mono text-[#10b981]">+{value}</span>
              </li>
            );
          })}
        </ul>
      </Card>

      <Card>
        <p className="text-[15px] font-semibold text-[#f2f0e8] mb-2">How tokens are spent</p>
        <ul className="flex flex-col gap-1.5 mb-3">
          {Object.entries(spend).map(([k, v]) => (
            <li key={k} className="flex justify-between gap-3 text-[12px]">
              <span className="text-[#a3a39c]">{k.replace(/_/g, ' ')}</span>
              <span className="font-mono text-[#f43f5e]">{v}</span>
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-[#8a8a83] leading-relaxed">
          Accepting work costs tokens on purpose. This is a fair rotation, not a
          leaderboard — working draws down your priority and time between jobs builds it back
          up, so the same few people cannot take every booking.
        </p>
      </Card>

      <Card>
        <p className="text-[15px] font-semibold text-[#f2f0e8] mb-2">Time between jobs</p>
        <p className="text-[12px] text-[#a3a39c]">
          You earn <span className="text-[#e8c34a]">{idle.tokens_per_idle_day}</span> tokens per day
          after <span className="text-[#e8c34a]">{idle.starts_after_days}</span> days without an
          assignment, up to a cap of <span className="text-[#e8c34a]">{idle.cap}</span>.
          You are currently at <span className="text-[#e8c34a]">{mine.idle ?? 0}</span>.
        </p>
      </Card>

      <Card>
        <p className="text-[15px] font-semibold text-[#f2f0e8] mb-2">What else counts</p>
        <div className="flex flex-col gap-2">
          {Object.entries(weights).map(([k, v]) => (
            <div key={k}>
              <div className="flex justify-between text-[11px] mb-0.5">
                <span className="text-[#a3a39c]">{k.replace(/_/g, ' ')}</span>
                <span className="font-mono text-[#5c5c55]">{Math.round(v * 100)}%</span>
              </div>
              <div className="h-1.5 rounded-full overflow-hidden" style={{ background: '#0e0e0e' }}>
                <div className="h-full" style={{ width: `${v * 100}%`, background: '#c9971f' }} />
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <p className="text-[15px] font-semibold text-[#f2f0e8] mb-2">The hard requirements</p>
        <ul className="flex flex-col gap-1 text-[12px] text-[#a3a39c]">
          <li>· Your profile is active.</li>
          <li>· You have the skills the role actually requires.</li>
          <li>· You have no calendar clash for those dates.</li>
        </ul>
        <p className="text-[11px] text-[#f59e0b] mt-2">
          No token total overcomes a clash. Keeping your availability current is the single most
          useful thing you can do here.
        </p>
      </Card>
    </div>
  );
}

export default function TalentPortal() {
  const [params] = useSearchParams();
  const location = useLocation();
  const inviteToken = params.get('token');

  const [me, setMe] = useState(null);
  const [tab, setTab] = useState('dashboard');
  // 'signin' | 'signup'. Sign-up is open: anyone can join the bench themselves,
  // no invite needed. /talent/join links straight into it.
  const [mode, setMode] = useState(location.pathname === '/talent/join' ? 'signup' : 'signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [locationField, setLocationField] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const [ledger, setLedger] = useState([]);
  const [offers, setOffers] = useState([]);
  const [certs, setCerts] = useState([]);
  const [events, setEvents] = useState([]);
  const [blocks, setBlocks] = useState([]);
  const [policies, setPolicies] = useState(null);
  const [quiz, setQuiz] = useState(null);
  const [answers, setAnswers] = useState({});
  const [code, setCode] = useState('');

  const loadMe = useCallback(async () => {
    const res = await fetch(`${API}/talent/me`, { credentials: 'include' });
    if (res.ok) setMe(await res.json());
  }, []);

  useEffect(() => { loadMe(); }, [loadMe]);

  const loadTab = useCallback(async () => {
    if (!me) return;
    const get = async (path, setter) => {
      const res = await fetch(`${API}/talent/${path}`, { credentials: 'include' });
      if (res.ok) setter(await res.json());
    };
    if (tab === 'dashboard') await get('tokens', d => setLedger(d.ledger || []));
    if (tab === 'offers') await get('offers', setOffers);
    if (tab === 'certifications') await get('certifications', setCerts);
    if (tab === 'events') await get('events', setEvents);
    if (tab === 'availability') await get('availability', setBlocks);
    if (tab === 'picked') await get('policies', setPolicies);
  }, [tab, me]);

  useEffect(() => { loadTab(); }, [loadTab]);

  async function submitAuth(e) {
    e.preventDefault();
    setBusy(true); setError(''); setNotice('');
    try {
      let path = 'login';
      let body = { email, password };
      if (inviteToken) {
        path = 'set-password';
        body = { token: inviteToken, password };
      } else if (mode === 'signup') {
        path = 'signup';
        body = { name, email, password, title: title || undefined, location: locationField || undefined };
      }

      const res = await fetch(`${API}/talent/${path}`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.error || (mode === 'signup' ? 'Could not create that account.' : 'Sign-in failed.'));
        return;
      }
      if (data.claim_sent) {
        // Already on the bench: the account is theirs to claim by email, not to
        // create here. Nothing is signed in yet.
        setNotice(data.link
          ? `${data.message} Console driver — link: ${data.link}`
          : data.message);
        setMode('signin');
        setPassword('');
        return;
      }
      loadMe();
    } finally { setBusy(false); }
  }

  async function logout() {
    await fetch(`${API}/talent/logout`, { method: 'POST', credentials: 'include' });
    setMe(null);
  }

  async function respond(offerId, action) {
    setError('');
    const res = await fetch(`${API}/talent/offers/${offerId}/respond`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError(data.error || 'Could not record your response.'); return; }
    loadMe(); loadTab();
  }

  async function startQuiz(key) {
    setError(''); setAnswers({});
    const res = await fetch(`${API}/talent/certifications/${key}/enroll`, {
      method: 'POST', credentials: 'include',
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError(data.error || 'Could not start that certification.'); return; }
    setQuiz({ ...data, key });
  }

  async function submitQuiz() {
    const ordered = (quiz.questions || []).map((_, i) => answers[i]);
    const res = await fetch(`${API}/talent/certifications/${quiz.enrollment_id}/submit`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answers: ordered }),
    });
    const data = await res.json().catch(() => ({}));
    setQuiz(null);
    setNotice(data.passed
      ? `Passed with ${Math.round(data.score * 100)}% — tokens credited.`
      : `Scored ${Math.round((data.score || 0) * 100)}%. You can retake it after ${data.cooldown_hours || 24} hours.`);
    loadMe(); loadTab();
  }

  async function checkin() {
    setError(''); setNotice('');
    const res = await fetch(`${API}/talent/events/checkin`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError(data.error || 'Check-in failed.'); return; }
    setNotice(data.already
      ? `You're already checked in to ${data.event}.`
      : `Checked in to ${data.event} — tokens credited.`);
    setCode(''); loadMe(); loadTab();
  }

  // --- sign in / join / claim an invite -------------------------------------
  if (!me) {
    const signingUp = !inviteToken && mode === 'signup';
    const needsNewPassword = signingUp || !!inviteToken;
    return (
      <div className="min-h-screen flex items-center justify-center px-4 py-10" style={{ background: '#0a0a0a' }}>
        <form onSubmit={submitAuth} className="w-full max-w-sm flex flex-col gap-4">
          <div className="flex items-center gap-2.5 mb-1">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}>
              <span className="text-white font-bold text-xs">EX</span>
            </div>
            <span className="text-[#f7f5ef] font-semibold text-[15px]">Talent Portal</span>
          </div>

          {inviteToken ? (
            <p className="text-[13px] text-[#8a8a83]">Choose a password to finish setting up your account.</p>
          ) : signingUp ? (
            <p className="text-[13px] text-[#8a8a83]">
              Join the GDF talent bench. Your account is live the moment you create it — set your
              availability, earn tokens, and get considered for every production we crew.
            </p>
          ) : null}

          {signingUp && (
            <>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="tp-name" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">FULL NAME</label>
                <input id="tp-name" value={name} onChange={e => setName(e.target.value)}
                  required autoComplete="name"
                  className="rounded-lg px-3 py-2 text-[13px] text-[#d6d4c9] bg-[#0e0e0e]"
                  style={{ border: '1px solid #262626' }} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="tp-title" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">DISCIPLINE</label>
                  <input id="tp-title" value={title} onChange={e => setTitle(e.target.value)}
                    placeholder="e.g. Editor"
                    className="rounded-lg px-3 py-2 text-[13px] text-[#d6d4c9] bg-[#0e0e0e] placeholder:text-[#4a4a45]"
                    style={{ border: '1px solid #262626' }} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="tp-loc" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">BASED IN</label>
                  <input id="tp-loc" value={locationField} onChange={e => setLocationField(e.target.value)}
                    placeholder="e.g. Nairobi"
                    className="rounded-lg px-3 py-2 text-[13px] text-[#d6d4c9] bg-[#0e0e0e] placeholder:text-[#4a4a45]"
                    style={{ border: '1px solid #262626' }} />
                </div>
              </div>
            </>
          )}

          {!inviteToken && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor="tp-email" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">EMAIL</label>
              <input id="tp-email" type="email" value={email} onChange={e => setEmail(e.target.value)}
                required autoComplete={signingUp ? 'email' : 'username'}
                className="rounded-lg px-3 py-2 text-[13px] text-[#d6d4c9] bg-[#0e0e0e]"
                style={{ border: '1px solid #262626' }} />
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <label htmlFor="tp-pass" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">PASSWORD</label>
            <input id="tp-pass" type="password" value={password} onChange={e => setPassword(e.target.value)}
              required autoComplete={needsNewPassword ? 'new-password' : 'current-password'}
              minLength={needsNewPassword ? 10 : undefined}
              className="rounded-lg px-3 py-2 text-[13px] text-[#d6d4c9] bg-[#0e0e0e]"
              style={{ border: '1px solid #262626' }} />
            {needsNewPassword && <p className="text-[10px] text-[#5c5c55]">At least 10 characters.</p>}
          </div>

          {error && <p role="alert" className="text-xs text-rose-500">{error}</p>}
          {notice && <p role="status" className="text-xs text-[#10b981] break-all">{notice}</p>}

          <button type="submit" disabled={busy}
            className="flex items-center justify-center gap-1.5 py-2.5 rounded-lg text-white text-[13px] font-medium hover:opacity-90 disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}>
            {busy && <Loader2 size={14} className="animate-spin" />}
            {inviteToken ? 'Set password & sign in' : signingUp ? 'Create my account' : 'Sign in'}
          </button>

          {!inviteToken && (
            <button type="button"
              onClick={() => { setMode(signingUp ? 'signin' : 'signup'); setError(''); setNotice(''); }}
              className="text-[12px] text-[#8a8a83] hover:text-[#e8c34a] transition-colors">
              {signingUp
                ? 'Already have an account? Sign in'
                : "New here? Create an account — you don't need an invite"}
            </button>
          )}
        </form>
      </div>
    );
  }

  // --- portal ---------------------------------------------------------------
  return (
    <div className="min-h-screen" style={{ background: '#0a0a0a' }}>
      <header className="flex items-center gap-3 px-6 h-[52px]"
        style={{ borderBottom: '1px solid #242424' }}>
        <span className="text-[#f7f5ef] font-semibold text-[14px]">The Exodus · Talent</span>
        <span className="ml-auto flex items-center gap-3">
          <span className="flex items-center gap-1 text-[12px] text-[#e8c34a]">
            <Coins size={12} /> {me.tokens?.total ?? 0}
          </span>
          <button onClick={logout} aria-label="Sign out"
            className="text-[#8a8a83] hover:text-rose-500 transition-colors"><LogOut size={14} /></button>
        </span>
      </header>

      <nav className="flex gap-1 px-6 py-3 overflow-x-auto" style={{ borderBottom: '1px solid #242424' }}>
        {TABS.map(t => (
          <button key={t.key} onClick={() => { setTab(t.key); setNotice(''); setError(''); }}
            aria-current={tab === t.key ? 'page' : undefined}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] whitespace-nowrap transition-colors ${
              tab === t.key ? 'bg-[#c9971f]/15 text-[#e8c34a]' : 'text-[#8a8a83] hover:text-[#d6d4c9]'}`}>
            <t.icon size={12} /> {t.label}
          </button>
        ))}
      </nav>

      <main className="px-6 py-6 max-w-3xl">
        {error && <p role="alert" className="text-sm text-rose-500 mb-4">{error}</p>}
        {notice && <p className="text-sm text-[#10b981] mb-4" aria-live="polite">{notice}</p>}

        {tab === 'dashboard' && (
          <div className="flex flex-col gap-4">
            <Card>
              <p className="text-[13px] text-[#8a8a83]">Hello {me.name}</p>
              <div className="flex items-baseline gap-3 mt-1 flex-wrap">
                <span className="text-[32px] font-semibold text-[#e8c34a]">{me.tokens?.total ?? 0}</span>
                <span className="text-[12px] text-[#8a8a83]">
                  tokens · {me.tokens?.ledger ?? 0} from history + {me.tokens?.idle ?? 0} from
                  {' '}{me.tokens?.idle_days ?? 0} days since your last job
                </span>
              </div>
              {me.next_best_action && (
                <p className="mt-3 text-[12px] text-[#10b981]">Best next step: {me.next_best_action.text}</p>
              )}
            </Card>

            <Card>
              <p className="text-[14px] font-semibold text-[#f2f0e8] mb-3">Your token history</p>
              <div className="flex flex-col divide-y" style={{ borderColor: '#191919' }}>
                {ledger.map(row => (
                  <div key={row.id} className="flex items-center gap-3 py-2">
                    <span className={`font-mono text-[12px] w-10 ${row.delta > 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'}`}>
                      {row.delta > 0 ? '+' : ''}{row.delta}
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="block text-[12px] text-[#d6d4c9]">{row.reason.replace(/_/g, ' ')}</span>
                      {row.note && <span className="block text-[10px] text-[#5c5c55]">{row.note}</span>}
                    </span>
                    <span className="font-mono text-[11px] text-[#5c5c55]">= {row.running_balance}</span>
                  </div>
                ))}
                {ledger.length === 0 && <p className="text-[12px] text-[#5c5c55] py-2">Nothing yet.</p>}
              </div>
            </Card>
          </div>
        )}

        {tab === 'offers' && (
          <div className="flex flex-col gap-3">
            {offers.map(o => (
              <Card key={o.id}>
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <p className="text-[14px] text-[#f2f0e8]">{o.role}</p>
                    <p className="text-[11px] text-[#8a8a83]">
                      {o.rate_kes ? `KES ${o.rate_kes.toLocaleString()}/day` : 'Rate to be confirmed'}
                      {o.start_at ? ` · from ${new Date(o.start_at).toLocaleDateString()}` : ''}
                    </p>
                    {o.expires_at && o.status === 'offered' && (
                      <p className="text-[10px] text-[#f59e0b] mt-0.5">
                        Respond by {new Date(o.expires_at).toLocaleString()}
                      </p>
                    )}
                  </div>
                  {o.status === 'offered' ? (
                    <div className="flex gap-2">
                      <button onClick={() => respond(o.id, 'accept')}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] text-white"
                        style={{ background: '#10b981' }}><Check size={12} /> Accept</button>
                      <button onClick={() => respond(o.id, 'decline')}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] text-[#a3a39c]"
                        style={{ border: '1px solid #333' }}><X size={12} /> Decline</button>
                    </div>
                  ) : (
                    <span className="text-[10px] font-mono text-[#5c5c55]">{o.status.toUpperCase()}</span>
                  )}
                </div>
                {o.status === 'offered' && (
                  <p className="text-[10px] text-[#5c5c55] mt-2">
                    Declining costs you nothing. Only accept what you can genuinely do.
                  </p>
                )}
              </Card>
            ))}
            {offers.length === 0 && <p className="text-[13px] text-[#8a8a83]">No offers right now.</p>}
          </div>
        )}

        {tab === 'certifications' && (
          <div className="flex flex-col gap-3">
            {quiz ? (
              <Card>
                <p className="text-[14px] font-semibold text-[#f2f0e8] mb-3">Assessment</p>
                <div className="flex flex-col gap-4">
                  {(quiz.questions || []).map((q, i) => (
                    <fieldset key={i}>
                      <legend className="text-[12px] text-[#d6d4c9] mb-1.5">{i + 1}. {q.q}</legend>
                      <div className="flex flex-col gap-1">
                        {(q.options || []).map((opt, j) => (
                          <label key={j} className="flex items-start gap-2 text-[12px] text-[#a3a39c] cursor-pointer">
                            <input type="radio" name={`q${i}`} checked={answers[i] === j}
                              onChange={() => setAnswers(a => ({ ...a, [i]: j }))}
                              className="mt-0.5 accent-[#c9971f]" />
                            {opt}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  ))}
                </div>
                <div className="flex gap-2 mt-4">
                  <button onClick={submitQuiz}
                    className="px-3.5 py-2 rounded-lg text-white text-[12px]"
                    style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}>Submit</button>
                  <button onClick={() => setQuiz(null)}
                    className="px-3 py-2 rounded-lg text-[12px] text-[#a3a39c]"
                    style={{ border: '1px solid #333' }}>Cancel</button>
                </div>
              </Card>
            ) : certs.map(c => (
              <Card key={c.key}>
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <p className="text-[14px] text-[#f2f0e8]">{c.name}</p>
                    <p className="text-[11px] text-[#8a8a83]">
                      {c.provider} · {c.category} · +{c.token_award} tokens
                    </p>
                    {c.enrollment?.status === 'completed' && (
                      <p className="text-[10px] text-[#10b981] mt-0.5">
                        Passed{c.enrollment.expires_at ? ` · valid to ${new Date(c.enrollment.expires_at).toLocaleDateString()}` : ''}
                      </p>
                    )}
                    {c.enrollment?.status === 'expired' && (
                      <p className="text-[10px] text-[#f59e0b] mt-0.5">Expired — retake to reinstate.</p>
                    )}
                  </div>
                  {c.enrollment?.status !== 'completed' && (
                    <button onClick={() => startQuiz(c.key)}
                      className="px-3 py-1.5 rounded-lg text-[12px] text-[#e8c34a]"
                      style={{ border: '1px solid rgba(201,151,31,0.35)' }}>
                      {c.enrollment ? 'Retake' : 'Start'}
                    </button>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}

        {tab === 'events' && (
          <div className="flex flex-col gap-3">
            <Card>
              <p className="text-[14px] font-semibold text-[#f2f0e8] mb-2">Check in</p>
              <div className="flex gap-2">
                <label htmlFor="tp-code" className="sr-only">Event check-in code</label>
                <input id="tp-code" value={code} onChange={e => setCode(e.target.value)}
                  placeholder="Enter the code from the event"
                  className="flex-1 rounded-lg px-3 py-2 text-[12px] text-[#d6d4c9] bg-[#0e0e0e]"
                  style={{ border: '1px solid #262626' }} />
                <button onClick={checkin} className="px-3.5 py-2 rounded-lg text-white text-[12px]"
                  style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}>Claim</button>
              </div>
            </Card>
            {events.map(e => (
              <Card key={e.id}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[13px] text-[#f2f0e8]">{e.name}</p>
                    <p className="text-[11px] text-[#8a8a83]">
                      {e.starts_at ? new Date(e.starts_at).toLocaleDateString() : ''} · {e.location} · +{e.token_award}
                    </p>
                  </div>
                  {e.attended && <span className="text-[10px] font-mono text-[#10b981]">ATTENDED</span>}
                </div>
              </Card>
            ))}
          </div>
        )}

        {tab === 'availability' && (
          <div className="flex flex-col gap-3">
            <Card>
              <p className="text-[13px] text-[#a3a39c]">
                You are considered available unless you say otherwise. Mark the dates you
                <em> cannot</em> work — that is what keeps you out of a booking you would have to turn down.
              </p>
            </Card>
            {blocks.map(b => (
              <Card key={b.id}>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-[12px] text-[#d6d4c9]">
                      {new Date(b.start_at).toLocaleDateString()} – {new Date(b.end_at).toLocaleDateString()}
                    </p>
                    <p className="text-[10px] font-mono text-[#5c5c55]">
                      {b.kind.toUpperCase()} · {b.source}{b.note ? ` · ${b.note}` : ''}
                    </p>
                  </div>
                  {b.source !== 'assignment' && (
                    <button
                      onClick={async () => {
                        await fetch(`${API}/talent/availability/${b.id}`, { method: 'DELETE', credentials: 'include' });
                        loadTab();
                      }}
                      className="text-[11px] text-[#a3a39c] hover:text-rose-500">Remove</button>
                  )}
                </div>
              </Card>
            ))}
            {blocks.length === 0 && <p className="text-[13px] text-[#8a8a83]">No blocked dates — you are fully available.</p>}
          </div>
        )}

        {tab === 'picked' && <HowIGetPicked policies={policies} />}
      </main>
    </div>
  );
}
