import React, { useEffect, useState } from 'react';

import { apiGetJson } from '../lib/apiClient';

type HealthResponse = {
  ok: boolean;
  provider_configured?: boolean;
  uptime_s?: number;
  ts?: number;
};

export function StatusWidget() {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiGetJson<HealthResponse>('/health');
        if (cancelled) return;
        setData(res);
        setError('');
      } catch (e: any) {
        if (cancelled) return;
        setData(null);
        setError(e?.message ? String(e.message) : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const ok = data?.ok === true;
  const providerOk = data?.provider_configured === true;

  return (
    <div className="ml-auto flex items-center gap-2 text-xs">
      <div className={`px-2 py-1 rounded border ${ok ? 'bg-green-600/20 border-green-600 text-green-200' : 'bg-red-600/20 border-red-600 text-red-200'}`}>
        API {ok ? 'OK' : 'DOWN'}
      </div>
      <div className={`px-2 py-1 rounded border ${providerOk ? 'bg-green-600/20 border-green-600 text-green-200' : 'bg-yellow-600/20 border-yellow-600 text-yellow-200'}`}>
        Provider {providerOk ? 'READY' : 'NOT SET'}
      </div>
      {error && <div className="text-gray-400 max-w-[340px] truncate">{error}</div>}
    </div>
  );
}
