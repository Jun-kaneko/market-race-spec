// 項目名から色を固定する。入れ替わっても同じ品目は同じ色
const PALETTE = [
  '#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f', '#edc948',
  '#b07aa1', '#ff9da7', '#9c755f', '#bab0ac', '#2f6f8f', '#d4742c',
];

function hash(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h;
}

export function colorOf(name: string): string {
  return PALETTE[hash(name) % PALETTE.length];
}
