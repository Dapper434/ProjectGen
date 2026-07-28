import { useState } from 'react';
import { Check, Circle, CircleDot, HelpCircle, Copy, ChevronDown } from 'lucide-react';

const STATUS = {
  covered: { label: 'COVERED', color: '#10b981', bg: 'rgba(16,185,129,0.12)', Icon: Check },
  partial: { label: 'PARTIAL', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', Icon: CircleDot },
  missing: { label: 'NOT RAISED', color: '#8a8a83', bg: 'rgba(138,138,131,0.10)', Icon: Circle },
  unknown: { label: 'UNCHECKED', color: '#64748b', bg: 'rgba(100,116,139,0.12)', Icon: HelpCircle },
};

// The checklist is the product, not the transcript. A producer glancing at this
// mid-meeting should be able to steer the conversation before the client hangs up.
export default function AgendaChecklist({ protocol, coverage, onJumpToSeq }) {
  const [expanded, setExpanded] = useState(null);
  const [copied, setCopied] = useState(null);
  const byKey = Object.fromEntries((coverage || []).map(c => [c.key, c]));
  const items = protocol?.items || [];

  const missingRequired = items.filter(
    i => i.required && (byKey[i.key]?.status ?? 'missing') !== 'covered'
  );

  async function copyAsk(item) {
    try {
      await navigator.clipboard.writeText(item.ask);
      setCopied(item.key);
      setTimeout(() => setCopied(null), 2000);
    } catch (err) { console.error(err); }
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Announced to screen readers; the scrolling transcript deliberately is not. */}
      <div aria-live="polite" className="sr-only">
        {missingRequired.length === 0
          ? 'All required agenda items are covered.'
          : `${missingRequired.length} required items still uncovered: ${missingRequired.map(i => i.label).join(', ')}.`}
      </div>

      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[14px] font-semibold text-[#f2f0e8]">Agenda</span>
        <span className="text-[10px] font-mono text-[#5c5c55]">
          {items.filter(i => byKey[i.key]?.status === 'covered').length}/{items.length} covered
        </span>
      </div>

      <div className="flex flex-col gap-2">
        {items.map(item => {
          const check = byKey[item.key];
          const meta = STATUS[check?.status || 'missing'] || STATUS.missing;
          const open = expanded === item.key;
          return (
            <div key={item.key} className="rounded-lg overflow-hidden"
              style={{ background: '#141414', border: '1px solid #242424' }}>
              <button
                onClick={() => setExpanded(open ? null : item.key)}
                aria-expanded={open}
                className="w-full flex items-start gap-2.5 px-3 py-2.5 text-left hover:bg-[#1a1a1a] transition-colors"
              >
                <meta.Icon size={13} style={{ color: meta.color }} className="shrink-0 mt-0.5" />
                <span className="flex-1 min-w-0">
                  <span className="block text-[12px] text-[#d6d4c9]">
                    {item.label}
                    {item.required && <span className="text-[#e11d48] ml-1" title="Required">*</span>}
                  </span>
                  <span className="text-[9px] font-mono" style={{ color: meta.color }}>{meta.label}</span>
                </span>
                <ChevronDown size={12}
                  className={`text-[#5c5c55] shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
              </button>

              {open && (
                <div className="px-3 pb-3 pt-1 flex flex-col gap-2" style={{ borderTop: '1px solid #191919' }}>
                  <p className="text-[11px] text-[#8a8a83]">{item.why}</p>
                  {check?.evidence ? (
                    <button
                      onClick={() => check.evidence_seq != null && onJumpToSeq?.(check.evidence_seq)}
                      className="text-left text-[11px] text-[#86efac] rounded px-2 py-1.5 hover:opacity-80"
                      style={{ background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)' }}
                    >
                      “{check.evidence}”
                      {check.evidence_seq != null && (
                        <span className="block text-[9px] text-[#5c5c55] mt-0.5">Jump to this moment</span>
                      )}
                    </button>
                  ) : (
                    <div className="flex items-start gap-2">
                      <p className="flex-1 text-[11px] text-[#a3a39c] italic">“{item.ask}”</p>
                      <button
                        onClick={() => copyAsk(item)}
                        aria-label={`Copy the question for ${item.label}`}
                        className="shrink-0 flex items-center gap-1 text-[10px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors"
                      >
                        <Copy size={10} />{copied === item.key ? 'Copied' : 'Ask this'}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {items.length === 0 && (
          <p className="text-[12px] text-[#5c5c55]">No protocol items — check Authoritative Data.</p>
        )}
      </div>
    </div>
  );
}
