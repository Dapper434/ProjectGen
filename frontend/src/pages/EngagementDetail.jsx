import { useEffect, useState } from 'react';
import { useParams, useOutletContext } from 'react-router-dom';
import { UploadCloud, FileText, CheckCircle, Clock, Download, Target, Users, Package, Calendar, Wallet, Briefcase, AlertTriangle, HelpCircle } from 'lucide-react';

function ReportSection({ icon: Icon, title, children }) {
  return (
    <div>
      <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2.5">
        <Icon size={13} className="text-indigo-500" />
        {title}
      </h3>
      <div className="text-sm text-zinc-700 leading-relaxed">{children}</div>
    </div>
  );
}

function BulletList({ items, tone = 'default' }) {
  if (!items || items.length === 0) return <p className="text-zinc-400 italic">None noted</p>;
  return (
    <ul className="space-y-1.5">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2.5">
          <span className={`mt-1.5 w-1 h-1 rounded-full shrink-0 ${tone === 'warn' ? 'bg-amber-500' : 'bg-indigo-400'}`} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function BriefReport({ brief, clientName }) {
  const data = brief.structured_json || {};
  return (
    <div className="bg-white text-zinc-900 rounded-lg border border-zinc-700/30 overflow-hidden shadow-sm">
      <div className="bg-gradient-to-br from-indigo-600 to-indigo-800 px-8 py-7">
        <p className="text-indigo-200 text-[11px] font-semibold tracking-[0.15em] uppercase mb-1.5">FactoryOS · Production Brief</p>
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <h2 className="text-2xl font-bold text-white">{clientName}</h2>
          {data.work_type && (
            <span className="inline-block bg-white/15 text-white text-xs font-medium px-3 py-1.5 rounded-full capitalize">
              {data.work_type.replace(/-/g, ' ')}
            </span>
          )}
        </div>
      </div>

      <div className="px-8 py-7 space-y-7">
        <ReportSection icon={Target} title="Objectives">
          <BulletList items={data.objectives} />
        </ReportSection>

        <ReportSection icon={Users} title="Audience">
          <p>{data.audience || 'Not specified'}</p>
        </ReportSection>

        <ReportSection icon={Package} title="Deliverables">
          <BulletList items={data.deliverables} />
        </ReportSection>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="bg-zinc-50 border border-zinc-200 rounded-lg p-4">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">
              <Calendar size={13} className="text-zinc-400" />
              Timeline
            </div>
            <p className="text-sm text-zinc-800">{data.timeline_signals || 'TBD'}</p>
          </div>
          <div className="bg-zinc-50 border border-zinc-200 rounded-lg p-4">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">
              <Wallet size={13} className="text-zinc-400" />
              Budget
            </div>
            <p className="text-sm text-zinc-800">{data.budget_signals || 'TBD'}</p>
          </div>
        </div>

        <ReportSection icon={Briefcase} title="Key Stakeholders">
          {data.key_stakeholders && data.key_stakeholders.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {data.key_stakeholders.map((s, i) => (
                <span key={i} className="text-xs font-medium bg-indigo-50 text-indigo-700 px-2.5 py-1 rounded-full border border-indigo-100">
                  {s}
                </span>
              ))}
            </div>
          ) : <p className="text-zinc-400 italic">None noted</p>}
        </ReportSection>

        {data.risks && data.risks.length > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-amber-900">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-amber-700 mb-2">
              <AlertTriangle size={13} />
              Risks
            </div>
            <BulletList items={data.risks} tone="warn" />
          </div>
        )}

        {data.open_questions && data.open_questions.length > 0 && (
          <ReportSection icon={HelpCircle} title="Open Questions">
            <BulletList items={data.open_questions} />
          </ReportSection>
        )}
      </div>
    </div>
  );
}

