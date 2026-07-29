import { useCallback, useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { BookOpen, Pencil, Plus, Search, ClipboardCheck } from 'lucide-react';
import AuthoritativeEditor from '../components/AuthoritativeEditor';
import RequirementEditor, { DOC_TYPE_LABEL } from '../components/RequirementEditor';
import { useConfig } from '../lib/config.jsx';
import { timeAgo } from '../lib/engagements';

const API = '/api';

// The Playbook is the single home for everything that instructs the system:
// versioned agent prompts and policies (AuthoritativeDoc, resolved per scope) and
// the free-text requirement corpus the completeness checker grades finished
// documents against. They used to be two pages — "Authoritative Data" and
// "Requirements" — which split one mental model across two places.
const REQUIREMENTS_GROUP = {
  id: 'requirements',
  title: 'Definition of Done',
  blurb: 'What a finished brief or proposal must contain. Every generated document is '
       + 'checked against these and anything missing is flagged before it reaches a client.',
};

function SectionShell({ group, count, action, children }) {
  return (
    <section className="mb-8">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-3">
        <div className="max-w-2xl">
          <div className="flex items-center gap-2">
            <h2 className="text-[15px] font-semibold text-[#f2f0e8]">{group.title}</h2>
            <span className="text-[10px] font-mono text-[#5c5c55]">{count}</span>
          </div>
          <p className="text-[12px] text-[#8a8a83] mt-1">{group.blurb}</p>
        </div>
        {action}
      </div>
      <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
        {children}
      </div>
    </section>
  );
}

function Row({ title, subtitle, meta, badge, canEdit, onOpen }) {
  return (
    <div
      onClick={() => canEdit && onOpen()}
      onKeyDown={e => { if (canEdit && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onOpen(); } }}
      role={canEdit ? 'button' : undefined}
      tabIndex={canEdit ? 0 : undefined}
      aria-label={canEdit ? `Edit ${title}` : undefined}
      className={`flex items-start gap-3 px-5 py-3.5 transition-colors group ${
        canEdit ? 'cursor-pointer hover:bg-[#1a1a1a] focus:bg-[#1a1a1a] focus:outline-none' : ''
      }`}
    >
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-[#d6d4c9]">{title}</p>
        {subtitle && <p className="text-[12px] text-[#8a8a83] mt-0.5 leading-snug">{subtitle}</p>}
        {meta && <p className="text-[10px] text-[#5c5c55] font-mono mt-1">{meta}</p>}
      </div>
      {badge}
      {canEdit && <Pencil size={12} className="mt-1 text-[#5c5c55] group-hover:text-[#c9971f] transition-colors shrink-0" />}
    </div>
  );
}

export default function Playbook() {
  const { user } = useOutletContext();
  const { flags } = useConfig();
  const canEdit = user?.role === 'Account Manager' || user?.role === 'Admin';

  const [entries, setEntries] = useState([]);
  const [groups, setGroups] = useState([]);
  const [requirements, setRequirements] = useState([]);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [editingKey, setEditingKey] = useState(null);
  const [editingDoc, setEditingDoc] = useState(undefined);  // undefined = closed, null = new

  const fetchAll = useCallback(async () => {
    try {
      const reqRes = await fetch(`${API}/requirements`, { credentials: 'include' });
      if (reqRes.ok) setRequirements(await reqRes.json());

      if (!flags.auth_data) return;
      const [entryRes, groupRes] = await Promise.all([
        fetch(`${API}/authoritative?scope_type=global`, { credentials: 'include' }),
        fetch(`${API}/authoritative/groups`, { credentials: 'include' }),
      ]);
      if (!entryRes.ok) {
        const err = await entryRes.json().catch(() => ({}));
        setError(err.error || 'Could not load the Playbook.');
        return;
      }
      setEntries(await entryRes.json());
      if (groupRes.ok) setGroups(await groupRes.json());
    } catch (err) {
      console.error(err);
      setError('Connection failed. Is the backend running?');
    }
  }, [flags.auth_data]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const q = query.trim().toLowerCase();
  const matches = useCallback((...fields) => (
    !q || fields.some(f => (f || '').toLowerCase().includes(q))
  ), [q]);

  const entriesByGroup = useMemo(() => {
    const out = {};
    for (const entry of entries) {
      if (!matches(entry.title, entry.description, entry.key, (entry.consumers || []).join(' '))) continue;
      (out[entry.group] ||= []).push(entry);
    }
    return out;
  }, [entries, matches]);

  const visibleRequirements = useMemo(
    () => requirements.filter(d => matches(d.title, DOC_TYPE_LABEL[d.doc_type])),
    [requirements, matches],
  );

  const editingEntry = entries.find(e => e.key === editingKey);
  const totalHits = Object.values(entriesByGroup).reduce((n, list) => n + list.length, 0) + visibleRequirements.length;

  return (
    <div className="px-8 py-7 max-w-4xl">
      <div className="flex items-center gap-2.5 mb-1.5">
        <BookOpen size={18} className="text-[#c9971f]" />
        <h1 className="font-serif text-[#f7f5ef] text-2xl">Playbook</h1>
      </div>
      <p className="text-sm text-[#8a8a83] mb-6 max-w-2xl">
        Everything that tells The Exodus how to work — the instructions its agents read, the rules
        they obey, and the standard finished documents are held to. Change something here and the
        next run picks it up; no deploy, and every edit is kept.
      </p>

      {error && <p role="alert" className="text-sm text-rose-500 mb-4">{error}</p>}

      <div className="relative mb-7">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#5c5c55]" />
        <input
          type="search"
          value={query}
          onChange={e => setQuery(e.target.value)}
          aria-label="Search the Playbook"
          placeholder="Search instructions, policies and requirements…"
          className="w-full rounded-lg pl-9 pr-3 py-2.5 text-[13px] text-[#d6d4c9] bg-[#0e0e0e] placeholder:text-[#5c5c55] focus:outline-none focus:border-[#c9971f]/60 transition-colors"
          style={{ border: '1px solid #262626' }}
        />
      </div>

      {q && totalHits === 0 && (
        <p className="text-[13px] text-[#8a8a83] mb-6">Nothing in the Playbook matches “{query}”.</p>
      )}

      {groups.map(group => {
        const list = entriesByGroup[group.id] || [];
        if (list.length === 0) return null;
        return (
          <SectionShell key={group.id} group={group} count={`${list.length}`}>
            <div className="divide-y" style={{ borderColor: '#191919' }}>
              {list.map(entry => {
                const active = entry.active_docs?.[0];
                return (
                  <Row
                    key={entry.key}
                    title={entry.title}
                    subtitle={entry.description}
                    meta={`${entry.fmt.toUpperCase()} · scopes: ${entry.scopes.join(', ')}`
                      + (entry.consumers.length ? ` · read by ${entry.consumers.join(', ')}` : '')
                      + (entry.variants ? ' · A/B variants' : '')}
                    canEdit={canEdit}
                    onOpen={() => setEditingKey(entry.key)}
                    badge={active ? (
                      <span className="text-[10px] font-mono font-semibold px-2 py-1 rounded-md shrink-0"
                        style={{ color: '#10b981', background: 'rgba(16,185,129,0.12)' }}>
                        v{active.version} ACTIVE
                      </span>
                    ) : (
                      <span className="text-[10px] font-mono text-[#5c5c55] shrink-0 px-2 py-1">NOT SET</span>
                    )}
                  />
                );
              })}
            </div>
          </SectionShell>
        );
      })}

      <SectionShell
        group={REQUIREMENTS_GROUP}
        count={`${visibleRequirements.length}`}
        action={canEdit && (
          <button
            onClick={() => setEditingDoc(null)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-white text-[12px] font-medium transition-all hover:opacity-90 shrink-0"
            style={{ background: 'linear-gradient(135deg, #c9971f, #a67a17)' }}
          >
            <Plus size={12} />
            New document
          </button>
        )}
      >
        {visibleRequirements.length === 0 ? (
          <div className="px-5 py-8 text-center text-[13px] text-[#8a8a83]">
            {q
              ? 'No requirement document matches that search.'
              : 'No requirement documents yet — completeness checks stay switched off until at least one exists.'}
          </div>
        ) : (
          <div className="divide-y" style={{ borderColor: '#191919' }}>
            {visibleRequirements.map(d => (
              <Row
                key={d.id}
                title={d.title}
                subtitle={null}
                meta={`Applies to ${DOC_TYPE_LABEL[d.doc_type] || d.doc_type} · ${d.length.toLocaleString()} chars · `
                  + (d.updated_at
                    ? `edited by ${d.updated_by || 'unknown'} ${timeAgo(d.updated_at)}`
                    : `added by ${d.uploaded_by || 'unknown'} ${timeAgo(d.uploaded_at)}`)}
                canEdit={canEdit}
                onOpen={() => setEditingDoc(d.id)}
                badge={(
                  <span className="text-[10px] font-mono px-2 py-1 rounded-md shrink-0 flex items-center gap-1"
                    style={{ color: '#8a8a83', background: '#1a1a1a' }}>
                    <ClipboardCheck size={10} />
                    GRADED
                  </span>
                )}
              />
            ))}
          </div>
        )}
      </SectionShell>

      {editingKey && (
        <AuthoritativeEditor
          keyName={editingKey}
          registryEntry={editingEntry}
          scopeType="global"
          scopeId={null}
          canEdit={canEdit}
          onClose={() => setEditingKey(null)}
          onSaved={fetchAll}
        />
      )}

      {editingDoc !== undefined && (
        <RequirementEditor
          docId={editingDoc}
          canEdit={canEdit}
          onClose={() => setEditingDoc(undefined)}
          onSaved={fetchAll}
        />
      )}
    </div>
  );
}
