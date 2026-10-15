import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { DatasetComponent, GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { Axis, CategoryMeta, Frames, MarketData, Metric, Mode, ValueTable } from './data';
import { rankAt, valueTable } from './data';
import { colorOf } from './colors';
import { exact, formatValue } from './format';

echarts.use([BarChart, DatasetComponent, GridComponent, TooltipComponent, CanvasRenderer]);

export interface RaceConfig {
  category: CategoryMeta;
  axis: Axis;
  metric: Metric;
  mode: Mode;
  topN: number;
  frames: Frames;
}

/** ECharts 公式の Bar Race 例に従ったバーチャートレース */
export class Race {
  private chart: echarts.ECharts;
  private cfg!: RaceConfig;
  private data: MarketData;
  private frame = 0;
  private stepMs = 1000;
  /** 指標（数量/金額）ごとの値テーブル。モードは cfg.mode に従う */
  private tables!: Record<Metric, ValueTable>;
  private monthlyQty!: ValueTable;

  constructor(el: HTMLElement, data: MarketData) {
    this.chart = echarts.init(el);
    this.data = data;
    window.addEventListener('resize', () => {
      this.chart.resize();
      if (this.cfg) this.chart.setOption(this.layout());
    });
  }

  setStepMs(ms: number) {
    this.stepMs = ms;
    this.chart.setOption({
      animationDurationUpdate: ms,
      series: [{ id: 'race', animationDurationUpdate: ms }],
    });
  }

  /** 大品目・軸・指標・件数のいずれかが変わったとき、グラフを作り直す */
  configure(cfg: RaceConfig, frame = 0) {
    this.cfg = cfg;
    const { category: c, axis: a, frames: f } = cfg;
    this.tables = {
      qty: valueTable(this.data, c.name, a, 'qty', cfg.mode, f),
      amt: valueTable(this.data, c.name, a, 'amt', cfg.mode, f),
    };
    this.monthlyQty = valueTable(this.data, c.name, a, 'qty', 'month', f);
    this.frame = Math.min(frame, cfg.frames.months.length - 1);
    const unit = cfg.category.qty_unit;
    const { metric, topN } = cfg;
    const fmt = (v: number) => formatValue(v, metric, unit);
    this.chart.clear();
    this.chart.setOption({
      animationDuration: 0,
      animationDurationUpdate: this.stepMs,
      animationEasing: 'linear',
      animationEasingUpdate: 'linear',
      ...this.layout(),
      tooltip: {
        trigger: 'item',
        confine: true,
        formatter: (p: any) => this.tooltip(p.value[0] as string),
      },
      dataset: { source: this.rows() },
      xAxis: {
        max: 'dataMax',
        axisLabel: { formatter: (v: number) => fmt(v), fontSize: 12 },
        name: (cfg.mode === 'cum' ? '累計 ' : '') + (metric === 'amt' ? '円' : unit),
        nameLocation: 'end',
      },
      yAxis: {
        type: 'category',
        inverse: true,
        max: topN - 1,
        // 項目名は左の固定幅ガターに右寄せで収め、棒（grid 内）と重ならないようにする
        axisLabel: { ...this.layout().yAxis.axisLabel },
        axisLine: { show: false },
        axisTick: { show: false },
        animationDuration: 300,
        animationDurationUpdate: 300,
      },
      series: [
        {
          id: 'race',
          type: 'bar',
          realtimeSort: true,
          encode: { x: 'value', y: 'name' },
          seriesLayoutBy: 'column',
          itemStyle: { color: (p: any) => colorOf(p.value[0] as string) },
          label: {
            show: true,
            position: 'right',
            fontSize: 14,
            valueAnimation: true,
            formatter: (p: any) => fmt(p.value[1] as number),
          },
          animationDuration: 0,
          animationDurationUpdate: this.stepMs,
        },
      ],
    });
  }

  /** 項目名ガターの幅は画面幅に応じて固定する。grid は左端をガター幅だけ空ける */
  private layout() {
    const w = this.chart.getWidth();
    const gutter = Math.round(Math.min(150, Math.max(92, w * 0.3)));
    return {
      grid: { top: 8, bottom: 28, left: gutter, right: 84, containLabel: false },
      yAxis: {
        axisLabel: {
          show: true,
          fontSize: 14,
          width: gutter - 14,
          overflow: 'truncate' as const,
          ellipsis: '…',
          align: 'right' as const,
          margin: 10,
          interval: 0,
        },
      },
    };
  }

  get currentFrame() {
    return this.frame;
  }

  setFrame(i: number) {
    this.frame = i;
    this.chart.setOption({ dataset: { source: this.rows() } });
  }

  /** 現在のフレームの値テーブル（指標に対応）。ダッシュボード側のキャプション判定でも使う */
  get table(): ValueTable {
    return this.tables[this.cfg.metric];
  }

  private rows(): (string | number)[][] {
    const rows: (string | number)[][] = [['name', 'value']];
    for (const name of this.cfg.frames.names) {
      // TOP20 圏外（null）は 0 として渡す。TOP10 表示では棒として現れない
      rows.push([name, this.table.get(name)?.[this.frame] ?? 0]);
    }
    return rows;
  }

  private tooltip(name: string): string {
    const { frames, category, axis, mode } = this.cfg;
    const mi = frames.monthIdx[this.frame];
    const unit = category.qty_unit;
    const s = this.data[axis][category.name]?.[name];
    const rel = (axis === 'items' ? s?.origins : s?.items)?.[mi];
    const relLabel = axis === 'items' ? '主要産地' : '主要品目';
    const none = mode === 'cum' ? '未集計' : 'TOP20圏外';
    const rankOf = (f: number) => rankAt(this.table, f).get(name);
    const rank = rankOf(this.frame);
    let rankLine = rank ? `${rank}位` : none;
    if (this.frame > 0) {
      const pr = rankOf(this.frame - 1);
      const consecutive = mi - frames.monthIdx[this.frame - 1] === 1;
      rankLine += `（${consecutive ? '前月' : '前回'} ${pr ? `${pr}位` : none}）`;
    }
    const pre = mode === 'cum' ? '累計' : '';
    const lines = [
      `<b>${name}</b>`,
      `順位: ${rankLine}`,
      `${pre}数量: ${exact(this.tables.qty.get(name)?.[this.frame], unit)}`,
      `${pre}金額: ${exact(this.tables.amt.get(name)?.[this.frame], '円')}`,
    ];
    if (mode === 'cum') lines.push(`当月数量: ${exact(this.monthlyQty.get(name)?.[this.frame], unit)}`);
    if (rel && rel.length) lines.push(`${relLabel}: ${rel.slice(0, 3).join('、')}`);
    return lines.join('<br>');
  }

  dispose() {
    this.chart.dispose();
  }
}
