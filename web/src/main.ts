import './style.css';
import { buildFrames, formatMonth, loadData } from './data';
import type { Axis, MarketData, Metric, Mode } from './data';
import { buildCaptions } from './captions';
import { seasonOf } from './season';
import { Race } from './race';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

async function main() {
  let data: MarketData;
  try {
    data = await loadData();
  } catch (e) {
    $('chart').textContent = String(e);
    return;
  }

  const catSel = $<HTMLSelectElement>('category');
  const axisSel = $<HTMLSelectElement>('axis');
  const metricSel = $<HTMLSelectElement>('metric');
  const modeSel = $<HTMLSelectElement>('mode');
  const topSel = $<HTMLSelectElement>('topn');
  const speedSel = $<HTMLSelectElement>('speed');
  const playBtn = $<HTMLButtonElement>('play');
  const restartBtn = $<HTMLButtonElement>('restart');
  const slider = $<HTMLInputElement>('slider');
  const monthEl = $('month');
  const notice = $('notice');
  const captionsEl = $('captions');
  const stageEl = document.querySelector<HTMLElement>('.stage')!;
  const seasonIcon = $('season-icon');
  const seasonLabel = $('season-label');

  for (const c of data.meta.categories) catSel.add(new Option(c.name, c.name));
  catSel.value = '生鮮水産物';

  const race = new Race($('chart'), data);
  let timer: number | undefined;
  let total = 0;
  let currentMonth = '';

  const stepMs = () => 1000 / Number(speedSel.value);

  function showFrame(i: number) {
    race.setFrame(i);
    slider.value = String(i);
    const f = currentFrames();
    currentMonth = f.months[i];
    monthEl.textContent = formatMonth(currentMonth);
    const se = seasonOf(currentMonth);
    if (seasonIcon.textContent !== se.icon) {
      seasonIcon.textContent = se.icon;
      seasonIcon.classList.remove('pop');
      void seasonIcon.offsetWidth; // アニメーションを再始動
      seasonIcon.classList.add('pop');
    }
    seasonLabel.textContent = `${se.season}・${se.motif}`;
    stageEl.style.setProperty('--stage-bg', se.tint);
    const caps = buildCaptions(race.table, modeSel.value as Mode, f, i, Number(topSel.value));
    captionsEl.replaceChildren(
      ...caps.map((t) => Object.assign(document.createElement('li'), { textContent: t })),
    );
  }

  function currentFrames() {
    return buildFrames(data, catSel.value, axisSel.value as Axis);
  }

  function updateNotice() {
    const f = currentFrames();
    const cat = data.meta.categories.find((c) => c.name === catSel.value)!;
    const lines: string[] = [];
    if (metricSel.value === 'amt') {
      lines.push('金額は「数量上位20位の中での金額順」です。金額が大きくても数量が少ない品目は含まれない場合があります。');
    }
    if (modeSel.value === 'cum') {
      lines.push('累計は「TOP20 に入った月」の合計です。圏外の月は含まれないため、実際の累計より少なく出る品目があります。');
    }
    if (cat.first_month > data.meta.months[0]) {
      lines.push(`${cat.name}は ${formatMonth(cat.first_month)} からのデータです。`);
    }
    if (f.skipped.length) {
      lines.push(`${f.skipped.map(formatMonth).join('、')}は元データの欠損のため表示を飛ばしています。`);
    }
    notice.hidden = lines.length === 0;
    notice.innerHTML = lines.join('<br>');
  }

  function stop() {
    if (timer !== undefined) window.clearTimeout(timer);
    timer = undefined;
    playBtn.textContent = '▶ 再生';
  }

  function tick() {
    const next = race.currentFrame + 1;
    if (next >= total) {
      stop();
      return;
    }
    showFrame(next);
    timer = window.setTimeout(tick, stepMs());
  }

  function play() {
    if (race.currentFrame >= total - 1) showFrame(0);
    playBtn.textContent = '⏸ 一時停止';
    timer = window.setTimeout(tick, stepMs());
  }

  /** 設定変更時: 再生を止め、同じ月（なければ先頭）からグラフを作り直す */
  function rebuild(keepMonth: boolean) {
    stop();
    const prevMonth = keepMonth ? currentMonth : undefined;
    const f = currentFrames();
    const category = data.meta.categories.find((c) => c.name === catSel.value)!;
    total = f.months.length;
    slider.max = String(total - 1);
    let frame = prevMonth ? f.months.indexOf(prevMonth) : 0;
    if (frame < 0) frame = 0;
    race.setStepMs(stepMs());
    race.configure({
      category,
      axis: axisSel.value as Axis,
      metric: metricSel.value as Metric,
      mode: modeSel.value as Mode,
      topN: Number(topSel.value),
      frames: f,
    }, frame);
    showFrame(frame);
    updateNotice();
  }

  [catSel, axisSel, metricSel, modeSel, topSel].forEach((el) =>
    el.addEventListener('change', () => {
      rebuild(el !== catSel);
    }),
  );
  speedSel.addEventListener('change', () => race.setStepMs(stepMs()));
  playBtn.addEventListener('click', () => (timer === undefined ? play() : stop()));
  restartBtn.addEventListener('click', () => {
    stop();
    showFrame(0);
    play();
  });
  slider.addEventListener('input', () => {
    stop();
    showFrame(Number(slider.value));
  });

  rebuild(false);
}

main();
