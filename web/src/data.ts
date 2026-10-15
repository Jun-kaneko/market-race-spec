// market.json の型と、フレーム（月）単位への変換

export type Axis = 'items' | 'origins';
export type Metric = 'qty' | 'amt';

export interface CategoryMeta {
  name: string;
  division: string;
  qty_unit: string;
  first_month: string;
}

export interface Series {
  qty: (number | null)[];
  amt: (number | null)[];
  origins?: (string[] | null)[];
  items?: (string[] | null)[];
}

export interface MarketData {
  meta: {
    generated: string;
    months: string[];
    categories: CategoryMeta[];
    missing: { items: Record<string, string[]>; origins: Record<string, string[]> };
  };
  items: Record<string, Record<string, Series>>;
  origins: Record<string, Record<string, Series>>;
}

export async function loadData(): Promise<MarketData> {
  const res = await fetch(`${import.meta.env.BASE_URL}data/market.json`);
  if (!res.ok) throw new Error(`market.json の取得に失敗しました (${res.status})`);
  return res.json();
}

export interface Frames {
  /** 再生対象の月（欠測月・花き部の開始前は除く） */
  months: string[];
  /** months と同じ並びの、全月配列上のインデックス */
  monthIdx: number[];
  names: string[];
  skipped: string[];
}

/** 大品目・軸ごとの再生フレームを作る。欠測月は飛ばす（0 に落とさない） */
export function buildFrames(data: MarketData, category: string, axis: Axis): Frames {
  const meta = data.meta.categories.find((c) => c.name === category)!;
  const missing = new Set(data.meta.missing[axis][category] ?? []);
  const months: string[] = [];
  const monthIdx: number[] = [];
  const skipped: string[] = [];
  data.meta.months.forEach((m, i) => {
    if (m < meta.first_month) return;
    if (missing.has(m)) {
      skipped.push(m);
      return;
    }
    months.push(m);
    monthIdx.push(i);
  });
  return { months, monthIdx, names: Object.keys(data[axis][category] ?? {}), skipped };
}

export function formatMonth(m: string): string {
  const [y, mo] = m.split('-');
  return `${y}年${Number(mo)}月`;
}

/** ある月の順位（1 始まり）。値が null の項目は含まない */
export function rankMap(
  data: MarketData,
  category: string,
  axis: Axis,
  metric: Metric,
  monthIdx: number,
): Map<string, number> {
  const rows: [string, number][] = [];
  for (const [name, s] of Object.entries(data[axis][category] ?? {})) {
    const v = s[metric][monthIdx];
    if (v != null) rows.push([name, v]);
  }
  rows.sort((a, b) => b[1] - a[1]);
  return new Map(rows.map(([name], i) => [name, i + 1]));
}
