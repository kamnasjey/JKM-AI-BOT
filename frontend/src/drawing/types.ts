export type UTCTimestampSeconds = number;

export type ToolId = 'select' | 'level' | 'trendline' | 'zone';

export type Point = {
  time: UTCTimestampSeconds;
  price: number;
};

export type ShapeBase = {
  id: string;
  kind: 'level' | 'trendline' | 'zone';
  createdAt: number;
  label?: string;
};

export type LevelShape = ShapeBase & {
  kind: 'level';
  price: number;
};

export type TrendlineShape = ShapeBase & {
  kind: 'trendline';
  a: Point;
  b: Point;
};

export type ZoneShape = ShapeBase & {
  kind: 'zone';
  a: Point;
  b: Point;
};

export type UserShape = LevelShape | TrendlineShape | ZoneShape;

export type EngineLevel = { price: number; label?: string };
export type EngineZone = { priceFrom: number; priceTo: number; label?: string };

export type EngineAnnotations = {
  levels?: EngineLevel[];
  zones?: EngineZone[];
  fiboZones?: EngineZone[];
};

export type EngineShape =
  | (LevelShape & { readonly: true; color: 'gold' })
  | (ZoneShape & { readonly: true; color: 'green' | 'gold' });
