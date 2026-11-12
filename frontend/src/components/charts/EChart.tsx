import { BarChart, LineChart } from "echarts/charts";
import {
  AriaComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import type { EChartsCoreOption } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

echarts.use([
  BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, MarkAreaComponent, MarkLineComponent,
  DataZoomComponent, AriaComponent, SVGRenderer,
]);

/**
 * One chart. `label` describes it to assistive technology; the figures themselves are always available in a table
 * or in the text next to the chart, so nothing is conveyed by the drawing alone.
 */
export function EChart({ option, height = 320, label }: { option: EChartsCoreOption; height?: number; label: string }) {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const node = element.current;
    if (!node) return;
    const instance = echarts.init(node, undefined, { renderer: "svg" });
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(node);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, true);
  }, [option]);

  return <div ref={element} role="img" aria-label={label} style={{ height }} className="w-full" />;
}

export default EChart;
