import type {Marker} from './types';

// A chart request has a 30,000-candle backend safety limit. Keep windows
// comfortably smaller so multi-pane indicators and condition scores stay responsive.
export const MAX_CHART_CANDLES = 8_000;

export type ChartWindow = {
  start: string;
  end: string; // Exclusive UTC boundary, like the backtest request.
  index: number; // 0 is the newest window.
  total: number;
};

export function calculateChartWindow(
  rangeStart: string,
  rangeEnd: string,
  timeframeMinutes: number,
  olderWindows = 0,
): ChartWindow {
  const start = Date.parse(rangeStart);
  const end = Date.parse(rangeEnd);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    throw new Error('Invalid chart date range');
  }
  if (!Number.isFinite(timeframeMinutes) || timeframeMinutes <= 0) {
    throw new Error('Invalid chart timeframe');
  }
  const duration = MAX_CHART_CANDLES * timeframeMinutes * 60_000;
  const total = Math.max(1, Math.ceil((end - start) / duration));
  const index = Math.min(total - 1, Math.max(0, Math.trunc(Number(olderWindows) || 0)));
  const windowEnd = end - index * duration;
  const windowStart = Math.max(start, windowEnd - duration);
  return {
    start: new Date(windowStart).toISOString(),
    end: new Date(windowEnd).toISOString(),
    index,
    total,
  };
}

export function markersInWindow(markers: Marker[], window: ChartWindow): Marker[] {
  const from = Date.parse(window.start) / 1000;
  const until = Date.parse(window.end) / 1000;
  return markers.filter(m => Number.isFinite(m.time) && m.time >= from && m.time < until);
}
