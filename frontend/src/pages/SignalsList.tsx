import { useEffect, useMemo, useState } from 'react';

import { getSignals } from '../lib/http';

function getUrlParam(key: string): string | null {
  try {
    return new URLSearchParams(window.location.search).get(key);
  } catch {
    return null;
  }
}

function getAuthToken(): string | null {
  return (
    getUrlParam('token') ||
    window.localStorage.getItem('jkm_ai_session_v1') ||
    window.localStorage.getItem('token') ||
    window.localStorage.getItem('session_token')
  );
}

export type SignalListItem = {
  key: string;
  ts?: number | null;
  signal_id?: string | null;
  symbol?: string | null;
  tf?: string | null;
  direction?: string | null;
  rr?: number | null;
  raw: any;
};

export function SignalsList(props: { onOpen: (signalId: string) => void }) {
  const [items, setItems] = useState<SignalListItem[]>([]);
  const [status, setStatus] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');
  const [retryKey, setRetryKey] = useState<number>(0);

  const headers = useMemo(() => {
    const token = getAuthToken();
    const h: Record<string, string> = { Accept: 'application/json' };
    if (token) h.Authorization = `Bearer ${token}`;
    return h;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      setStatus('Loading…');
      try {
        const data = await getSignals(50);
        if (cancelled) return;
        const mapped = Array.isArray(data)
          ? data.map((x, idx) => {
              const obj = (x && typeof x === 'object') ? x : { value: x };
              const signalId = obj.signal_id == null ? null : String(obj.signal_id);
              const ts = obj.ts == null ? null : Number(obj.ts);
              const key = signalId || (Number.isFinite(ts) ? String(ts) : String(idx));
              return {
                key,
                ts: Number.isFinite(ts) ? ts : null,
                signal_id: signalId,
                symbol: obj.symbol == null ? null : String(obj.symbol),
                tf: obj.tf == null ? null : String(obj.tf),
                direction: obj.direction == null ? null : String(obj.direction),
                rr: obj.rr == null ? null : Number(obj.rr),
                raw: obj,
              } as SignalListItem;
            })
          : [];
        setItems(mapped);
        setStatus(`Loaded ${mapped.length}`);
      } catch (e) {
        const msg = String((e as any)?.message || e);
        setError(msg);
        setStatus('');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [headers, retryKey]);

  const retry = () => setRetryKey((x) => x + 1);

  return (
    <div className="p-4 text-white">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">Signals</h2>
        <div className="text-sm text-gray-400">{status}</div>
      </div>

      {error ? (
        <div className="mb-3 p-3 rounded border border-red-800 bg-red-900/20 text-red-200">
          <div className="font-semibold">Could not load signals</div>
          <div className="text-sm text-red-200/80 mt-1 break-words">{error}</div>
          <button
            className="mt-3 px-3 py-1 rounded border border-red-700 bg-red-800/30 hover:bg-red-800/50"
            onClick={retry}
            type="button"
          >
            Retry
          </button>
        </div>
      ) : null}

      <div className="overflow-auto border border-gray-700 rounded">
        <table className="w-full text-sm">
          <thead className="bg-gray-800 text-gray-200">
            <tr>
              <th className="text-left p-2">ID</th>
              <th className="text-left p-2">Symbol</th>
              <th className="text-left p-2">TF</th>
              <th className="text-left p-2">Side</th>
              <th className="text-left p-2">RR</th>
              <th className="text-left p-2">Time</th>
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 && !error && (
              Array.from({ length: 6 }).map((_, i) => (
                <tr key={`sk_${i}`} className="border-t border-gray-800">
                  <td className="p-2"><div className="h-3 w-28 bg-gray-800 rounded animate-pulse" /></td>
                  <td className="p-2"><div className="h-3 w-20 bg-gray-800 rounded animate-pulse" /></td>
                  <td className="p-2"><div className="h-3 w-10 bg-gray-800 rounded animate-pulse" /></td>
                  <td className="p-2"><div className="h-3 w-16 bg-gray-800 rounded animate-pulse" /></td>
                  <td className="p-2"><div className="h-3 w-12 bg-gray-800 rounded animate-pulse" /></td>
                  <td className="p-2"><div className="h-3 w-32 bg-gray-800 rounded animate-pulse" /></td>
                </tr>
              ))
            )}

            {items.map((it) => {
              const clickable = Boolean(it.signal_id);
              return (
                <tr
                  key={it.key}
                  className={`border-t border-gray-800 hover:bg-gray-800 ${clickable ? 'cursor-pointer' : ''}`}
                  onClick={() => {
                    if (it.signal_id) props.onOpen(it.signal_id);
                  }}
                >
                  <td className="p-2 font-mono text-xs text-gray-300">{it.signal_id || '—'}</td>
                  <td className="p-2 font-medium">{it.symbol || ''}</td>
                  <td className="p-2">{it.tf || ''}</td>
                  <td className="p-2">{it.direction || ''}</td>
                  <td className="p-2">{it.rr == null || Number.isNaN(it.rr) ? '' : Number(it.rr).toFixed(2)}</td>
                  <td className="p-2 text-gray-400">{it.ts ? new Date(it.ts * 1000).toLocaleString() : ''}</td>
                </tr>
              );
            })}

            {!loading && !error && items.length === 0 && (
              <tr>
                <td className="p-3 text-gray-400" colSpan={6}>
                  No signals yet. When the engine produces signals, they will show up here.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
