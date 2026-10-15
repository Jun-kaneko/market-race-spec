// 月 → 季節・モチーフ。季節性の強い品目の動きを読み取りやすくするための表示用

export interface Season {
  season: '春' | '夏' | '秋' | '冬';
  icon: string;
  motif: string;
  /** グラフ背景のごく薄い色（棒の固定色と干渉しないよう淡色） */
  tint: string;
}

const TINT = {
  春: '#fff1f5',
  夏: '#eaf7f6',
  秋: '#fff3e6',
  冬: '#eef3f9',
} as const;

const BY_MONTH: Record<number, [Season['season'], string, string]> = {
  1: ['冬', '⛄', '雪'],
  2: ['冬', '🌸', '梅'],
  3: ['春', '🌸', '桜'],
  4: ['春', '🌸', '桜'],
  5: ['春', '🎏', '鯉のぼり'],
  6: ['夏', '☔', '梅雨'],
  7: ['夏', '🎋', '七夕'],
  8: ['夏', '🌻', 'ひまわり'],
  9: ['秋', '🎑', '月見'],
  10: ['秋', '🍁', '紅葉'],
  11: ['秋', '🍂', '紅葉'],
  12: ['冬', '❄️', '雪'],
};

/** `YYYY-MM` から季節情報を返す */
export function seasonOf(month: string): Season {
  const m = Number(month.split('-')[1]);
  const [season, icon, motif] = BY_MONTH[m];
  return { season, icon, motif, tint: TINT[season] };
}
