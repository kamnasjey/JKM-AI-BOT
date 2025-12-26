import type { UserShape } from './types';

const STORAGE_KEY = 'jkm_chart_drawings_v1';

type StoredPayload = {
  version: 1;
  savedAt: number;
  shapes: UserShape[];
};

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function isValidShape(value: unknown): value is UserShape {
  if (!isObject(value)) return false;
  const kind = value.kind;
  if (kind !== 'level' && kind !== 'trendline' && kind !== 'zone') return false;
  if (typeof value.id !== 'string') return false;
  if (typeof value.createdAt !== 'number') return false;

  if (kind === 'level') {
    return typeof value.price === 'number' && Number.isFinite(value.price);
  }

  const a = (value as any).a;
  const b = (value as any).b;
  return (
    isObject(a) &&
    isObject(b) &&
    typeof (a as any).time === 'number' &&
    typeof (a as any).price === 'number' &&
    typeof (b as any).time === 'number' &&
    typeof (b as any).price === 'number'
  );
}

export function saveDrawings(shapes: UserShape[]): void {
  const payload: StoredPayload = {
    version: 1,
    savedAt: Date.now(),
    shapes,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

export function loadDrawings(): UserShape[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!isObject(parsed) || parsed.version !== 1 || !Array.isArray(parsed.shapes)) return [];
    return parsed.shapes.filter(isValidShape);
  } catch {
    return [];
  }
}

export function clearDrawings(): void {
  localStorage.removeItem(STORAGE_KEY);
}
