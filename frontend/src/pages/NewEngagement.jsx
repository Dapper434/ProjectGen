import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function NewEngagement() {
  const [companyName, setCompanyName] = useState('');
  const [companyIndustry, setCompanyIndustry] = useState('');
  const [companyNotes, setCompanyNotes] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!companyName.trim()) {
      setError('Enter a company name to create an engagement.');
      return;
    }

    try {
      setIsSubmitting(true);
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
      setIsSubmitting(false);
    }
  };

  return (
    <div className="p-8 max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-white tracking-tight">New Engagement</h1>
        <p className="text-zinc-400 mt-1">Create the company record and its first engagement.</p>
      </div>

      <form onSubmit={handleSubmit} className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 space-y-5">
        <div className="space-y-2">
          <label htmlFor="company-name" className="block text-sm font-medium text-zinc-200">Company name</label>
          <input id="company-name" autoFocus value={companyName} onChange={(event) => setCompanyName(event.target.value)} className="w-full bg-zinc-950 border border-zinc-700 text-white px-3 py-2 rounded-md text-sm focus:outline-none focus:border-indigo-500" placeholder="e.g. Acme Ltd" />
        </div>
        <div className="space-y-2">
          <label htmlFor="company-industry" className="block text-sm font-medium text-zinc-200">Industry <span className="text-zinc-500">(optional)</span></label>
          <input id="company-industry" value={companyIndustry} onChange={(event) => setCompanyIndustry(event.target.value)} className="w-full bg-zinc-950 border border-zinc-700 text-white px-3 py-2 rounded-md text-sm focus:outline-none focus:border-indigo-500" placeholder="e.g. Financial services" />
        </div>
        <div className="space-y-2">
          <label htmlFor="company-notes" className="block text-sm font-medium text-zinc-200">Notes <span className="text-zinc-500">(optional)</span></label>
          <textarea id="company-notes" value={companyNotes} onChange={(event) => setCompanyNotes(event.target.value)} className="w-full min-h-28 bg-zinc-950 border border-zinc-700 text-white px-3 py-2 rounded-md text-sm focus:outline-none focus:border-indigo-500 resize-y" placeholder="Anything the team should know about this company" />
        </div>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={() => navigate('/engagements')} className="text-sm text-zinc-300 hover:text-white px-4 py-2">Cancel</button>
          <button type="submit" disabled={isSubmitting} className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-4 py-2 rounded-md font-medium text-sm transition-colors">{isSubmitting ? 'Creating...' : 'Create engagement'}</button>
        </div>
      </form>
    </div>
  );
}
