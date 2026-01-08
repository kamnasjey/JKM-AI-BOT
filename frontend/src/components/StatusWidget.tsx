import { useCallback, useEffect, useState } from 'react';

import { getHealth, type HealthResponse } from '../lib/http';

export function StatusWidget() {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [retryKey, setRetryKey] = useState<number>(0);

  const retry = useCallback(() => {
    setRetryKey((x) => x + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const res = await getHealth();
        if (cancelled) return;
        setData(res);
        setError('');
      } catch (e: any) {
        if (cancelled) return;
        setData(null);
        setError(e?.message ? String(e.message) : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [retryKey]);

  const ok = data?.ok === true;
  const providerOk = data?.provider_configured === true;

  const status: 'loading' | 'down' | 'warn' | 'ok' = loading
    ? 'loading'
    : error
      ? 'down'
      : ok && providerOk
        ? 'ok'
        : ok
          ? 'warn'
          : 'down';

  const dotClass =
    status === 'ok'
      ? 'bg-green-500'
      : status === 'warn'
        ? 'bg-yellow-500'
        : status === 'down'
          ? 'bg-red-500'
          : 'bg-gray-500 animate-pulse';

  return (
    <div className="ml-auto flex items-center gap-3 text-xs">
      <div className="flex items-center gap-2 px-2 py-1 rounded border border-gray-700 bg-gray-900/40">
        <span className={`inline-block w-2 h-2 rounded-full ${dotClass}`} />
        <span className="text-gray-200">API Status</span>
        {loading ? (
          <span className="ml-1 inline-block w-20 h-3 rounded bg-gray-700/70 animate-pulse" />
        ) : (
          <span className="text-gray-300">
            {status === 'ok' ? 'OK' : status === 'warn' ? 'OK (provider not set)' : 'DOWN'}
          </span>
        )}
      </div>

      {error ? (
        <div className="flex items-center gap-2">
          <div className="text-gray-400 max-w-[340px] truncate" title={error}>
            {error}
          </div>
          <button
            className="px-2 py-1 rounded border border-gray-700 bg-gray-800 hover:bg-gray-700"
            onClick={retry}
            type="button"
          >
            Retry
          </button>
        </div>
      ) : null}
    </div>
  );
}
