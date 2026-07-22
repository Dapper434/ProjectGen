import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Zap, ArrowRight, FileText, CheckCircle2 } from 'lucide-react';

const pipeline = [
  { label: 'Transcript Upload', icon: FileText, color: '#c9971f' },
  { label: 'Brief Generation', icon: Zap, color: '#0ea5e9' },
  { label: 'Proposal Draft', icon: FileText, color: '#f59e0b' },
  { label: 'AM Approval', icon: CheckCircle2, color: '#10b981' },
];

// Seeded demo users (backend seed.py); role comes from the user record on login.
const demoAccounts = [
  { username: 'producer', password: 'demo', label: 'Producer' },
  { username: 'am', password: 'demo', label: 'Account Manager' },
  { username: 'admin', password: 'demo', label: 'Admin' },
];

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
        credentials: 'include',
      });
      if (res.ok) {
        navigate('/dashboard');
        return;
      }
      setError('Incorrect username or password. Please try again.');
    } catch (err) {
      setError('Connection failed. Is the backend running?');
    }
    setLoading(false);
  };

  const fill = (account) => {
    setUsername(account.username);
    setPassword(account.password);
    setError('');
  };

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex">
      {/* Left brand panel */}
      <div className="hidden lg:flex w-[520px] shrink-0 flex-col relative overflow-hidden bg-[#0e0e0e] border-r border-[#262626]">
        {/* Grid pattern */}
        <div
          className="absolute inset-0 opacity-30"
          style={{
            backgroundImage: `linear-gradient(#e2e8f0 1px, transparent 1px), linear-gradient(90deg, #e2e8f0 1px, transparent 1px)`,
            backgroundSize: '40px 40px',
          }}
        />
        {/* Gold glow */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[400px] h-[400px] rounded-full bg-[#c9971f]/10 blur-[80px] pointer-events-none" />

        <div className="relative z-10 flex flex-col h-full px-12 py-10">
          {/* Logo */}
          <div className="flex items-center gap-3 mb-auto">
            <div className="w-9 h-9 rounded-lg bg-[#c9971f] flex items-center justify-center">
              <Zap size={18} className="text-white" fill="white" />
            </div>
            <div>
              <span className="font-serif text-[#f7f5ef] text-xl tracking-tight">The Exodus</span>
              <p className="text-[10px] font-mono text-[#6e6e67] uppercase tracking-widest">by GDF Kenya</p>
            </div>
          </div>

          {/* Hero copy */}
          <div className="mb-10">
            <h1 className="font-serif text-[#f7f5ef] text-4xl leading-[1.1] mb-4">
              Turning conversations<br />
              into <span className="text-[#e8c34a]">change.</span>
            </h1>
            <p className="text-[#a3a39c] text-sm leading-relaxed max-w-xs">
              Upload a meeting transcript. In seconds, The Exodus produces structured briefs and client proposals — ready for human review.
            </p>
          </div>

          {/* Pipeline steps */}
          <div className="mb-10">
            <p className="text-[10px] font-mono text-[#6e6e67] uppercase tracking-widest mb-4">Pipeline</p>
            <div className="flex flex-col gap-3">
              {pipeline.map(({ label, icon: Icon, color }, i) => (
                <div key={i} className="flex items-center gap-3">
                  <div
                    className="w-7 h-7 rounded-md flex items-center justify-center shrink-0"
                    style={{ background: color + '22', border: `1px solid ${color}44` }}
                  >
                    <Icon size={13} style={{ color }} />
                  </div>
                  <span className="text-sm text-[#a3a39c]">{label}</span>
                  {i < pipeline.length - 1 && (
                    <div className="ml-auto w-4 h-px bg-[#262626]" />
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Client logos row */}
          <div className="border-t border-[#262626] pt-6">
            <p className="text-[10px] font-mono text-[#6e6e67] uppercase tracking-widest mb-3">Active clients</p>
            <div className="flex gap-3">
              {['KCB', 'Safaricom', 'NCBA', 'Equity'].map(c => (
                <div key={c} className="px-3 py-1.5 rounded border border-[#262626] bg-[#1a1a1a]">
                  <span className="text-[11px] font-mono text-[#6e6e67]">{c}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Right auth panel */}
      <div className="flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-sm">
          {/* Mobile logo */}
          <div className="lg:hidden flex items-center gap-2 mb-8">
            <div className="w-8 h-8 rounded-lg bg-[#c9971f] flex items-center justify-center">
              <Zap size={15} className="text-white" fill="white" />
            </div>
            <span className="font-serif text-[#f7f5ef] text-lg">The Exodus</span>
          </div>

          <div className="mb-8">
            <h2 className="text-[#f7f5ef] text-2xl font-semibold mb-1">Sign in</h2>
            <p className="text-sm text-[#a3a39c]">Access your agency workspace</p>
          </div>

          <form onSubmit={handleLogin} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs text-[#a3a39c] mb-1.5">Username</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="Enter your username"
                className="w-full bg-[#141414] border border-[#262626] rounded-lg px-3 py-2.5 text-sm text-[#f7f5ef] placeholder:text-[#6e6e67] focus:outline-none focus:border-[#c9971f]/60 transition-colors"
              />
            </div>
            <div>
              <label className="block text-xs text-[#a3a39c] mb-1.5">Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-[#141414] border border-[#262626] rounded-lg px-3 py-2.5 text-sm text-[#f7f5ef] placeholder:text-[#6e6e67] focus:outline-none focus:border-[#c9971f]/60 transition-colors"
              />
            </div>

            {error && <p role="alert" className="text-xs text-rose-500">{error}</p>}

            <div className="flex items-center gap-3">
              {demoAccounts.map(account => (
                <button
                  key={account.username}
                  type="button"
                  onClick={() => fill(account)}
                  className="text-xs text-[#c9971f] hover:text-[#e8c34a] text-left transition-colors"
                >
                  Demo: {account.label} →
                </button>
              ))}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="flex items-center justify-center gap-2 w-full py-2.5 rounded-lg bg-[#c9971f] hover:bg-[#a67a17] text-white text-sm font-medium transition-all disabled:opacity-60"
            >
              {loading ? (
                <span className="flex items-center gap-2">
                  <span className="w-3.5 h-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  Authenticating…
                </span>
              ) : (
                <>Sign in <ArrowRight size={14} /></>
              )}
            </button>
          </form>

          <p className="mt-6 text-center text-xs text-[#6e6e67]">
            Protected workspace — GDF Kenya internal use only
          </p>
        </div>
      </div>
    </div>
  );
}
