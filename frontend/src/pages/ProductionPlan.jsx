import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ChevronRight, Users, Wrench, ClipboardCheck, Calendar, CheckCircle2,
  AlertTriangle, MapPin, Sparkles, Wallet,
} from 'lucide-react';
import { stageMeta, formatId, clientColor, formatKes, timeAgo } from '../lib/engagements';

const API = '/api';

const initials = (name = '') =>
  name.split(' ').map(w => w[0]).filter(Boolean).slice(0, 2).join('').toUpperCase();

function TalentCard({ member }) {
  const t = member.talent;
  const color = clientColor(t.name);
  const available = t.availability === 'available';
  return (
    <div className="rounded-xl p-4 flex flex-col gap-3" style={{ background: '#141414', border: '1px solid #242424' }}>
      <div className="flex items-start gap-3">
        <div
          className="w-10 h-10 rounded-full flex items-center justify-center shrink-0 text-[12px] font-bold"
          style={{ background: `${color}22`, border: `1px solid ${color}44`, color }}
        >
          {initials(t.name)}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-semibold text-[#f7f5ef] truncate">{t.name}</p>
          <p className="text-[11px] text-[#a3a39c] truncate">{t.title}</p>
        </div>
        <span className="shrink-0 text-[11px] font-mono px-2 py-0.5 rounded-full bg-[#7c3aed]/15 text-[#a78bfa] border border-[#7c3aed]/30">
          {member.match_score}% match
        </span>
      </div>

      <div className="text-[10px] font-mono text-[#7c3aed] bg-[#7c3aed]/10 px-2 py-1 rounded inline-block self-start">
        Cast as: {member.role}
      </div>

      <ul className="space-y-1">
        {member.match_reasons.map((r, i) => (
          <li key={i} className="flex gap-2 text-[11px] text-[#8a8a83]">
            <span className="mt-1.5 w-1 h-1 rounded-full shrink-0 bg-[#7c3aed]" />
            <span>{r}</span>
          </li>
        ))}
      </ul>

      {t.highlight && <p className="text-[11px] text-[#6e6e67] italic leading-relaxed">{t.highlight}</p>}

      <div className="flex items-center gap-3 pt-2 text-[10px] text-[#6e6e67] font-mono" style={{ borderTop: '1px solid #1e1e1e' }}>
        <span className="text-[#d6d4c9]">{formatKes(t.day_rate_kes || 0)}/day</span>
        {t.location && <span className="flex items-center gap-1"><MapPin size={10} />{t.location}</span>}
        <span className={`ml-auto flex items-center gap-1 ${available ? 'text-[#10b981]' : 'text-[#b45309]'}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${available ? 'bg-[#10b981]' : 'bg-[#f59e0b]'}`} />
          {available ? 'Available' : `Free from ${t.available_from || 'TBC'}`}
        </span>
      </div>
    </div>
  );
}

function SectionHeader({ icon: Icon, title, hint }) {
  return (
    <div className="flex items-baseline gap-2 mb-3">
      <h2 className="flex items-center gap-2 text-[14px] font-semibold text-[#f2f0e8]">
        <Icon size={14} className="text-[#8a8a83]" />
        {title}
      </h2>
      {hint && <span className="text-[10px] text-[#5c5c55] font-mono">{hint}</span>}
    </div>
  );
}

export default function ProductionPlan() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [engagement, setEngagement] = useState(null);
  const [staffing, setStaffing] = useState(null);
  // Checklist ticks are local-only — this page is the mock of the delivery phase.
  const [checked, setChecked] = useState({});

  const fetchAll = useCallback(async () => {
    try {
      const [engRes, staffRes] = await Promise.all([
        fetch(`${API}/engagements/${id}`, { credentials: 'include' }),
        fetch(`${API}/engagements/${id}/staffing`, { credentials: 'include' }),
      ]);
      if (engRes.ok) setEngagement(await engRes.json());
      if (staffRes.ok) setStaffing(await staffRes.json());
    } catch (err) {
      console.error(err);
    }
  }, [id]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  if (!engagement || !staffing) {
    return <div className="px-8 py-7 text-sm text-[#8a8a83]">Loading…</div>;
  }

  if (!staffing.available) {
    return (
      <div className="px-8 py-7">
        <p className="text-sm text-[#a3a39c] mb-3">No production plan yet — the proposal hasn't been marked as client-accepted.</p>
        <button onClick={() => navigate(`/engagements/${id}`)} className="text-xs text-[#e8c34a] underline decoration-dotted">
          Back to engagement
        </button>
      </div>
    );
  }

  const plan = staffing.plan;
  const meta = stageMeta(engagement.status);
  const doneCount = Object.values(checked).filter(Boolean).length;

  return (
    <div className="px-8 py-7 max-w-5xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-xs text-[#6e6e67] mb-6">
        <button onClick={() => navigate('/engagements')} className="hover:text-[#a3a39c] transition-colors">Engagements</button>
        <ChevronRight size={12} />
        <button onClick={() => navigate(`/engagements/${id}`)} className="hover:text-[#a3a39c] transition-colors">{engagement.client_name}</button>
        <ChevronRight size={12} />
        <span className="text-[#f7f5ef]">Production Plan</span>
      </div>

      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs font-mono text-[#6e6e67] bg-[#1a1a1a] border border-[#262626] px-2 py-0.5 rounded">{formatId(engagement.id)}</span>
          <span className="text-xs font-mono px-2 py-0.5 rounded" style={{ color: meta.color, background: meta.bg, border: `1px solid ${meta.color}30` }}>
            {meta.label}
          </span>
        </div>
        <h1 className="font-serif text-[#f7f5ef] text-2xl mb-1">Production Plan · {engagement.client_name}</h1>
        <p className="text-xs text-[#6e6e67]">
          Client accepted {timeAgo(staffing.created_at)} · Crew assembled by the Resource Planner from the agency talent pool
        </p>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-4 gap-3 mb-8">
        {[
          { icon: Users, label: 'Crew Assigned', value: String(plan.team.length) },
          { icon: Wallet, label: 'Combined Day Rate', value: formatKes(plan.team_day_rate_kes || 0) },
          { icon: Wrench, label: 'Tool Categories', value: String(plan.tools.length) },
          { icon: ClipboardCheck, label: 'Kickoff Items', value: `${doneCount}/${plan.kickoff_checklist.length}` },
        ].map(({ icon: Icon, label, value }) => (
          <div key={label} className="rounded-xl px-4 py-3" style={{ background: '#141414', border: '1px solid #242424' }}>
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-[#6e6e67] mb-1">
              <Icon size={11} />
              {label}
            </div>
            <p className="text-lg font-semibold text-[#f7f5ef] tabular-nums">{value}</p>
          </div>
        ))}
      </div>

      {/* Team */}
      <div className="mb-8">
        <SectionHeader icon={Users} title="Assigned Crew" hint="best match per proposal role" />
        <div className="grid grid-cols-2 gap-3">
          {plan.team.map((m, i) => <TalentCard key={i} member={m} />)}
        </div>

        {plan.unfilled.length > 0 && (
          <div className="mt-3 p-3 rounded-lg bg-[#f59e0b]/10 border border-[#f59e0b]/20">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-[#b45309] mb-1.5">
              <AlertTriangle size={12} />
              Roles to source externally
            </div>
            {plan.unfilled.map((u, i) => (
              <p key={i} className="text-xs text-[#b45309]">
                <span className="font-medium">{u.role}</span> — {u.note}
              </p>
            ))}
          </div>
        )}
      </div>

      {/* Tools & equipment */}
      <div className="mb-8">
        <SectionHeader icon={Wrench} title="Tools & Equipment Required" hint="derived from scoped deliverables" />
        <div className="grid grid-cols-2 gap-3">
          {plan.tools.map((group, i) => (
            <div key={i} className="rounded-xl p-4" style={{ background: '#141414', border: '1px solid #242424' }}>
              <p className="text-[12px] font-semibold text-[#d6d4c9] mb-0.5">{group.category}</p>
              <p className="text-[10px] text-[#5c5c55] font-mono mb-2">{group.reason}</p>
              <ul className="space-y-1">
                {group.items.map((item, j) => (
                  <li key={j} className="flex gap-2 text-[11px] text-[#8a8a83]">
                    <span className="mt-1.5 w-1 h-1 rounded-full shrink-0 bg-[#c9971f]" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      {/* Timeline phases from the accepted proposal */}
      {plan.phases.length > 0 && (
        <div className="mb-8">
          <SectionHeader icon={Calendar} title="Delivery Phases" hint="from the accepted proposal" />
          <div className="rounded-xl px-5 py-2" style={{ background: '#141414', border: '1px solid #242424' }}>
            {plan.phases.map((phase, i) => (
              <div key={i} className="flex items-center gap-3 py-2.5" style={i < plan.phases.length - 1 ? { borderBottom: '1px solid #191919' } : {}}>
                <span className="w-6 h-6 rounded-full bg-[#7c3aed]/15 border border-[#7c3aed]/30 text-[#a78bfa] text-[10px] font-mono flex items-center justify-center shrink-0">
                  {i + 1}
                </span>
                <p className="text-[12px] text-[#d6d4c9]">{phase}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Kickoff checklist */}
      <div className="mb-8">
        <SectionHeader icon={ClipboardCheck} title="Kickoff Checklist" />
        <div className="rounded-xl px-5 py-2" style={{ background: '#141414', border: '1px solid #242424' }}>
          {plan.kickoff_checklist.map((entry, i) => (
            <label
              key={i}
              className="flex items-center gap-3 py-2.5 cursor-pointer group"
              style={i < plan.kickoff_checklist.length - 1 ? { borderBottom: '1px solid #191919' } : {}}
            >
              <button
                type="button"
                onClick={() => setChecked(c => ({ ...c, [i]: !c[i] }))}
                className={`w-[18px] h-[18px] rounded border flex items-center justify-center shrink-0 transition-colors ${
                  checked[i] ? 'bg-[#10b981] border-[#10b981]' : 'border-[#3a3a3a] group-hover:border-[#c9971f]/60'
                }`}
              >
                {checked[i] && <CheckCircle2 size={12} className="text-white" />}
              </button>
              <p className={`flex-1 text-[12px] transition-colors ${checked[i] ? 'text-[#5c5c55] line-through' : 'text-[#d6d4c9]'}`}>
                {entry.item}
              </p>
              <span className="text-[10px] font-mono text-[#6e6e67] bg-[#1a1a1a] border border-[#262626] px-2 py-0.5 rounded shrink-0">
                {entry.owner}
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Provenance */}
      <div className="flex items-center gap-2 pb-4">
        <div className="w-5 h-5 rounded bg-[#7c3aed]/20 flex items-center justify-center">
          <Sparkles size={11} className="text-[#a78bfa]" />
        </div>
        <p className="text-[10px] text-[#6e6e67] font-mono">
          Assembled by FactoryOS · Resource Planner · Matched against {plan.team.length + plan.unfilled.length} proposal roles — review assignments before booking crew
        </p>
      </div>
    </div>
  );
}
