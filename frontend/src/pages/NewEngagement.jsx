import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight, ArrowRight, Zap } from 'lucide-react';

function TextInput({ label, placeholder, value, onChange, optional = false, autoFocus = false }) {
  return (
    <div>
      <label className="block text-xs text-[#a3a39c] mb-1.5">
        {label} {optional && <span className="text-[#6e6e67]">(optional)</span>}
      </label>
      <input
        type="text"
        value={value}
        autoFocus={autoFocus}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-[#141414] border border-[#262626] rounded-lg px-3 py-2.5 text-sm text-[#f7f5ef] placeholder:text-[#6e6e67] focus:outline-none focus:border-[#c9971f]/60 transition-colors"
      />
    </div>
  );
}

export default function NewEngagement() {
  const navigate = useNavigate();
  const [companyName, setCompanyName] = useState('');
  const [companyIndustry, setCompanyIndustry] = useState('');
  const [companyNotes, setCompanyNotes] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const handleCreate = async (event) => {
    event.preventDefault();
    if (!companyName.trim()) {
      setError('Enter a company name to create an engagement.');
      return;
    }

    try {
      setSaving(true);
      setError('');
      const clientResponse = await fetch('http://localhost:5000/api/clients', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: companyName.trim(),
          industry: companyIndustry.trim(),
          notes: companyNotes.trim(),
        }),
      });
      const client = await clientResponse.json().catch(() => ({}));
      if (!clientResponse.ok) {
        setError(client.error || 'Unable to create company. Restart the backend if it was already running.');
        return;
      }

      const engagementResponse = await fetch('http://localhost:5000/api/engagements', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: client.id }),
      });
      const engagement = await engagementResponse.json().catch(() => ({}));
      if (!engagementResponse.ok) {
        setError(engagement.error || 'Company created, but the engagement could not be created.');
        return;
      }

      navigate(`/engagements/${engagement.id}`);
    } catch (requestError) {
      console.error(requestError);
      setError('Unable to create the company and engagement. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const isValid = companyName.trim().length > 0;

  return (
    <div className="max-w-2xl mx-auto px-8 py-8">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-xs text-[#6e6e67] mb-7">
        <button onClick={() => navigate('/dashboard')} className="hover:text-[#a3a39c] transition-colors">Dashboard</button>
        <ChevronRight size={12} />
        <span className="text-[#f7f5ef]">New Engagement</span>
      </div>

      {/* Header */}
      <div className="mb-8">
        <h1 className="font-serif text-[#f7f5ef] text-2xl mb-1">New Engagement</h1>
        <p className="text-sm text-[#a3a39c]">Set up a new client engagement. Transcripts and documents will be added from the engagement view.</p>
      </div>

      <form onSubmit={handleCreate} className="flex flex-col gap-6">
        {/* Client details */}
        <div className="bg-[#141414] border border-[#262626] rounded-xl p-5">
          <p className="text-xs font-mono text-[#6e6e67] uppercase tracking-widest mb-4">Engagement Details</p>
          <div className="flex flex-col gap-4">
            <TextInput label="Client Name" placeholder="e.g. KCB Bank Group" value={companyName} onChange={setCompanyName} autoFocus />
            <TextInput label="Industry" placeholder="e.g. Financial services" value={companyIndustry} onChange={setCompanyIndustry} optional />
            <div>
              <label className="block text-xs text-[#a3a39c] mb-1.5">Notes <span className="text-[#6e6e67]">(optional)</span></label>
              <textarea
                value={companyNotes}
                onChange={e => setCompanyNotes(e.target.value)}
                rows={3}
                placeholder="Anything the team should know about this company…"
                className="w-full bg-[#1a1a1a] border border-[#262626] rounded-lg px-3 py-2.5 text-sm text-[#f7f5ef] placeholder:text-[#6e6e67] focus:outline-none focus:border-[#c9971f]/60 resize-none transition-colors"
              />
            </div>
          </div>
        </div>

        {/* FactoryOS info banner */}
        <div className="flex items-start gap-3 p-4 rounded-xl bg-[#c9971f]/10 border border-[#c9971f]/20">
          <div className="w-7 h-7 rounded-lg bg-[#c9971f]/20 flex items-center justify-center shrink-0 mt-0.5">
            <Zap size={13} className="text-[#e8c34a]" />
          </div>
          <div>
            <p className="text-xs font-semibold text-[#e8c34a] mb-1">FactoryOS will stand by</p>
            <p className="text-xs text-[#a3a39c] leading-relaxed">
              Once created, the Producer uploads the first meeting transcript to generate a Production Brief. After a brief review meeting, the second transcript generates the full Client Proposal — ready for Account Manager approval.
            </p>
          </div>
        </div>

        {error && <p role="alert" className="text-sm text-rose-500">{error}</p>}

        {/* Actions */}
        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={() => navigate('/dashboard')}
            className="px-4 py-2.5 rounded-lg border border-[#262626] text-sm text-[#a3a39c] hover:border-[#333333] hover:text-[#f7f5ef] transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!isValid || saving}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[#c9971f] hover:bg-[#a67a17] text-white text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? (
              <>
                <span className="w-3.5 h-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                Creating…
              </>
            ) : (
              <>
                Create Engagement
                <ArrowRight size={14} />
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
