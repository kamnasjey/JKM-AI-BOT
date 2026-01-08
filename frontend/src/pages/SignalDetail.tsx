import React, { useEffect, useMemo, useRef, useState } from 'react';

import { ChartBoard, type ChartBoardHandle } from '../components/ChartBoard';
import { apiGetJson } from '../lib/apiClient';
import type { EngineAnnotations } from '../drawing/types';

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

type SignalPayload = {
  signal_id: string;
  created_at: number;
  symbol: string;
  tf: string;
  direction: string;
  entry: number;
  sl: number;
  tp: number;
  rr: number;
  score?: number | null;
  reasons?: string[];
  explain?: any;
  engine_annotations?: EngineAnnotations;
};

export function SignalDetail(props: { signalId: string; onBack: () => void }) {
  const [payload, setPayload] = useState<SignalPayload | null>(null);
  const [status, setStatus] = useState<string>('');
  const chartRef = useRef<ChartBoardHandle | null>(null);

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
        const data = await apiGetJson<any>(`/api/signals/${encodeURIComponent(props.signalId)}`, { headers });
        if (cancelled) return;
        setPayload(data);
        setStatus('');
      } catch (e) {
        setStatus(`Error: ${String(e)}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [headers, props.signalId]);

  useEffect(() => {
    if (!payload?.engine_annotations) return;
    chartRef.current?.applyAnnotations(payload.engine_annotations);
  }, [payload]);

  const copyJson = async () => {
    if (!payload) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
      setStatus('Copied JSON');
      setTimeout(() => setStatus(''), 1200);
    } catch {
      setStatus('Copy failed');
      setTimeout(() => setStatus(''), 1200);
    }
  };

  if (!payload) {
    return (
      <div className="p-4 text-white">
        <button className="px-3 py-1 bg-gray-800 rounded border border-gray-700" onClick={props.onBack}>
          Back
        </button>
        <div className="mt-3 text-gray-400">{status || 'Loading…'}</div>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 relative">
        <ChartBoard ref={chartRef} symbol={payload.symbol} />
      </div>

      <div className="w-[420px] border-l border-gray-800 bg-gray-900 text-white overflow-auto">
        <div className="p-4 border-b border-gray-800">
          <div className="flex items-center justify-between">
            <button className="px-3 py-1 bg-gray-800 rounded border border-gray-700" onClick={props.onBack}>
              Back
            </button>
            <button className="px-3 py-1 bg-yellow-500 text-black font-semibold rounded" onClick={copyJson}>
              Copy JSON
            </button>
          </div>
          <div className="mt-3">
            <div className="text-lg font-semibold">{payload.symbol}</div>
            <div className="text-sm text-gray-300">
              {payload.direction} · {payload.tf} · RR {payload.rr.toFixed(2)}
              {payload.score == null ? '' : ` · Score ${Number(payload.score).toFixed(2)}`}
            </div>
            <div className="text-sm text-gray-400">
              {payload.created_at ? new Date(payload.created_at * 1000).toLocaleString() : ''}
            </div>
          </div>
        </div>

        <div className="p-4">
          <div className="text-sm font-semibold mb-2">Why</div>
          <ul className="text-sm text-gray-200 list-disc pl-5 space-y-1">
            {(payload.reasons || []).map((r, idx) => (
              <li key={idx}>{r}</li>
            ))}
            {(payload.reasons || []).length === 0 && <li className="text-gray-400">No reasons</li>}
          </ul>

          <div className="mt-4 text-sm font-semibold mb-2">Explain</div>
          <pre className="text-xs text-gray-200 whitespace-pre-wrap break-words bg-gray-950 border border-gray-800 rounded p-3">
            {JSON.stringify(payload.explain || {}, null, 2)}
          </pre>
        </div>

        {status && <div className="px-4 pb-4 text-sm text-gray-400">{status}</div>}
      </div>
    </div>
  );
}
