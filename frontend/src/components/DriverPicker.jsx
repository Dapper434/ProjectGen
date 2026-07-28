import { useState } from 'react';
import { Cloud, HardDrive, Play, Loader2 } from 'lucide-react';

const API = '/api';

function HealthDot({ health }) {
  // amber = reachable but degraded/unconfigured, red = unavailable, green = ok.
  const color = health === undefined ? '#5c5c55' : health?.ok ? '#10b981' : '#f43f5e';
  const label = health === undefined ? 'Health unknown' : health.ok ? 'Healthy' : `Unavailable: ${health.detail}`;
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className="w-2 h-2 rounded-full shrink-0"
      style={{ background: color }}
    />
  );
}

function OptionsForm({ schema, values, onChange }) {
  const entries = Object.entries(schema || {});
  if (entries.length === 0) return null;
  return (
    <div className="mt-2.5 pl-6 flex flex-col gap-2">
      {entries.map(([name, spec]) => {
        const id = `opt-${name}`;
        const current = values?.[name] ?? spec.default ?? '';
        if (spec.type === 'boolean') {
          return (
            <label key={name} htmlFor={id} className="flex items-center gap-2 text-[11px] text-[#a3a39c]">
              <input
                id={id}
                type="checkbox"
                checked={Boolean(current)}
                onChange={e => onChange({ ...values, [name]: e.target.checked })}
                className="accent-[#c9971f]"
              />
              {spec.label || name}
            </label>
          );
        }
        return (
          <div key={name} className="flex flex-col gap-1">
            <label htmlFor={id} className="text-[10px] font-mono tracking-wider text-[#6e6e67]">
              {(spec.label || name).toUpperCase()}
            </label>
            <input
              id={id}
              type={spec.secret ? 'password' : spec.type === 'number' ? 'number' : 'text'}
              value={current === null ? '' : current}
              placeholder={spec.default === null ? 'server default' : String(spec.default ?? '')}
              onChange={e => onChange({
                ...values,
                [name]: spec.type === 'number' ? Number(e.target.value) : e.target.value,
              })}
              className="rounded-lg px-2.5 py-1.5 text-[11px] text-[#d6d4c9] bg-[#0e0e0e]"
              style={{ border: '1px solid #262626' }}
            />
          </div>
        );
      })}
    </div>
  );
}

// Radio list of drivers for one capability, with health dot, options form and a
// Test button. Selecting one writes the runtime setting and takes effect on the
// next request — no restart.
export default function DriverPicker({ capability, healthByDriver, canEdit, onChanged }) {
  const [pending, setPending] = useState(null);
  const [options, setOptions] = useState(capability.options || {});
  const [testResult, setTestResult] = useState({});
  const [testing, setTesting] = useState(null);
  const [error, setError] = useState('');

  async function selectDriver(driverKey) {
    if (!canEdit) return;
    setPending(driverKey);
    setError('');
    try {
      const res = await fetch(`${API}/providers/${capability.capability}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ driver_key: driverKey, options }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.error || 'Could not switch driver.');
        return;
      }
      onChanged?.();
    } catch (err) {
      console.error(err);
      setError('Connection failed.');
    } finally {
      setPending(null);
    }
  }

  async function testDriver(driverKey) {
    setTesting(driverKey);
    try {
      const res = await fetch(`${API}/providers/${capability.capability}/test`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ driver_key: driverKey, options }),
      });
      const result = await res.json();
      setTestResult(prev => ({ ...prev, [driverKey]: result }));
    } catch (err) {
      console.error(err);
      setTestResult(prev => ({ ...prev, [driverKey]: { ok: false, detail: 'Connection failed.' } }));
    } finally {
      setTesting(null);
    }
  }

  return (
    <div className="rounded-xl overflow-hidden" style={{ background: '#141414', border: '1px solid #242424' }}>
      <div className="flex items-center justify-between gap-3 px-5 py-4" style={{ borderBottom: '1px solid #242424' }}>
        <div>
          <p className="text-[14px] font-semibold text-[#f2f0e8]">{capability.label}</p>
          <p className="text-[10px] font-mono text-[#5c5c55] mt-0.5">
            {capability.capability} · selected from {capability.selected_source}
          </p>
        </div>
      </div>

      {error && <p role="alert" className="px-5 pt-3 text-xs text-rose-500">{error}</p>}

      <fieldset className="px-5 py-2">
        <legend className="sr-only">Driver for {capability.label}</legend>
        {capability.drivers.map(driver => {
          const id = `${capability.capability}-${driver.key}`;
          const health = healthByDriver?.[`${capability.capability}:${driver.key}`];
          const test = testResult[driver.key];
          return (
            <div key={driver.key} className="py-3" style={{ borderBottom: '1px solid #191919' }}>
              <div className="flex items-start gap-2.5">
                <input
                  id={id}
                  type="radio"
                  name={capability.capability}
                  checked={driver.selected}
                  disabled={!canEdit || !driver.available || pending === driver.key}
                  onChange={() => selectDriver(driver.key)}
                  className="mt-1 accent-[#c9971f]"
                />
                <div className="min-w-0 flex-1">
                  <label htmlFor={id} className="flex items-center gap-2 flex-wrap cursor-pointer">
                    <span className="text-[13px] font-medium text-[#d6d4c9]">{driver.label}</span>
                    <HealthDot health={health} />
                    <span className="inline-flex items-center gap-1 text-[9px] font-mono text-[#6e6e67]">
                      {driver.is_local ? <HardDrive size={9} /> : <Cloud size={9} />}
                      {driver.is_local ? 'LOCAL' : 'CLOUD'}
                    </span>
                    {driver.selected && (
                      <span className="text-[9px] font-mono font-semibold px-1.5 py-0.5 rounded"
                        style={{ color: '#10b981', background: 'rgba(16,185,129,0.12)' }}>IN USE</span>
                    )}
                  </label>
                  <p className="text-[11px] text-[#8a8a83] mt-0.5">{driver.blurb}</p>
                  <p className="text-[10px] text-[#5c5c55] font-mono mt-0.5">{driver.cost_hint}</p>
                  {!driver.available && (
                    <p className="text-[10px] text-[#f43f5e] mt-1">
                      Unavailable — {driver.missing_env.join(', ')} not set on the server.
                    </p>
                  )}
                  {test && (
                    <p className={`text-[10px] mt-1 ${test.ok ? 'text-[#10b981]' : 'text-[#f43f5e]'}`} aria-live="polite">
                      {test.ok ? 'OK' : 'Failed'} — {test.detail}
                      {typeof test.latency_ms === 'number' ? ` (${test.latency_ms}ms)` : ''}
                    </p>
                  )}
                  {driver.selected && (
                    <OptionsForm schema={driver.options_schema} values={options} onChange={setOptions} />
                  )}
                </div>
                <button
                  onClick={() => testDriver(driver.key)}
                  disabled={testing === driver.key}
                  aria-label={`Test ${driver.label}`}
                  className="shrink-0 flex items-center gap-1 text-[11px] text-[#a3a39c] hover:text-[#e8c34a] transition-colors disabled:opacity-50"
                >
                  {testing === driver.key ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
                  Test
                </button>
              </div>
            </div>
          );
        })}
      </fieldset>
    </div>
  );
}
