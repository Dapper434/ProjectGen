// Shared pipeline/stage presentation tokens from the Figma design
// (frontenddesigns), keyed by the backend's real engagement statuses.

export const PIPELINE_STAGES = [
  'awaiting_transcript',
  'brief_ready',
  'awaiting_review_transcript',
  'proposal_ready',
  'in_review',
  'approved',
];

export const STAGE_META = {
  awaiting_transcript:        { label: 'AWAITING TRANSCRIPT', color: '#64748b', bg: 'rgba(100,116,139,0.12)' },
  brief_ready:                { label: 'BRIEF READY',         color: '#a16207', bg: 'rgba(201,151,31,0.14)' },
  awaiting_review_transcript: { label: 'AWAITING REVIEW',     color: '#b45309', bg: 'rgba(245,158,11,0.12)' },
  proposal_ready:             { label: 'PROPOSAL READY',      color: '#0369a1', bg: 'rgba(14,165,233,0.12)' },
  in_review:                  { label: 'IN REVIEW',           color: '#c2410c', bg: 'rgba(249,115,22,0.12)' },
  approved:                   { label: 'APPROVED',            color: '#047857', bg: 'rgba(16,185,129,0.12)' },
};

export const STAGE_FALLBACK = { label: 'UNKNOWN', color: '#64748b', bg: 'rgba(100,116,139,0.12)' };

export const stageMeta = (status) => STAGE_META[status] ?? { ...STAGE_FALLBACK, label: (status || 'unknown').replace(/_/g, ' ').toUpperCase() };

const CLIENT_PALETTE = ['#c9971f', '#0ea5e9', '#10b981', '#f59e0b', '#f97316', '#ec4899'];

// Deterministic accent per client so avatars stay stable between renders and pages.
export function clientColor(name = '') {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return CLIENT_PALETTE[hash % CLIENT_PALETTE.length];
}

export const formatId = (id) => `#${String(id).padStart(4, '0')}`;

export function timeAgo(isoString) {
  if (!isoString) return '';
  // Backend timestamps are naive UTC; treat them as such.
  const then = new Date(isoString.endsWith('Z') ? isoString : isoString + 'Z').getTime();
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return 'Just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'Yesterday';
  return `${days}d ago`;
}

export function formatKes(n = 0) {
  if (Math.abs(n) >= 1_000_000) return `KES ${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `KES ${(n / 1_000).toFixed(1)}K`;
  return `KES ${n.toLocaleString()}`;
}
