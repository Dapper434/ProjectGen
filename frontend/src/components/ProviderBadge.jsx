import { Cloud, HardDrive } from 'lucide-react';

// Small, quiet chip shown wherever a driver produced an artefact — under a
// transcript, on a recording job, beside a generated brief. The user should
// never have to guess which engine wrote something (AGENTS.md §5).
export default function ProviderBadge({ driverLabel, driverKey, isLocal, latencyMs, className = '' }) {
  if (!driverLabel && !driverKey) return null;
  const Icon = isLocal ? HardDrive : Cloud;
  const seconds = typeof latencyMs === 'number' ? `${(latencyMs / 1000).toFixed(1)}s` : null;

  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded ${className}`}
      style={{ color: '#8a8a83', background: '#1a1a1a', border: '1px solid #262626' }}
      title={`Produced by ${driverLabel || driverKey}${seconds ? ` in ${seconds}` : ''}`}
    >
      <Icon size={9} aria-hidden="true" />
      via {driverLabel || driverKey}
      {seconds && <span className="text-[#5c5c55]">· {seconds}</span>}
    </span>
  );
}
