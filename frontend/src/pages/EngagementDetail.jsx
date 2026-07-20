import { useEffect, useState } from 'react';
import { useParams, useOutletContext } from 'react-router-dom';
import { UploadCloud, FileText, CheckCircle, Clock } from 'lucide-react';

export default function EngagementDetail() {
  const { id } = useParams();
  const { user } = useOutletContext();
  const [engagement, setEngagement] = useState(null);
  const [transcriptText, setTranscriptText] = useState('');
  const [isUploading, setIsUploading] = useState(false);

  useEffect(() => {
    fetchEngagement();
  }, [id]);

  const fetchEngagement = async () => {
    try {
      const res = await fetch(`http://localhost:5000/api/engagements/${id}`, { credentials: 'include' });
      const data = await res.json();
      setEngagement(data);
    } catch (err) {
      console.error(err);
    }
  };

  const handleUpload = async () => {
    if (!transcriptText.trim()) return;
    setIsUploading(true);
    try {
      const res = await fetch(`http://localhost:5000/api/engagements/${id}/transcripts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_text: transcriptText }),
        credentials: 'include'
      });
      if (res.ok) {
        setTranscriptText('');
        await fetchEngagement(); // Refresh to see brief/proposal
      }
    } catch (err) {
      console.error(err);
    }
    setIsUploading(false);
  };

  const handleReview = async (action) => {
    setIsUploading(true);
    try {
      const notes = prompt("Any notes for the agent? (Leave blank to just proceed)");
      if (action === 'send_back' && !notes) {
         alert("Notes are required to send back.");
         setIsUploading(false);
         return;
      }
      const res = await fetch(`http://localhost:5000/api/engagements/${id}/proposals/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, notes: notes || '' }),
        credentials: 'include'
      });
      if (res.ok) {
        await fetchEngagement();
      } else {
        const err = await res.json();
        alert(err.error || 'Review failed');
      }
    } catch (err) {
      console.error(err);
    }
    setIsUploading(false);
  };

  if (!engagement) return <div className="p-8 text-zinc-400">Loading...</div>;

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-2xl font-semibold text-white tracking-tight">{engagement.client_name}</h1>
          <span className="px-2.5 py-1 rounded-full text-[10px] font-medium tracking-wide uppercase bg-zinc-800 text-zinc-300">
            {engagement.status.replace(/_/g, ' ')}
          </span>
        </div>
        <p className="text-zinc-400">Engagement #{id.toString().padStart(4, '0')}</p>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Left Column: Actions / Status */}
        <div className="lg:col-span-1 space-y-6">
          {(engagement.status === 'awaiting_transcript' || engagement.status === 'awaiting_review_transcript') && (
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
              <h2 className="text-sm font-medium text-white mb-3 flex items-center gap-2">
                <UploadCloud size={16} className="text-indigo-400" />
                Upload {engagement.status === 'awaiting_transcript' ? 'Client Meeting' : 'Brief Review'} Transcript
              </h2>
              <textarea 
                className="w-full h-32 bg-zinc-950 border border-zinc-800 rounded-md p-3 text-sm text-zinc-300 focus:outline-none focus:border-indigo-500 transition-colors mb-3 resize-none"
                placeholder="Paste transcript here..."
                value={transcriptText}
                onChange={(e) => setTranscriptText(e.target.value)}
              />
              <button 
                onClick={handleUpload}
                disabled={isUploading}
                className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white py-2 rounded-md font-medium text-sm transition-colors"
              >
                {isUploading ? 'Agent Processing...' : 'Generate Document'}
              </button>
            </div>
          )}

          {/* Activity Log */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
            <h2 className="text-sm font-medium text-white mb-4 flex items-center gap-2">
              <Clock size={16} className="text-zinc-400" />
              Activity Log
            </h2>
            <div className="space-y-4">
              {engagement.events && engagement.events.map((ev, idx) => (
                <div key={idx} className="relative pl-4 border-l border-zinc-800">
                  <div className="absolute w-2 h-2 bg-indigo-500 rounded-full -left-[4.5px] top-1.5" />
                  <p className="text-xs font-medium text-indigo-400">{ev.agent}</p>
                  <p className="text-xs text-zinc-400 mt-1">{ev.reasoning_summary}</p>
                </div>
              ))}
              {(!engagement.events || engagement.events.length === 0) && (
                <p className="text-xs text-zinc-500">No activity yet.</p>
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Documents */}
        <div className="lg:col-span-2 space-y-6">
          
          {engagement.brief && (
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
              <div className="flex items-center justify-between mb-6 pb-4 border-b border-zinc-800">
                <h2 className="text-lg font-medium text-white flex items-center gap-2">
                  <FileText size={18} className="text-blue-400" />
                  Production Brief
                </h2>
                <button className="text-sm text-zinc-400 hover:text-white">Download PDF</button>
              </div>
              <div className="prose prose-invert prose-sm max-w-none text-zinc-300">
                <pre className="whitespace-pre-wrap font-sans bg-transparent p-0">{engagement.brief.rendered_markdown}</pre>
              </div>
            </div>
          )}

          {engagement.proposal && (
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
              <div className="flex items-center justify-between mb-6 pb-4 border-b border-zinc-800">
                <h2 className="text-lg font-medium text-white flex items-center gap-2">
                  <FileText size={18} className="text-emerald-400" />
                  Client Proposal {engagement.proposal.status === 'approved' && <span className="text-xs bg-emerald-500/20 text-emerald-400 px-2 py-1 rounded">Approved</span>}
                </h2>
                <div className="flex items-center gap-3">
                  <button className="text-sm text-zinc-400 hover:text-white">Download PDF</button>
                  {user?.role === 'Account Manager' && engagement.proposal.status !== 'approved' && (
                    <div className="flex items-center gap-2 border-l border-zinc-700 pl-3">
                      <button 
                        onClick={() => handleReview('send_back')}
                        disabled={isUploading}
                        className="text-sm px-3 py-1.5 rounded bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
                      >
                        Send Back
                      </button>
                      <button 
                        onClick={() => handleReview('approve')}
                        disabled={isUploading}
                        className="text-sm px-3 py-1.5 rounded bg-emerald-600 text-white hover:bg-emerald-500 transition-colors"
                      >
                        Approve
                      </button>
                    </div>
                  )}
                </div>
              </div>
              <div className="prose prose-invert prose-sm max-w-none text-zinc-300">
                <pre className="whitespace-pre-wrap font-sans bg-transparent p-0 mb-6">{engagement.proposal.rendered_markdown}</pre>
                
                <h3 className="text-white font-medium mb-3">Pricing Structure</h3>
                <div className="overflow-x-auto rounded-lg border border-zinc-800">
                  <table className="w-full text-sm text-left">
                    <thead className="bg-zinc-950 text-zinc-400">
                      <tr>
                        <th className="px-4 py-3 font-medium">Category</th>
                        <th className="px-4 py-3 font-medium">Description</th>
                        <th className="px-4 py-3 font-medium text-right">Rate (KES)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800">
                      {engagement.proposal.pricing_line_items.map((item, i) => (
                        <tr key={i} className="bg-zinc-900/50">
                          <td className="px-4 py-3">{item.category}</td>
                          <td className="px-4 py-3">{item.description}</td>
                          <td className="px-4 py-3 text-right font-medium">{item.rate_kes.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {!engagement.brief && !engagement.proposal && (
            <div className="h-64 border border-dashed border-zinc-800 rounded-xl flex items-center justify-center text-zinc-500 text-sm">
              No documents generated yet. Upload a transcript to begin.
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
