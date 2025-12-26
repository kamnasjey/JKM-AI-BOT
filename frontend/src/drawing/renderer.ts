import type { EngineShape, Point, UserShape } from './types';

export type CoordinateFns = {
  timeToX: (time: number) => number | null;
  priceToY: (price: number) => number | null;
};

export type RenderStyle = {
  bg: string;
  grid: string;
  text: string;
  user: string;
  engineGold: string;
  engineGreen: string;
  selected: string;
};

export type RenderInput = {
  ctx: CanvasRenderingContext2D;
  width: number;
  height: number;
  coords: CoordinateFns;
  userShapes: UserShape[];
  engineShapes: EngineShape[];
  draftShape: UserShape | null;
  selectedId: string | null;
  style: RenderStyle;
};

const HIT_LINE_WIDTH = 2;

function normalizeRect(a: Point, b: Point) {
  const x1 = Math.min(a.time, b.time);
  const x2 = Math.max(a.time, b.time);
  const y1 = Math.min(a.price, b.price);
  const y2 = Math.max(a.price, b.price);
  return { t1: x1, t2: x2, p1: y1, p2: y2 };
}

function drawLabel(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, color: string) {
  ctx.save();
  ctx.font = '12px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
  ctx.restore();
}

function drawLevel(ctx: CanvasRenderingContext2D, y: number, width: number, color: string) {
  ctx.beginPath();
  ctx.moveTo(0, y);
  ctx.lineTo(width, y);
  ctx.strokeStyle = color;
  ctx.lineWidth = HIT_LINE_WIDTH;
  ctx.stroke();
}

function drawTrendline(ctx: CanvasRenderingContext2D, ax: number, ay: number, bx: number, by: number, color: string) {
  ctx.beginPath();
  ctx.moveTo(ax, ay);
  ctx.lineTo(bx, by);
  ctx.strokeStyle = color;
  ctx.lineWidth = HIT_LINE_WIDTH;
  ctx.stroke();
}

function drawZone(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number, stroke: string, fill: string) {
  const left = Math.min(x1, x2);
  const right = Math.max(x1, x2);
  const top = Math.min(y1, y2);
  const bottom = Math.max(y1, y2);
  const w = Math.max(1, right - left);
  const h = Math.max(1, bottom - top);
  ctx.fillStyle = fill;
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.rect(left, top, w, h);
  ctx.fill();
  ctx.stroke();
}

function renderShape(ctx: CanvasRenderingContext2D, shape: UserShape | EngineShape, coords: CoordinateFns, width: number, selected: boolean, style: RenderStyle) {
  const isEngine = (shape as any).readonly === true;
  const baseColor = isEngine
    ? ((shape as any).color === 'green' ? style.engineGreen : style.engineGold)
    : style.user;

  const color = selected ? style.selected : baseColor;

  if (shape.kind === 'level') {
    const y = coords.priceToY(shape.price);
    if (y == null) return;
    drawLevel(ctx, y, width, color);
    if (shape.label) {
      drawLabel(ctx, 10, Math.max(14, y - 8), shape.label, color);
    }
    return;
  }

  if (shape.kind === 'trendline') {
    const ax = coords.timeToX(shape.a.time);
    const ay = coords.priceToY(shape.a.price);
    const bx = coords.timeToX(shape.b.time);
    const by = coords.priceToY(shape.b.price);
    if (ax == null || ay == null || bx == null || by == null) return;
    drawTrendline(ctx, ax, ay, bx, by, color);
    if (shape.label) {
      drawLabel(ctx, bx + 8, by, shape.label, color);
    }
    return;
  }

  if (shape.kind === 'zone') {
    const rect = normalizeRect(shape.a, shape.b);
    const x1 = coords.timeToX(rect.t1);
    const x2 = coords.timeToX(rect.t2);
    const y1 = coords.priceToY(rect.p1);
    const y2 = coords.priceToY(rect.p2);
    if (x1 == null || x2 == null || y1 == null || y2 == null) return;

    const fill = isEngine
      ? (shape as any).color === 'green'
        ? 'rgba(34, 197, 94, 0.18)'
        : 'rgba(245, 197, 66, 0.18)'
      : 'rgba(255, 255, 255, 0.10)';

    drawZone(ctx, x1, y1, x2, y2, color, fill);
    if (shape.label) {
      drawLabel(ctx, Math.min(x1, x2) + 10, Math.min(y1, y2) + 18, shape.label, color);
    }
  }
}

export function renderOverlay(input: RenderInput) {
  const { ctx, width, height, coords, userShapes, engineShapes, draftShape, selectedId, style } = input;

  ctx.clearRect(0, 0, width, height);

  // Engine annotations (under)
  for (const shape of engineShapes) {
    renderShape(ctx, shape, coords, width, false, style);
  }

  // User drawings
  for (const shape of userShapes) {
    const isSelected = selectedId != null && shape.id === selectedId;
    renderShape(ctx, shape, coords, width, isSelected, style);
  }

  // Draft (on top)
  if (draftShape) {
    ctx.save();
    ctx.setLineDash([6, 6]);
    renderShape(ctx, draftShape, coords, width, false, style);
    ctx.restore();
  }
}
