import type { EChartsCoreOption } from "echarts/core";
import { lazy, Suspense } from "react";

// The charting library is the largest part of the application: it is loaded only when a chart is shown.
const EChart = lazy(() => import("./EChart"));

export function Chart({ option, height = 320, label }: { option: EChartsCoreOption; height?: number; label: string }) {
  return (
    <Suspense fallback={<div style={{ height }} className="grid place-items-center text-sm text-ink-500" role="status">Loading the chart…</div>}>
      <EChart option={option} height={height} label={label} />
    </Suspense>
  );
}
