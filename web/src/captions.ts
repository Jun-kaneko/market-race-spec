import type { Axis, Frames, MarketData, Metric } from './data';
import { formatMonth, rankMap } from './data';

const MAX_CAPTIONS = 2;
const SURGE_RATIO = 3;
const TOP_ENTRY = 10;

/**
 * 出来事の自動キャプション（SPEC 6.4）。優先順: 1位交代 > 急増 > TOP10新規入り。
 * 最初のフレームは判定しない。急増は表示中の TOP N に入っている項目だけを対象にする。
 */
export function buildCaptions(
  data: MarketData,
  category: string,
  axis: Axis,
  metric: Metric,
  frames: Frames,
  frame: number,
  topN: number,
): string[] {
  if (frame <= 0) return [];
  const mi = frames.monthIdx[frame];
  const pi = frames.monthIdx[frame - 1];
  const cur = rankMap(data, category, axis, metric, mi);
  const prev = rankMap(data, category, axis, metric, pi);
  const series = data[axis][category];
  // 欠測月を挟んだ場合は「前月」と書かず、比較対象の月を明示する
  const consecutive = mi - pi === 1;
  const prevLabel = consecutive ? '前月' : formatMonth(frames.months[frame - 1]);

  const out: string[] = [];
  const used = new Set<string>();
  const push = (name: string, text: string) => {
    if (out.length >= MAX_CAPTIONS || used.has(name)) return;
    used.add(name);
    out.push(text);
  };
  const nameAt = (m: Map<string, number>, rank: number) =>
    [...m.entries()].find(([, r]) => r === rank)?.[0];

  // 1. 1位交代
  const top = nameAt(cur, 1);
  const prevTop = nameAt(prev, 1);
  if (top && prevTop && top !== prevTop) push(top, `${top}が1位に（${prevLabel}は${prevTop}）`);

  // 2. 急増（比率の大きい順）
  const surges: [string, number][] = [];
  for (const [name, rank] of cur) {
    if (rank > topN) continue;
    const c = series[name]?.[metric][mi];
    const p = series[name]?.[metric][pi];
    if (c != null && p != null && p > 0 && c >= p * SURGE_RATIO) surges.push([name, c / p]);
  }
  surges.sort((a, b) => b[1] - a[1]);
  for (const [name, ratio] of surges) {
    push(name, `${name}が急増（${prevLabel}比 ${ratio.toFixed(1)}倍）`);
  }

  // 3. TOP10 新規入り（順位の高い順）
  for (const [name, rank] of cur) {
    if (rank > TOP_ENTRY) break;
    const pr = prev.get(name);
    if (pr == null || pr > TOP_ENTRY) push(name, `${name}がTOP${TOP_ENTRY}入り`);
  }
  return out;
}
