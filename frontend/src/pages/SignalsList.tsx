import React, { useEffect, useMemo, useState } from 'react';

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
  signal_id: string;
  created_at: number;
  symbol: string;
  tf: string;
  direction: string;
  rr: number;
  score?: number | null;
};

export function SignalsList(props: { onOpen: (signalId: string) => void }) {
  const [items, setItems] = useState<SignalListItem[]>([]);
  const [status, setStatus] = useState<string>('');

  const headers = useMemo(() => {
    const token = getAuthToken();
    const h: Record<string, string> = { Accept: 'application/json' };
    if (token) h.Authorization = `Bearer ${token}`;
    return h;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setStatus('Loading…');
      try {
        const res = await fetch('/api/signals?limit=50', { headers });
        if (!res.ok) {
          setStatus(`Error: ${res.status}`);
          return;
        }
        const data = (await res.json()) as any[];
        if (cancelled) return;
        const mapped = Array.isArray(data)
          ? data
              .map((x) => ({
                signal_id: String(x.signal_id || ''),
                created_at: Number(x.created_at || 0),
                symbol: String(x.symbol || ''),
                tf: String(x.tf || ''),
                direction: String(x.direction || ''),
                rr: Number(x.rr || 0),
                score: x.score == null ? null : Number(x.score),
              }))
              .filter((x) => x.signal_id)
          : [];
        setItems(mapped);
        setStatus(`Loaded ${mapped.length}`);
      } catch (e) {
        setStatus(`Error: ${String(e)}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [headers]);

  return (
    <div className="p-4 text-white">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">Signals</h2>
        <div className="text-sm text-gray-400">{status}</div>
      </div>

      <div className="overflow-auto border border-gray-700 rounded">
        <table className="w-full text-sm">
          <thead className="bg-gray-800 text-gray-200">
            <tr>
              <th className="text-left p-2">Symbol</th>
              <th className="text-left p-2">TF</th>
              <th className="text-left p-2">Side</th>
              <th className="text-left p-2">RR</th>
              <th className="text-left p-2">Score</th>
              <th className="text-left p-2">Time</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr
                key={it.signal_id}
                className="border-t border-gray-800 hover:bg-gray-800 cursor-pointer"
                onClick={() => props.onOpen(it.signal_id)}
              >
                <td className="p-2 font-medium">{it.symbol}</td>
                <td className="p-2">{it.tf}</td>
                <td className="p-2">{it.direction}</td>
                <td className="p-2">{it.rr.toFixed(2)}</td>
                <td className="p-2">{it.score == null ? '' : it.score.toFixed(2)}</td>
                <td className="p-2 text-gray-400">{it.created_at ? new Date(it.created_at * 1000).toLocaleString() : ''}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td className="p-3 text-gray-400" colSpan={6}>
                  No signals yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
