import { useEffect, useState } from 'react';
import { useParams, useOutletContext } from 'react-router-dom';
import { UploadCloud, FileText, CheckCircle, Clock, Download, Target, Users, Package, Calendar, Wallet, Briefcase, AlertTriangle, HelpCircle, Loader2 } from 'lucide-react';

export default function EngagementDetail() {
  const { id } = useParams();
  const { user } = useOutletContext();
  const [engagement, setEngagement] = useState(null);
  const [transcriptText, setTranscriptText] = useState('');
  const [proposalTranscriptText, setProposalTranscriptText] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [isProposalGenerating, setIsProposalGenerating] = useState(false);

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

  const handleUpload = async (type = 'transcript') => {
    const text = type === 'proposal' ? proposalTranscriptText : transcriptText;
    if (!text.trim()) return;
    
    if (type === 'proposal') setIsProposalGenerating(true);
    else setIsUploading(true);

    try {
      // Both brief and proposal uploads go through the same endpoint;
      // the backend dispatches based on engagement.status
      const endpoint = `http://localhost:5000/api/engagements/${id}/transcripts`;

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_text: text }),
        credentials: 'include'
      });
      if (res.ok) {
        if (type === 'proposal') setProposalTranscriptText('');
        else setTranscriptText('');
        await fetchEngagement();
      }
    } catch (err) {
      console.error(err);
    }
    setIsUploading(false);
    setIsProposalGenerating(false);
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

  const [isDownloading, setIsDownloading] = useState(null); // 'brief' | 'proposal' | null

  const downloadPDF = async (type) => {
    setIsDownloading(type);
    try {
      const endpoint = type === 'brief' ? 'brief/pdf' : 'proposal/pdf';
      const res = await fetch(`http://localhost:5000/api/engagements/${id}/${endpoint}`, {
        credentials: 'include'
      });
      
      if (!res.ok) {
        const err = await res.json();
        alert(err.error || 'Download failed');
        setIsDownloading(null);
        return;
      }
      
      // Get filename from Content-Disposition header or use a default
      const disposition = res.headers.get('Content-Disposition');
      let filename = `${engagement.client_name}_${type === 'brief' ? 'Production_Brief' : 'Client_Proposal'}.pdf`;
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

  if (!engagement) return <div className="p-8 text-zinc-400">Loading...</div>;

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      <div>
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-2xl font-semibold text-white tracking-tight">{engagement.client_name}</h1>
          <span className="px-2.5 py-1 rounded-full text-[10px] font-medium tracking-wide uppercase bg-zinc-800 text-zinc-300">
            {engagement.status.replace(/_/g, ' ')}
          </span>
        </div>
        <p className="text-zinc-400">Engagement #{id.toString().padStart(4, '0')}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-1 space-y-6">
          {/* brief_ready must offer the upload box too — it's how the review transcript
              (Agent 2's input) gets in; the backend accepts it in that state. */}
          {(engagement.status === 'awaiting_transcript' || engagement.status === 'awaiting_review_transcript' || engagement.status === 'brief_ready') && (
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
              <h2 className="text-sm font-medium text-white mb-3 flex items-center gap-2">
                <UploadCloud size={16} className="text-indigo-400" />
                Upload Client Meeting Transcript
              </h2>
              <textarea 
                className="w-full h-32 bg-zinc-950 border border-zinc-800 rounded-md p-3 text-sm text-zinc-300 focus:outline-none focus:border-indigo-500 transition-colors mb-3 resize-none"
                placeholder="Paste transcript here..."
                value={transcriptText}
                onChange={(e) => setTranscriptText(e.target.value)}
              />
              <button 
                onClick={() => handleUpload('transcript')}
                disabled={isUploading}
                className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white py-2 rounded-md font-medium text-sm transition-colors"
              >
                {isUploading ? 'Agent Processing...' : 'Generate Brief'}
              </button>
            </div>
          )}

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

        <div className="lg:col-span-2 space-y-6">
          {engagement.brief && (
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
              <div className="flex items-center justify-between mb-6 pb-4 border-b border-zinc-800">
                <h2 className="text-lg font-medium text-white flex items-center gap-2">
                  <FileText size={18} className="text-blue-400" />
                  Production Brief
                </h2>
                <button
                  onClick={() => downloadPDF('brief')}
                  disabled={isDownloading === 'brief'}
                  className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-indigo-600 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200"
                >
                  <Download size={14} />
                  {isDownloading === 'brief' ? 'Generating PDF...' : 'Download PDF'}
                </button>
              </div>
              <div className="prose prose-invert prose-sm max-w-none text-zinc-300 mb-6">
                <pre className="whitespace-pre-wrap font-sans bg-transparent p-0">{engagement.brief.rendered_markdown}</pre>
              </div>

              {!engagement.proposal && (
                <div className="mt-2 border-t border-zinc-800 pt-6">
                  <div className="flex items-center gap-2 mb-1">
                    <UploadCloud size={15} className="text-emerald-400" />
                    <h3 className="text-sm font-semibold text-white">Create Proposal</h3>
                  </div>
                  <p className="text-xs text-zinc-500 mb-3">
                    Paste the client review meeting transcript below. The AI will read it alongside this brief and hand back a finished, client-ready proposal.
                  </p>
                  <textarea 
                    className="w-full h-44 bg-zinc-950 border border-zinc-700 rounded-md p-3 text-sm text-zinc-300 placeholder-zinc-600 focus:outline-none focus:border-emerald-500 transition-colors mb-3 resize-none"
                    placeholder="Paste the review meeting transcript here…"
                    value={proposalTranscriptText}
                    onChange={(e) => setProposalTranscriptText(e.target.value)}
                    disabled={isProposalGenerating}
                  />
                  {isProposalGenerating ? (
                    <div className="flex items-center gap-3 py-2.5 px-4 bg-zinc-800 rounded-md">
                      <Loader2 size={15} className="animate-spin text-emerald-400 shrink-0" />
                      <span className="text-sm text-zinc-300">Agent is generating your proposal — this may take a moment…</span>
                    </div>
                  ) : (
                    <button 
                      onClick={() => handleUpload('proposal')}
                      disabled={!proposalTranscriptText.trim()}
                      className="flex items-center justify-center gap-2 w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed text-white py-2.5 rounded-md font-semibold text-sm transition-colors"
                    >
                      Create Proposal
                    </button>
                  )}
                </div>
              )}
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
                  <button
                    onClick={() => downloadPDF('proposal')}
                    disabled={isDownloading === 'proposal'}
                    className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-emerald-600 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200"
                  >
                    <Download size={14} />
                    {isDownloading === 'proposal' ? 'Generating PDF...' : 'Download PDF'}
                  </button>
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
              <ProposalReport proposal={engagement.proposal} clientName={engagement.client_name} />
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
