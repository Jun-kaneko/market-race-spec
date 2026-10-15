import type { Metric } from './data';

/** 数量: kg は t に、金額: 円は万円/億円に丸めて読みやすくする */
export function formatValue(v: number, metric: Metric, unit: string): string {
  if (metric === 'amt') {
    if (v >= 1e8) return `${(v / 1e8).toFixed(2)}億円`;
    return `${Math.round(v / 1e4).toLocaleString('ja-JP')}万円`;
  }
  if (unit === 'kg') {
    return v >= 1000 ? `${(v / 1000).toFixed(1)}t` : `${Math.round(v).toLocaleString('ja-JP')}kg`;
  }
  return `${Math.round(v).toLocaleString('ja-JP')}${unit}`;
}

export function exact(v: number | null | undefined, unit: string): string {
  return v == null ? '—' : `${Math.round(v).toLocaleString('ja-JP')}${unit}`;
}
