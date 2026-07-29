import { NavLink, Navigate, Outlet, useOutletContext } from 'react-router-dom';
import { Settings as SettingsIcon, SlidersHorizontal, FlaskConical, AudioLines } from 'lucide-react';
import { useConfig } from '../lib/config.jsx';

// Settings is the home for anything you configure once and then leave alone —
// which engines run, and the two bake-off Labs used to decide that. None of it
// belongs in the daily sidebar; all of it is flag-gated, so the tab list is
// derived rather than hardcoded.
export function useSettingsTabs() {
  const { flags } = useConfig();
  if (!flags.lab) return [];
  return [
    {
      to: '/settings/providers', label: 'Engines', icon: SlidersHorizontal,
      blurb: 'Which speech, model and email provider each capability runs on.',
    },
    {
      to: '/settings/lab/agents', label: 'Agent Lab', icon: FlaskConical,
      blurb: 'Run the same transcript through different models and prompt variants side by side.',
    },
    ...(flags.voice ? [{
      to: '/settings/lab/speech', label: 'Speech Lab', icon: AudioLines,
      blurb: 'Compare transcription engines on the same audio before trusting one with a meeting.',
    }] : []),
  ];
}

export default function Settings() {
  const { user } = useOutletContext();
  const tabs = useSettingsTabs();

  if (tabs.length === 0) {
    return (
      <div className="px-8 py-7">
        <div className="flex items-center gap-2.5 mb-1.5">
          <SettingsIcon size={18} className="text-[#c9971f]" />
          <h1 className="font-serif text-[#f7f5ef] text-2xl">Settings</h1>
        </div>
        <p className="text-sm text-[#8a8a83]">
          Nothing to configure — the provider registry and the Labs are switched off in this deployment.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-8 pt-7 pb-0">
        <div className="flex items-center gap-2.5 mb-1.5">
          <SettingsIcon size={18} className="text-[#c9971f]" />
          <h1 className="font-serif text-[#f7f5ef] text-2xl">Settings</h1>
        </div>
        <p className="text-sm text-[#8a8a83] mb-5 max-w-2xl">
          How the system is wired up. Changes take effect on the next request — no restart, no deploy.
        </p>
        <nav aria-label="Settings sections" className="flex gap-1 -mb-px">
          {tabs.map(({ to, label, icon: Icon, blurb }) => (
            <NavLink
              key={to}
              to={to}
              title={blurb}
              className={({ isActive }) =>
                `flex items-center gap-1.5 px-3.5 py-2.5 text-[13px] font-medium transition-colors ${
                  isActive ? 'text-[#f7f5ef]' : 'text-[#8a8a83] hover:text-[#d6d4c9]'
                }`
              }
              style={({ isActive }) => ({
                borderBottom: isActive ? '2px solid #c9971f' : '2px solid transparent',
              })}
            >
              {({ isActive }) => (
                <>
                  <Icon size={14} className={isActive ? 'text-[#e8c34a]' : 'text-[#5c5c55]'} />
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="flex-1 overflow-y-auto" style={{ borderTop: '1px solid #242424' }}>
        <Outlet context={{ user }} />
      </div>
    </div>
  );
}

// Landing on /settings goes to whichever section is actually enabled.
export function SettingsIndex() {
  const tabs = useSettingsTabs();
  if (tabs.length === 0) return null;
  return <Navigate to={tabs[0].to} replace />;
}
