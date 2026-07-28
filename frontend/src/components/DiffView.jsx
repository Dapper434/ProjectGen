import { useMemo } from 'react';

// Word-level diff between two transcripts, rendered as two columns.
//
// This is how you actually judge a speech engine: not by a score, but by seeing
// exactly which words it got different from the engine you trust. Implemented
// here rather than pulled from a library — it is a longest-common-subsequence
// over word arrays, and adding a dependency for that is not worth it.
function diffWords(a, b) {
  const left = (a || '').split(/\s+/).filter(Boolean);
  const right = (b || '').split(/\s+/).filter(Boolean);
  const norm = w => w.toLowerCase().replace(/[^a-z0-9]/g, '');

  // LCS table. Transcripts are bounded by meeting length; a few thousand words
  // squared is fine, but cap it so a pathological input cannot hang the tab.
  const MAX = 1200;
  if (left.length > MAX || right.length > MAX) {
    return {
      truncated: true,
      left: left.map(w => ({ word: w, kind: 'same' })),
      right: right.map(w => ({ word: w, kind: 'same' })),
    };
  }

  const table = Array.from({ length: left.length + 1 }, () => new Uint16Array(right.length + 1));
  for (let i = left.length - 1; i >= 0; i--) {
    for (let j = right.length - 1; j >= 0; j--) {
      table[i][j] = norm(left[i]) === norm(right[j])
        ? table[i + 1][j + 1] + 1
        : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }

  const leftOut = [];
  const rightOut = [];
  let i = 0;
  let j = 0;
  while (i < left.length && j < right.length) {
    if (norm(left[i]) === norm(right[j])) {
      leftOut.push({ word: left[i], kind: 'same' });
      rightOut.push({ word: right[j], kind: 'same' });
      i++; j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      leftOut.push({ word: left[i], kind: 'removed' });
      i++;
    } else {
      rightOut.push({ word: right[j], kind: 'added' });
      j++;
    }
  }
  while (i < left.length) leftOut.push({ word: left[i++], kind: 'removed' });
  while (j < right.length) rightOut.push({ word: right[j++], kind: 'added' });

  return { truncated: false, left: leftOut, right: rightOut };
}

function Column({ title, words, tone }) {
  const highlight = tone === 'removed'
    ? { color: '#fda4af', background: 'rgba(244,63,94,0.14)' }
    : { color: '#86efac', background: 'rgba(16,185,129,0.14)' };

  return (
    <div className="flex-1 min-w-0">
      <p className="text-[10px] font-mono tracking-wider text-[#8a8a83] mb-2">{title}</p>
      <div
        className="rounded-lg px-3 py-2.5 text-[12px] leading-relaxed max-h-80 overflow-y-auto"
        style={{ background: '#0e0e0e', border: '1px solid #262626' }}
      >
        {words.map((w, idx) => (
          <span
            key={idx}
            style={w.kind === 'same' ? { color: '#a3a39c' } : { ...highlight, borderRadius: 3, padding: '0 2px' }}
          >
            {w.word}{' '}
          </span>
        ))}
        {words.length === 0 && <span className="text-[#5c5c55] italic">No output.</span>}
      </div>
    </div>
  );
}

export default function DiffView({ referenceLabel, reference, candidateLabel, candidate }) {
  const diff = useMemo(() => diffWords(reference, candidate), [reference, candidate]);

  return (
    <div>
      <div className="flex gap-4 flex-col sm:flex-row">
        <Column title={`${referenceLabel} (reference)`} words={diff.left} tone="removed" />
        <Column title={candidateLabel} words={diff.right} tone="added" />
      </div>
      <p className="text-[10px] text-[#5c5c55] mt-2">
        {diff.truncated
          ? 'Transcripts too long to diff word-by-word — showing both in full instead.'
          : 'Highlighted words differ between the two engines. Neither column is ground truth.'}
      </p>
    </div>
  );
}