function ProposalReport({ proposal, clientName }) {
  const data = proposal.structured_json || {};
  const pricingItems = proposal.pricing_line_items || [];
  const grandTotal = pricingItems.reduce((sum, item) => sum + (item.qty || 1) * (item.rate_kes || 0), 0);

  return (
    <div className="bg-white text-zinc-900 rounded-lg border border-zinc-700/30 overflow-hidden shadow-sm">
      <div className="bg-gradient-to-br from-emerald-600 to-emerald-800 px-8 py-7">
        <p className="text-emerald-200 text-[11px] font-semibold tracking-[0.15em] uppercase mb-1.5">FactoryOS · Client Proposal</p>
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <h2 className="text-2xl font-bold text-white">{clientName}</h2>
          {proposal.status === 'approved' && (
            <span className="inline-block bg-white/15 text-white text-xs font-medium px-3 py-1.5 rounded-full">Approved</span>
          )}
        </div>
      </div>

      <div className="px-8 py-7 space-y-7">
        <ReportSection icon={Target} title="Approach">
          <p>{data.approach || 'Not specified'}</p>
        </ReportSection>

        <ReportSection icon={Package} title="Scoped Deliverables">
          <BulletList items={data.scoped_deliverables} />
        </ReportSection>

        <ReportSection icon={Calendar} title="Phased Timeline">
          <BulletList items={data.phased_timeline} />
        </ReportSection>

        <ReportSection icon={Users} title="Team Shape">
          {data.team_shape && data.team_shape.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {data.team_shape.map((t, i) => (
                <span key={i} className="text-xs font-medium bg-emerald-50 text-emerald-700 px-2.5 py-1 rounded-full border border-emerald-100">
                  {t}
                </span>
              ))}
            </div>
          ) : <p className="text-zinc-400 italic">Not specified</p>}
        </ReportSection>

        {pricingItems.length > 0 && (
          <div>
            <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2.5">
              <Wallet size={13} className="text-emerald-500" />
              Pricing Structure
            </h3>
            <div className="overflow-x-auto rounded-lg border border-zinc-200">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="bg-zinc-50">
                    <th className="px-4 py-2.5 text-left font-medium text-zinc-500 border-b border-zinc-200">Category</th>
                    <th className="px-4 py-2.5 text-left font-medium text-zinc-500 border-b border-zinc-200">Description</th>
                    <th className="px-4 py-2.5 text-center font-medium text-zinc-500 border-b border-zinc-200">Qty</th>
                    <th className="px-4 py-2.5 text-right font-medium text-zinc-500 border-b border-zinc-200">Rate (KES)</th>
                    <th className="px-4 py-2.5 text-right font-medium text-zinc-500 border-b border-zinc-200">Total (KES)</th>
                  </tr>
                </thead>
                <tbody>
                  {pricingItems.map((item, i) => (
                    <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-zinc-50/50'}>
                      <td className="px-4 py-2.5 border-b border-zinc-100 text-zinc-800">{item.category}</td>
                      <td className="px-4 py-2.5 border-b border-zinc-100 text-zinc-600">{item.description}</td>
                      <td className="px-4 py-2.5 border-b border-zinc-100 text-center text-zinc-600">{item.qty || 1}</td>
                      <td className="px-4 py-2.5 border-b border-zinc-100 text-right text-zinc-700">KES {(item.rate_kes || 0).toLocaleString()}</td>
                      <td className="px-4 py-2.5 border-b border-zinc-100 text-right font-medium text-zinc-900">KES {((item.qty || 1) * (item.rate_kes || 0)).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="bg-zinc-50">
                    <td colSpan={4} className="px-4 py-3 text-right font-semibold text-zinc-800 border-t-2 border-zinc-800">Total Investment</td>
                    <td className="px-4 py-3 text-right font-bold text-zinc-900 border-t-2 border-zinc-800">KES {grandTotal.toLocaleString()}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

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
          {/* brief_ready must offer the upload box too — it's how the review transcript
              (Agent 2's input) gets in; the backend accepts it in that state. */}
          {(engagement.status === 'awaiting_transcript' || engagement.status === 'awaiting_review_transcript' || engagement.status === 'brief_ready') && (
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
                <button
                  onClick={() => downloadPDF('brief')}
                  disabled={isDownloading === 'brief'}
                  className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-indigo-600 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200"
                >
                  <Download size={14} />
                  {isDownloading === 'brief' ? 'Generating PDF...' : 'Download PDF'}
                </button>
              </div>
              <BriefReport brief={engagement.brief} clientName={engagement.client_name} />
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
