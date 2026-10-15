import type { Frames, Mode, ValueTable } from './data';
import { formatMonth, rankAt } from './data';

const MAX_CAPTIONS = 2;
const SURGE_RATIO = 3;
const TOP_ENTRY = 10;

/**
 * 出来事の自動キャプション（SPEC 6.4）。優先順: 1位交代 > 急増 > TOP10新規入り。
 * 最初のフレームは判定しない。急増は表示中の TOP N に入っている項目だけを対象にし、
 * 累計モードでは「急増」を判定しない（累計は単調に増えるため意味を持たない）。
 */
export function buildCaptions(
  table: ValueTable,
  mode: Mode,
  frames: Frames,
  frame: number,
  topN: number,
): string[] {
  if (frame <= 0) return [];
  const cur = rankAt(table, frame);
  const prev = rankAt(table, frame - 1);
  // 欠測月を挟んだ場合は「前月」と書かず、比較対象の月を明示する
  const consecutive = frames.monthIdx[frame] - frames.monthIdx[frame - 1] === 1;
  const prevLabel = consecutive ? '前月' : formatMonth(frames.months[frame - 1]);
  const cum = mode === 'cum';

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
  if (top && prevTop && top !== prevTop) {
    push(top, cum ? `${top}が累計1位に（${prevTop}を逆転）` : `${top}が1位に（${prevLabel}は${prevTop}）`);
  }

  // 2. 急増（比率の大きい順）。月次のみ
  if (!cum) {
    const surges: [string, number][] = [];
    for (const [name, rank] of cur) {
      if (rank > topN) continue;
      const c = table.get(name)?.[frame];
      const p = table.get(name)?.[frame - 1];
      if (c != null && p != null && p > 0 && c >= p * SURGE_RATIO) surges.push([name, c / p]);
    }
    surges.sort((a, b) => b[1] - a[1]);
    for (const [name, ratio] of surges) {
      push(name, `${name}が急増（${prevLabel}比 ${ratio.toFixed(1)}倍）`);
    }
  }

  // 3. TOP10 新規入り（順位の高い順）
  for (const [name, rank] of cur) {
    if (rank > TOP_ENTRY) break;
    const pr = prev.get(name);
    if (pr == null || pr > TOP_ENTRY) push(name, `${name}が${cum ? '累計' : ''}TOP${TOP_ENTRY}入り`);
  }
  return out;
}
