const COLORS = {
  tokens: '#c9971f',
  skill_match: '#0ea5e9',
  rating: '#10b981',
  inhouse: '#a78bfa',
  rate_fit: '#f59e0b',
};

const LABELS = {
  tokens: 'Tokens',
  skill_match: 'Skill match',
  rating: 'Rating',
  inhouse: 'In-house',
  rate_fit: 'Rate fit',
};

// Not decoration. This is what an Account Manager points at when a producer asks
// why the agent picked someone, and what makes the token system feel like a
// system rather than a black box.
export default function ScoreBreakdown({ why, score }) {
  if (!why?.length) return null;
  const total = why.reduce((sum, w) => sum + (w.contribution || 0), 0) || 1;

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-[10px] font-mono tracking-wider text-[#8a8a83]">SCORE</span>
        <span className="text-[12px] font-medium text-[#f2f0e8]">{(score ?? total).toFixed(3)}</span>
      </div>

      <div className="flex h-2 rounded-full overflow-hidden" style={{ background: '#0e0e0e' }}
        role="img"
        aria-label={why.map(w => `${LABELS[w.component] || w.component} ${(w.contribution * 100 / total).toFixed(0)} percent`).join(', ')}>
        {why.map(w => (
          <div key={w.component}
            style={{ width: `${(w.contribution / total) * 100}%`, background: COLORS[w.component] || '#5c5c55' }}
            title={`${LABELS[w.component] || w.component}: ${w.contribution.toFixed(3)}`} />
        ))}
      </div>

      <div className="mt-2 flex flex-col gap-1">
        {why.map(w => (
          <div key={w.component} className="flex items-center gap-2 text-[10px]">
            <span className="w-2 h-2 rounded-sm shrink-0"
              style={{ background: COLORS[w.component] || '#5c5c55' }} />
            <span className="text-[#a3a39c] flex-1">{LABELS[w.component] || w.component}</span>
            <span className="font-mono text-[#5c5c55]">
              {(w.raw ?? 0).toFixed(2)} × {w.weight}
            </span>
            <span className="font-mono text-[#d6d4c9] w-12 text-right">{w.contribution.toFixed(3)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
