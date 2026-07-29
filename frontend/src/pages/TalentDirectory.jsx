import { useCallback, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Users, Coins, MapPin, Mail, Loader2 } from 'lucide-react';

const API = '/api';

function TokenBadge({ tokens }) {
  if (!tokens) return null;
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded"
      style={{ color: '#e8c34a', background: 'rgba(201,151,31,0.12)' }}
      title={`${tokens.ledger} earned/spent + ${tokens.idle} idle (${tokens.idle_days} days since last job)`}>
      <Coins size={9} /> {tokens.total}
    </span>
  );
}

export default function TalentDirectory() {
  const { user } = useOutletContext();
  const canEdit = user?.role === 'Account Manager' || user?.role === 'Admin';
  const [talents, setTalents] = useState([]);
  const [engagementType, setEngagementType] = useState('');
  const [discipline, setDiscipline] = useState('');
  const [error, setError] = useState('');
  const [inviting, setInviting] = useState(null);
  const [notice, setNotice] = useState('');

  const fetchTalents = useCallback(async () => {
    const params = new URLSearchParams();
    if (engagementType) params.set('engagement_type', engagementType);
    if (discipline) params.set('discipline', discipline);
    try {
      const res = await fetch(`${API}/talent?${params}`, { credentials: 'include' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError(err.error || 'Could not load the bench.');
        return;
      }
      setTalents(await res.json());
    } catch {
      setError('Connection failed. Is the backend running?');
    }
  }, [engagementType, discipline]);

  useEffect(() => { fetchTalents(); }, [fetchTalents]);

  async function invite(t) {
    setInviting(t.id); setNotice('');
    try {
      const res = await fetch(`${API}/talent/${t.id}/invite`, { method: 'POST', credentials: 'include' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setError(data.error || 'Could not send the invite.'); return; }
      setNotice(data.link
        ? `Invite printed to the server log (console driver). Link: ${data.link}`
        : `Invite sent to ${t.email} via ${data.driver}.`);
    } finally { setInviting(null); }
  }

  return (
    <div className="px-8 py-7">
      <div className="flex items-center gap-2.5 mb-1.5">
        <Users size={18} className="text-[#c9971f]" />
        <h1 className="font-serif text-[#f7f5ef] text-2xl">Talent Bench</h1>
      </div>
      <p className="text-sm text-[#8a8a83] mb-6 max-w-2xl">
        Everyone available to crew a production. Token balances combine earned history with idle
        accrual, so people who have not worked recently rise up the casting queue. Talent can join
        the bench themselves at <span className="font-mono text-[#a3a39c]">/talent/join</span> —
        those profiles are marked self-registered until someone here has worked with them.
      </p>

      {error && <p role="alert" className="text-sm text-rose-500 mb-4">{error}</p>}
      {notice && <p className="text-xs text-[#10b981] mb-4 break-all">{notice}</p>}

      <div className="flex gap-3 mb-5 flex-wrap">
        <div className="flex flex-col gap-1">
          <label htmlFor="td-type" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">TYPE</label>
          <select id="td-type" value={engagementType} onChange={e => setEngagementType(e.target.value)}
            className="rounded-lg px-3 py-1.5 text-[12px] text-[#d6d4c9] bg-[#0e0e0e]"
            style={{ border: '1px solid #262626' }}>
            <option value="">All</option>
            <option value="inhouse">In-house</option>
            <option value="contract">Contract</option>
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="td-disc" className="text-[10px] font-mono tracking-wider text-[#8a8a83]">DISCIPLINE</label>
          <input id="td-disc" value={discipline} onChange={e => setDiscipline(e.target.value)}
            placeholder="e.g. Editor"
            className="rounded-lg px-3 py-1.5 text-[12px] text-[#d6d4c9] bg-[#0e0e0e]"
            style={{ border: '1px solid #262626' }} />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {talents.map(t => (
          <div key={t.id} className="rounded-xl p-4 flex flex-col gap-2"
            style={{ background: '#141414', border: '1px solid #242424' }}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-[14px] font-medium text-[#f2f0e8] truncate">{t.name}</p>
                <p className="text-[11px] text-[#8a8a83]">{t.title || 'Unspecified'}</p>
              </div>
              <TokenBadge tokens={t.tokens} />
            </div>

            <div className="flex items-center gap-2 flex-wrap text-[10px] font-mono text-[#5c5c55]">
              <span className="px-1.5 py-0.5 rounded"
                style={t.engagement_type === 'inhouse'
                  ? { color: '#a78bfa', background: 'rgba(167,139,250,0.12)' }
                  : { color: '#8a8a83', background: '#1a1a1a' }}>
                {(t.engagement_type || 'contract').toUpperCase()}
              </span>
              {t.seniority && <span>{t.seniority.toUpperCase()}</span>}
              {t.day_rate_kes ? <span>KES {t.day_rate_kes.toLocaleString()}/day</span> : null}
              {t.avg_rating ? <span>★ {t.avg_rating}</span> : null}
              {t.signup_source === 'self' && (
                <span className="px-1.5 py-0.5 rounded"
                  title="Registered themselves through the talent portal — nobody at GDF has vetted this profile yet"
                  style={{ color: '#38bdf8', background: 'rgba(56,189,248,0.12)' }}>
                  SELF-REGISTERED
                </span>
              )}
            </div>

            {t.location && (
              <p className="flex items-center gap-1 text-[10px] text-[#5c5c55]">
                <MapPin size={9} /> {t.location}
              </p>
            )}
            {t.highlight && <p className="text-[11px] text-[#a3a39c]">{t.highlight}</p>}

            <div className="flex flex-wrap gap-1 mt-auto pt-1">
              {(t.skills || []).slice(0, 4).map((s, i) => (
                <span key={i} className="text-[9px] px-1.5 py-0.5 rounded text-[#8a8a83]"
                  style={{ background: '#1a1a1a', border: '1px solid #262626' }}>{s}</span>
              ))}
            </div>

            {/* Only worth offering to people who have not set a password yet —
                anyone else already has portal access, however they got it. */}
            {canEdit && t.email && !t.has_portal_login && (
              <button onClick={() => invite(t)} disabled={inviting === t.id}
                className="mt-1 flex items-center gap-1 text-[11px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors disabled:opacity-50">
                {inviting === t.id ? <Loader2 size={10} className="animate-spin" /> : <Mail size={10} />}
                {inviting === t.id ? 'Sending…' : 'Email a portal set-up link'}
              </button>
            )}
            {t.has_portal_login && (
              <p className="mt-1 flex items-center gap-1 text-[11px] text-[#5c5c55]">
                <Mail size={10} /> Portal access active
              </p>
            )}
          </div>
        ))}
      </div>
      {talents.length === 0 && !error && (
        <p className="text-[13px] text-[#8a8a83]">No talent matches those filters.</p>
      )}
    </div>
  );
}
