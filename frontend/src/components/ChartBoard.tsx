import {
  CandlestickSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import React, { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';

import { loadDrawings, saveDrawings } from '../drawing/storage';
import { renderOverlay } from '../drawing/renderer';
import {
  hitTest,
  newId,
  setToolCursor,
  toPoint,
  type Pointer,
  type ToolContext,
} from '../drawing/tools';
import type { EngineAnnotations, EngineShape, ToolId, UserShape } from '../drawing/types';

import { apiFetch, buildApiUrl } from '../lib/apiClient';

import './ChartBoard.css';

export type ChartBoardHandle = {
  applyAnnotations: (annotationsJson: EngineAnnotations) => void;
};

type InteractionState =
  | { mode: 'none' }
  | { mode: 'drawing'; tool: 'trendline' | 'zone'; start: { x: number; y: number } }
  | { mode: 'dragging'; id: string; start: { x: number; y: number }; original: UserShape };

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

function nowSec(): number {
  return Math.floor(Date.now() / 1000);
}

function normalizeTime(t: unknown): number | null {
  if (typeof t === 'number' && Number.isFinite(t)) return t;
  if (t && typeof t === 'object' && 'year' in (t as any)) {
    const bd = t as { year: number; month: number; day: number };
    const ms = Date.UTC(bd.year, bd.month - 1, bd.day);
    return Math.floor(ms / 1000);
  }
  return null;
}

function toWebSocketUrl(httpUrl: string): string {
  return httpUrl.replace(/^http:\/\//i, 'ws://').replace(/^https:\/\//i, 'wss://');
}

function getRelativePointer(ev: React.PointerEvent, host: HTMLElement): Pointer {
  const r = host.getBoundingClientRect();
  return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}

interface ChartBoardProps {
  symbol?: string; // Passed from parent
}

export const ChartBoard = forwardRef<ChartBoardHandle, ChartBoardProps>(function ChartBoard({ symbol: propSymbol }, ref) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const chartHostRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const candlesRef = useRef<CandlestickData<UTCTimestamp>[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  const interactionRef = useRef<InteractionState>({ mode: 'none' });

  const [tool, setTool] = useState<ToolId>('select');
  const [userShapes, setUserShapes] = useState<UserShape[]>(() => loadDrawings());
  const [engineShapes, setEngineShapes] = useState<EngineShape[]>([]);
  const [draftShape, setDraftShape] = useState<UserShape | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [chartReady, setChartReady] = useState(false);
  const [engineStatus, setEngineStatus] = useState<string>('');

  const symbol = useMemo(() => (propSymbol || getUrlParam('symbol') || 'XAUUSD').trim(), [propSymbol]);

  const style = useMemo(
    () => ({
      bg: '#0b1220',
      grid: 'rgba(255,255,255,0.08)',
      text: 'rgba(255,255,255,0.90)',
      user: 'rgba(255,255,255,0.86)',
      engineGold: '#f5c542',
      engineGreen: '#22c55e',
      selected: '#f5c542',
    }),
    [],
  );

  const toolCtx: ToolContext | null = useMemo(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return null;

    return {
      xToTime: (x) => {
        const t = chart.timeScale().coordinateToTime(x as any);
        return normalizeTime(t);
      },
      yToPrice: (y) => {
        const price = series.coordinateToPrice(y);
        return typeof price === 'number' && Number.isFinite(price) ? price : null;
      },
      timeToX: (time) => {
        const x = chart.timeScale().timeToCoordinate(time as any);
        return typeof x === 'number' && Number.isFinite(x) ? x : null;
      },
      priceToY: (price) => {
        const y = series.priceToCoordinate(price);
        return typeof y === 'number' && Number.isFinite(y) ? y : null;
      },
    };
  }, [chartReady]);

  const buildEngineShapes = (annotationsJson: EngineAnnotations): EngineShape[] => {
    const data = candlesRef.current;
    const t1 = data.at(0)?.time ? Number(data.at(0)!.time) : nowSec() - 3600;
    const t2 = data.at(-1)?.time ? Number(data.at(-1)!.time) : nowSec();

    const next: EngineShape[] = [];
    const levels = annotationsJson.levels || [];
    const zones = annotationsJson.zones || [];
    const fiboZones = annotationsJson.fiboZones || [];

    for (const lvl of levels) {
      if (typeof lvl.price !== 'number' || !Number.isFinite(lvl.price)) continue;
      next.push({
        id: newId('eng_lvl'),
        kind: 'level',
        createdAt: Date.now(),
        price: lvl.price,
        label: lvl.label,
        readonly: true,
        color: 'gold',
      });
    }

    for (const z of zones) {
      if (!Number.isFinite(z.priceFrom) || !Number.isFinite(z.priceTo)) continue;
      next.push({
        id: newId('eng_zone'),
        kind: 'zone',
        createdAt: Date.now(),
        a: { time: t1, price: z.priceFrom },
        b: { time: t2, price: z.priceTo },
        label: z.label,
        readonly: true,
        color: 'green',
      });
    }

    for (const z of fiboZones) {
      if (!Number.isFinite(z.priceFrom) || !Number.isFinite(z.priceTo)) continue;
      next.push({
        id: newId('eng_fibo'),
        kind: 'zone',
        createdAt: Date.now(),
        a: { time: t1, price: z.priceFrom },
        b: { time: t2, price: z.priceTo },
        label: z.label,
        readonly: true,
        color: 'gold',
      });
    }

    return next;
  };

  const syncEngine = async (): Promise<void> => {
    setEngineStatus('Syncing…');
    try {
      const token = getAuthToken();
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (token) headers.Authorization = `Bearer ${token}`;

      const url = `/api/chart/annotations?symbol=${encodeURIComponent(symbol)}`;
      const res = await apiFetch(url, { headers });
      if (!res.ok) {
        const text = await res.text();
        setEngineStatus(`Engine error: ${res.status} ${text}`);
        return;
      }
      const payload = (await res.json()) as any;
      const shapes = buildEngineShapes(payload);
      setEngineShapes(shapes);
      setEngineStatus(`Synced ${symbol}`);
    } catch (e) {
      setEngineStatus(`Engine error: ${String(e)}`);
    }
  };

  useImperativeHandle(ref, () => ({
    applyAnnotations: (annotationsJson) => {
      setEngineShapes(buildEngineShapes(annotationsJson));
    },
  }));

  // Persist user drawings
  useEffect(() => {
    saveDrawings(userShapes);
  }, [userShapes]);

  // Init chart
  useEffect(() => {
    if (!chartHostRef.current) return;
    if (chartRef.current) {
      // If chart already exists, just clear data if needed?
      // Actually we reconstruct on mount usually.
      // For changing symbol, we might keep chart instance but replace data.
      // But for simplicity let's destroy and recreate or just setData.
    } else {
      const host = chartHostRef.current;
      const chart = createChart(host, {
        autoSize: true,
        layout: {
          background: { color: '#0b1220' },
          textColor: 'rgba(255,255,255,0.78)',
        },
        grid: {
          vertLines: { color: 'rgba(255,255,255,0.06)' },
          horzLines: { color: 'rgba(255,255,255,0.06)' },
        },
        timeScale: {
          borderColor: 'rgba(255,255,255,0.12)',
          timeVisible: true,
          secondsVisible: false,
        },
        rightPriceScale: {
          borderColor: 'rgba(255,255,255,0.12)',
        },
        crosshair: {
          vertLine: { color: 'rgba(245,197,66,0.35)', width: 1 },
          horzLine: { color: 'rgba(245,197,66,0.35)', width: 1 },
        },
      });

      const series = chart.addSeries(CandlestickSeries, {
        upColor: '#22c55e',
        downColor: 'rgba(239,68,68,0.95)',
        borderVisible: false,
        wickUpColor: '#22c55e',
        wickDownColor: 'rgba(239,68,68,0.95)',
      });

      chartRef.current = chart;
      seriesRef.current = series;
      setChartReady(true);
    }

    // FETCH CACHED DATA
    const fetchData = async () => {
      if (!seriesRef.current) return;
      try {
        const res = await apiFetch(`/api/markets/${symbol}/candles?limit=1000`);
        if (res.ok) {
          const data = await res.json();
          const formatted = data.map((d: any) => {
            let t = d.time;
            if (typeof t === 'string') t = new Date(t).getTime() / 1000;
            if (t > 2000000000) t = t / 1000; // ms to sec
            return {
              time: t as UTCTimestamp,
              open: d.open,
              high: d.high,
              low: d.low,
              close: d.close,
            };
          }).sort((a: any, b: any) => a.time - b.time);

          seriesRef.current.setData(formatted);
          candlesRef.current = formatted;
          chartRef.current?.timeScale().fitContent();
        }
      } catch (e) {
        console.error("Fetch error", e);
      }
    };

    fetchData();

    // WEBSOCKET
    if (wsRef.current) wsRef.current.close();

    const wsBase = toWebSocketUrl(buildApiUrl(''));
    const wsUrl = `${wsBase.replace(/\/$/, '')}/ws/markets/${symbol}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      if (!seriesRef.current) return;
      try {
        const d = JSON.parse(ev.data);
        let t = d.time;
        if (t > 2000000000) t = t / 1000;
        const c: CandlestickData<UTCTimestamp> = {
          time: t as UTCTimestamp,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close
        };
        seriesRef.current.update(c);

        // Update internal ref so shapes can anchor correctly
        // Simplistic append, ideally we handle overwrites if time matches
        const last = candlesRef.current.at(-1);
        if (last && last.time === c.time) {
          candlesRef.current[candlesRef.current.length - 1] = c;
        } else {
          candlesRef.current.push(c);
        }
      } catch (e) { console.error("WS", e); }
    };

    return () => {
      // Don't destroy chart on symbol change necessarily, but clean up WS
      // destroy chart on unmount?
      ws.close();
      //   chart.remove(); // If we want to reuse container logic, maybe keep it.
      // But standard React way:
    };
  }, [symbol]);

  // Clean up chart on TOTAL unmount
  useEffect(() => {
    return () => {
      chartRef.current?.remove();
      chartRef.current = null;
    };
  }, []);

  // Resize canvas with container
  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;

    const ro = new ResizeObserver(() => {
      const r = wrap.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(r.width * dpr));
      canvas.height = Math.max(1, Math.floor(r.height * dpr));
      canvas.style.width = `${r.width}px`;
      canvas.style.height = `${r.height}px`;
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    });

    ro.observe(wrap);
    return () => ro.disconnect();
  }, []);

  // Render overlay when state changes
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctxObj = toolCtx;
    if (!canvas || !ctxObj) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const r = canvas.getBoundingClientRect();
    renderOverlay({
      ctx,
      width: r.width,
      height: r.height,
      coords: {
        timeToX: ctxObj.timeToX,
        priceToY: ctxObj.priceToY,
      },
      userShapes,
      engineShapes,
      draftShape,
      selectedId,
      style,
    });
  }, [toolCtx, userShapes, engineShapes, draftShape, selectedId, style]);

  function onPointerDown(ev: React.PointerEvent) {
    const host = wrapRef.current;
    const ctxObj = toolCtx;
    if (!host || !ctxObj) return;

    (ev.currentTarget as HTMLElement).setPointerCapture(ev.pointerId);

    const p = getRelativePointer(ev, host);

    if (tool === 'level') {
      const price = ctxObj.yToPrice(p.y);
      if (price == null) return;
      const s: UserShape = {
        id: newId('lvl'),
        kind: 'level',
        createdAt: Date.now(),
        price,
      };
      setUserShapes((prev) => [...prev, s]);
      setSelectedId(s.id);
      return;
    }

    if (tool === 'trendline' || tool === 'zone') {
      const startPoint = toPoint(ctxObj, p);
      if (!startPoint) return;

      const s: UserShape =
        tool === 'trendline'
          ? { id: newId('tl'), kind: 'trendline', createdAt: Date.now(), a: startPoint, b: startPoint }
          : { id: newId('zone'), kind: 'zone', createdAt: Date.now(), a: startPoint, b: startPoint };

      interactionRef.current = { mode: 'drawing', tool, start: p };
      setDraftShape(s);
      setSelectedId(null);
      return;
    }

    // select tool
    const hit = hitTest(userShapes, ctxObj, p);
    if (!hit) {
      setSelectedId(null);
      interactionRef.current = { mode: 'none' };
      return;
    }

    const shape = userShapes.find((s) => s.id === hit.id);
    if (!shape) return;

    setSelectedId(shape.id);
    interactionRef.current = { mode: 'dragging', id: shape.id, start: p, original: shape };
  }

  function onPointerMove(ev: React.PointerEvent) {
    const host = wrapRef.current;
    const ctxObj = toolCtx;
    if (!host || !ctxObj) return;

    const p = getRelativePointer(ev, host);
    const st = interactionRef.current;

    if (st.mode === 'drawing') {
      const pt = toPoint(ctxObj, p);
      if (!pt) return;

      setDraftShape((prev) => {
        if (!prev) return prev;
        if (prev.kind === 'trendline') return { ...prev, b: pt };
        if (prev.kind === 'zone') return { ...prev, b: pt };
        return prev;
      });
      return;
    }

    if (st.mode === 'dragging') {
      const startPt = toPoint(ctxObj, st.start);
      const nowPt = toPoint(ctxObj, p);
      if (!startPt || !nowPt) return;

      const dt = nowPt.time - startPt.time;
      const dp = nowPt.price - startPt.price;

      setUserShapes((prev) =>
        prev.map((s) => {
          if (s.id !== st.id) return s;
          const o = st.original;
          if (o.kind === 'level') {
            return { ...o, price: o.price + dp };
          }
          if (o.kind === 'trendline') {
            return {
              ...o,
              a: { time: o.a.time + dt, price: o.a.price + dp },
              b: { time: o.b.time + dt, price: o.b.price + dp },
            };
          }
          if (o.kind === 'zone') {
            return {
              ...o,
              a: { time: o.a.time + dt, price: o.a.price + dp },
              b: { time: o.b.time + dt, price: o.b.price + dp },
            };
          }
          return s;
        }),
      );
    }
  }

  function onPointerUp(ev: React.PointerEvent) {
    const host = wrapRef.current;
    const ctxObj = toolCtx;
    if (!host || !ctxObj) return;

    const st = interactionRef.current;
    if (st.mode === 'drawing') {
      const p = getRelativePointer(ev, host);
      const endPoint = toPoint(ctxObj, p);
      if (!endPoint) {
        setDraftShape(null);
        interactionRef.current = { mode: 'none' };
        return;
      }

      setDraftShape((prev) => {
        if (!prev) return null;
        const finalized: UserShape =
          prev.kind === 'trendline'
            ? { ...prev, b: endPoint }
            : prev.kind === 'zone'
              ? { ...prev, b: endPoint }
              : prev;

        setUserShapes((list) => [...list, finalized]);
        setSelectedId(finalized.id);
        return null;
      });

      interactionRef.current = { mode: 'none' };
      return;
    }

    interactionRef.current = { mode: 'none' };
  }

  function undo() {
    setUserShapes((prev) => prev.slice(0, -1));
    setSelectedId(null);
  }

  function clear() {
    setUserShapes([]);
    setSelectedId(null);
  }

  function save() {
    saveDrawings(userShapes);
    setSavedAt(Date.now());
  }

  return (
    <div className="chartboard">
      <div className="chartboard__toolbar">
        <div className="chartboard__toolgroup">
          <button
            className={`chartboard__btn ${tool === 'select' ? 'chartboard__btn--active' : ''}`}
            type="button"
            onClick={() => setTool('select')}
          >
            Select
          </button>
          <button
            className={`chartboard__btn ${tool === 'level' ? 'chartboard__btn--active' : ''}`}
            type="button"
            onClick={() => setTool('level')}
          >
            Level
          </button>
          <button
            className={`chartboard__btn ${tool === 'trendline' ? 'chartboard__btn--active' : ''}`}
            type="button"
            onClick={() => setTool('trendline')}
          >
            Trendline
          </button>
          <button
            className={`chartboard__btn ${tool === 'zone' ? 'chartboard__btn--active' : ''}`}
            type="button"
            onClick={() => setTool('zone')}
          >
            Zone
          </button>
        </div>

        <div className="chartboard__toolgroup">
          <button className="chartboard__btn" type="button" onClick={undo}>
            Undo
          </button>
          <button className="chartboard__btn chartboard__btn--danger" type="button" onClick={clear}>
            Clear
          </button>
          <button className="chartboard__btn" type="button" onClick={save}>
            Save
          </button>
          <button className="chartboard__btn" type="button" onClick={syncEngine}>
            Sync engine
          </button>
        </div>

        <div className="chartboard__meta">
          <span>Tool: <strong style={{ color: 'var(--jkm-gold)' }}>{tool}</strong></span>
          <span>Symbol: <strong style={{ color: 'var(--jkm-gold)' }}>{symbol}</strong></span>
          <span>
            User: {userShapes.length} • Engine: {engineShapes.length}
          </span>
          {savedAt ? <span>Saved {new Date(savedAt).toLocaleTimeString()}</span> : null}
          {engineStatus ? <span>{engineStatus}</span> : null}
        </div>
      </div>

      <div className="chartboard__canvasWrap" ref={wrapRef}>
        <div className="chartboard__chart" ref={chartHostRef} />
        <canvas
          className="chartboard__overlay"
          ref={canvasRef}
          style={{ cursor: setToolCursor(tool) }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        />
        <div className="chartboard__hint">
          Drawings: localStorage <strong>jkm_chart_drawings_v1</strong> • Engine overlays are readonly
        </div>
      </div>
    </div>
  );
});

