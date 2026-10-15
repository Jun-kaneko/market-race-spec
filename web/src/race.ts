import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { DatasetComponent, GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { Axis, CategoryMeta, Frames, MarketData, Metric } from './data';
import { colorOf } from './colors';
import { exact, formatValue } from './format';

echarts.use([BarChart, DatasetComponent, GridComponent, TooltipComponent, CanvasRenderer]);

export interface RaceConfig {
  category: CategoryMeta;
  axis: Axis;
  metric: Metric;
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

  constructor(el: HTMLElement, data: MarketData) {
    this.chart = echarts.init(el);
    this.data = data;
    window.addEventListener('resize', () => this.chart.resize());
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
      grid: { top: 8, bottom: 28, left: 8, right: 76, containLabel: true },
      tooltip: {
        trigger: 'item',
        confine: true,
        formatter: (p: any) => this.tooltip(p.value[0] as string),
      },
      dataset: { source: this.rows() },
      xAxis: {
        max: 'dataMax',
        axisLabel: { formatter: (v: number) => fmt(v), fontSize: 12 },
        name: metric === 'amt' ? '円' : unit,
        nameLocation: 'end',
      },
      yAxis: {
        type: 'category',
        inverse: true,
        max: topN - 1,
        axisLabel: { show: true, fontSize: 14, width: 96, overflow: 'truncate' },
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

  get currentFrame() {
    return this.frame;
  }

  setFrame(i: number) {
    this.frame = i;
    this.chart.setOption({ dataset: { source: this.rows() } });
  }

  private seriesOf(name: string) {
    return this.data[this.cfg.axis][this.cfg.category.name]?.[name];
  }

  private rows(): (string | number)[][] {
    const { frames, metric } = this.cfg;
    const mi = frames.monthIdx[this.frame];
    const rows: (string | number)[][] = [['name', 'value']];
    for (const name of frames.names) {
      // TOP20 圏外（null）は 0 として渡す。TOP10 表示では棒として現れない
      rows.push([name, this.seriesOf(name)?.[metric][mi] ?? 0]);
    }
    return rows;
  }

  private tooltip(name: string): string {
    const { frames, category, axis } = this.cfg;
    const s = this.seriesOf(name);
    const mi = frames.monthIdx[this.frame];
    const unit = category.qty_unit;
    const rel = (axis === 'items' ? s?.origins : s?.items)?.[mi];
    const relLabel = axis === 'items' ? '主要産地' : '主要品目';
    return [
      `<b>${name}</b>`,
      `数量: ${exact(s?.qty[mi], unit)}`,
      `金額: ${exact(s?.amt[mi], '円')}`,
      rel && rel.length ? `${relLabel}: ${rel.slice(0, 3).join('、')}` : '',
    ].filter(Boolean).join('<br>');
  }

  dispose() {
    this.chart.dispose();
  }
}
