import type { Point, ToolId, UserShape } from './types';

export type HitTestResult = { id: string } | null;

export type ToolContext = {
  xToTime: (x: number) => number | null;
  yToPrice: (y: number) => number | null;
  timeToX: (time: number) => number | null;
  priceToY: (price: number) => number | null;
};

export type Pointer = {
  x: number;
  y: number;
};

export function newId(prefix: string) {
  return `${prefix}_${Math.random().toString(16).slice(2)}_${Date.now()}`;
}

export function toPoint(ctx: ToolContext, p: Pointer): Point | null {
  const time = ctx.xToTime(p.x);
  const price = ctx.yToPrice(p.y);
  if (time == null || price == null) return null;
  return { time, price };
}

function distPointToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number) {
  const abx = bx - ax;
  const aby = by - ay;
  const apx = px - ax;
  const apy = py - ay;
  const denom = abx * abx + aby * aby;
  const t = denom === 0 ? 0 : Math.max(0, Math.min(1, (apx * abx + apy * aby) / denom));
  const cx = ax + t * abx;
  const cy = ay + t * aby;
  const dx = px - cx;
  const dy = py - cy;
  return Math.sqrt(dx * dx + dy * dy);
}

export function hitTest(shapes: UserShape[], ctx: ToolContext, p: Pointer): HitTestResult {
  const threshold = 8;

  // top-most first
  for (let i = shapes.length - 1; i >= 0; i -= 1) {
    const s = shapes[i];

    if (s.kind === 'level') {
      const y = ctx.priceToY(s.price);
      if (y == null) continue;
      if (Math.abs(p.y - y) <= threshold) return { id: s.id };
    }

    if (s.kind === 'trendline') {
      const ax = ctx.timeToX(s.a.time);
      const ay = ctx.priceToY(s.a.price);
      const bx = ctx.timeToX(s.b.time);
      const by = ctx.priceToY(s.b.price);
      if (ax == null || ay == null || bx == null || by == null) continue;
      const d = distPointToSegment(p.x, p.y, ax, ay, bx, by);
      if (d <= threshold) return { id: s.id };
    }

    if (s.kind === 'zone') {
      const x1 = ctx.timeToX(Math.min(s.a.time, s.b.time));
      const x2 = ctx.timeToX(Math.max(s.a.time, s.b.time));
      const y1 = ctx.priceToY(Math.min(s.a.price, s.b.price));
      const y2 = ctx.priceToY(Math.max(s.a.price, s.b.price));
      if (x1 == null || x2 == null || y1 == null || y2 == null) continue;
      const left = Math.min(x1, x2);
      const right = Math.max(x1, x2);
      const top = Math.min(y1, y2);
      const bottom = Math.max(y1, y2);
      const inside = p.x >= left && p.x <= right && p.y >= top && p.y <= bottom;
      if (inside) return { id: s.id };
    }
  }

  return null;
}

export function setToolCursor(tool: ToolId): string {
  if (tool === 'select') return 'default';
  if (tool === 'level') return 'crosshair';
  if (tool === 'trendline') return 'crosshair';
  if (tool === 'zone') return 'crosshair';
  return 'default';
}
