import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, X } from 'lucide-react';

const MATCH_LABELS = {
  'Client name': 'Client',
  'Production brief': 'Brief',
  'Client proposal': 'Proposal',
};

// Company names aren't unique identifiers — the same client can have many engagements,
// so group results under one header per client instead of repeating the name per row.
function groupByClient(results) {
  const groups = [];
  const indexByClient = new Map();
  for (const r of results) {
    if (!indexByClient.has(r.client_name)) {
      indexByClient.set(r.client_name, groups.length);
      groups.push({ client_name: r.client_name, items: [] });
    }
    groups[indexByClient.get(r.client_name)].items.push(r);
  }
  return groups;
}

export default function SearchBar() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const containerRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      setLoading(false);
      setHighlightIndex(-1);
      return;
    }
    setLoading(true);
    const handle = setTimeout(() => {
      fetch(`http://localhost:5000/api/search?q=${encodeURIComponent(q)}`, { credentials: 'include' })
        .then((res) => (res.ok ? res.json() : []))
        .then((data) => {
          setResults(data);
          setHighlightIndex(-1);
          setOpen(true);
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const goTo = (id) => {
    navigate(`/engagements/${id}`);
    setOpen(false);
    setQuery('');
  };

  const groups = useMemo(() => groupByClient(results), [results]);
  // Flat list in the same order the grouped dropdown renders, so arrow keys walk it top-to-bottom.
  const flatItems = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      setOpen(false);
      e.currentTarget.blur();
    } else if (e.key === 'ArrowDown' && flatItems.length > 0) {
      e.preventDefault();
      setOpen(true);
      setHighlightIndex((i) => (i + 1) % flatItems.length);
    } else if (e.key === 'ArrowUp' && flatItems.length > 0) {
      e.preventDefault();
      setHighlightIndex((i) => (i <= 0 ? flatItems.length - 1 : i - 1));
    } else if (e.key === 'Enter') {
      // Enter only follows an explicit choice: a highlighted row, or the sole result.
      // With several matches and nothing highlighted, it just keeps the list open to browse.
      if (highlightIndex >= 0 && highlightIndex < flatItems.length) {
        goTo(flatItems[highlightIndex].id);
      } else if (flatItems.length === 1) {
        goTo(flatItems[0].id);
      }
    }
  };

  return (
    <div ref={containerRef} className="relative w-full max-w-md">
      <div className="relative">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => query.trim().length >= 2 && setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search clients, briefs, proposals..."
          className="w-full bg-zinc-900 border border-zinc-800 rounded-md pl-9 pr-8 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
        />
        {query && (
          <button
            onClick={() => { setQuery(''); setResults([]); setOpen(false); }}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {open && query.trim().length >= 2 && (
        <div className="absolute z-20 mt-2 w-full bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl overflow-hidden">
          {loading ? (
            <div className="px-4 py-3 text-xs text-zinc-500">Searching...</div>
          ) : results.length === 0 ? (
            <div className="px-4 py-3 text-xs text-zinc-500">No matches for "{query}"</div>
          ) : (
            <ul className="max-h-96 overflow-auto divide-y divide-zinc-800">
              {groups.map((group) => (
                <li key={group.client_name}>
                  <div className="px-4 pt-2.5 pb-1.5 flex items-center gap-2 bg-zinc-950/60">
                    <span className="text-xs font-medium text-zinc-200 truncate">{group.client_name}</span>
                    {group.items.length > 1 && (
                      <span className="text-[10px] text-zinc-500">({group.items.length} engagements)</span>
                    )}
                  </div>
                  <ul>
                    {group.items.map((r) => (
                      <li key={r.id}>
                        <button
                          onClick={() => goTo(r.id)}
                          onMouseEnter={() => setHighlightIndex(flatItems.indexOf(r))}
                          className={`w-full text-left pl-6 pr-4 py-2 transition-colors flex items-start justify-between gap-3 ${flatItems[highlightIndex] === r ? 'bg-zinc-800/80' : 'hover:bg-zinc-800/60'}`}
                        >
                          <div className="min-w-0">
                            <p className="text-xs text-zinc-400">
                              Engagement #{r.id.toString().padStart(4, '0')} · {r.status.replace(/_/g, ' ')}
                            </p>
                            {r.preview && (
                              <p className="text-xs text-zinc-500 mt-0.5 truncate">{r.preview}</p>
                            )}
                          </div>
                          <span className="shrink-0 text-[10px] font-medium tracking-wide uppercase text-indigo-400 bg-indigo-500/10 px-2 py-1 rounded-full">
                            {MATCH_LABELS[r.match] || r.match}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
