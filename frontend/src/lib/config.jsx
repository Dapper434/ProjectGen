import { createContext, useContext, useEffect, useState } from 'react';

// All flags default off until /api/config answers, so a slow/failed fetch never
// makes flagged UI appear — the safe failure mode is "hidden", not "shown".
const ConfigContext = createContext({ flags: {}, product: 'The Exodus', loaded: false });

export function ConfigProvider({ children }) {
  const [config, setConfig] = useState({ flags: {}, product: 'The Exodus', loaded: false });

  useEffect(() => {
    fetch('/api/config', { credentials: 'include' })
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        if (data) setConfig({ flags: data.flags || {}, product: data.product || 'The Exodus', loaded: true });
      })
      .catch(err => console.error(err));
  }, []);

  return <ConfigContext.Provider value={config}>{children}</ConfigContext.Provider>;
}

export function useConfig() {
  return useContext(ConfigContext);
}
