/**
 * Chart definitions, as pure functions of the engine's result.
 *
 * Two rules hold in every chart:
 *  - a missing value stays missing: it is passed to the chart as `null` and drawn as a gap, never as zero;
 *  - tooltips are built as DOM nodes with `textContent`, so no text from the server is ever parsed as HTML.
 */
import type { EChartsCoreOption } from "echarts/core";

import type {
  AnalysisResult,
  AttributionScope,
  EconomicsResult,
  PerformanceForecast,
  Series,
} from "../../api/types";
import { fmtDayShort, fmtEnergy, fmtMoney, fmtNumber, fmtPct, MISSING_LABEL } from "../../lib/format";
import { FACTOR_LABEL } from "../../lib/labels";

export const COLORS = {
  ink: "#13243a",
  expected: "#5f758d",
  actual: "#f3b524",
  loss: "#be123c",
  gain: "#047857",
  residual: "#a9b9ca",
  soiling: "#b9740b",
  rain: "#0284c7",
  grid: "#e4eaf1",
  axis: "#7f93a9",
  window: "rgba(19, 36, 58, 0.07)",
  flagged: "#be123c",
  normal: "#5f758d",
  forecast: ["#7c3aed", "#0f766e", "#b45309"],
} as const;

const FONT = '"IBM Plex Sans", system-ui, sans-serif';

const BASE = {
  animation: false,
  textStyle: { fontFamily: FONT, color: COLORS.ink },
  aria: { enabled: true },
};

const AXIS_STYLE = {
  axisLine: { lineStyle: { color: COLORS.axis } },
  axisLabel: { color: COLORS.expected, fontFamily: FONT },
  splitLine: { lineStyle: { color: COLORS.grid } },
};

type TooltipRow = [label: string, value: string, color?: string];

/** Tooltip content as DOM nodes: text is assigned with `textContent`, never interpreted as markup. */
export function tooltipNode(title: string, rows: TooltipRow[], note?: string): HTMLElement {
  const root = document.createElement("div");
  root.style.cssText = `font-family:${FONT};font-size:12px;line-height:1.5;color:${COLORS.ink};min-width:160px`;
  const head = document.createElement("div");
  head.style.cssText = "font-weight:600;margin-bottom:4px";
  head.textContent = title;
  root.appendChild(head);
  for (const [label, value, color] of rows) {
    const line = document.createElement("div");
    line.style.cssText = "display:flex;justify-content:space-between;gap:16px";
    const left = document.createElement("span");
    if (color) {
      const dot = document.createElement("span");
      dot.style.cssText = `display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px;background:${color}`;
      left.appendChild(dot);
    }
    left.appendChild(document.createTextNode(label));
    const right = document.createElement("span");
    right.style.cssText = "font-variant-numeric:tabular-nums;font-weight:500";
    right.textContent = value;
    line.append(left, right);
    root.appendChild(line);
  }
  if (note) {
    const foot = document.createElement("div");
    foot.style.cssText = "margin-top:4px;color:#5f758d;max-width:260px;white-space:normal";
    foot.textContent = note;
    root.appendChild(foot);
  }
  return root;
}

interface AxisParam {
  dataIndex: number;
}

function indexOf(params: unknown): number {
  const first = Array.isArray(params) ? (params[0] as AxisParam | undefined) : (params as AxisParam | undefined);
  return first?.dataIndex ?? 0;
}

function tooltip(build: (index: number) => HTMLElement) {
  return {
    trigger: "axis",
    axisPointer: { type: "shadow" },
    confine: true,
    borderColor: COLORS.grid,
    formatter: (params: unknown) => build(indexOf(params)),
  };
}

const orMissing = (text: string) => (text === "—" ? MISSING_LABEL : text);

// ----------------------------------------------------------------------------- energy: expected against actual

export function energyOption(result: AnalysisResult): EChartsCoreOption {
  const daily = result.gap.daily;
  const days = daily.map((d) => d.day);
  const window = result.gap.window;
  return {
    ...BASE,
    grid: { left: 64, right: 24, top: 60, bottom: 56 },
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 10, textStyle: { fontFamily: FONT } },
    tooltip: tooltip((i) => {
      const d = daily[i];
      if (!d) return tooltipNode("", []);
      return tooltipNode(
        fmtDayShort(d.day),
        [
          ["Expected", orMissing(fmtEnergy(d.expected_kwh)), COLORS.expected],
          ["Actual", orMissing(fmtEnergy(d.actual_kwh)), COLORS.actual],
          ["Gap", d.gap_kwh === null ? MISSING_LABEL : `${fmtEnergy(d.gap_kwh)} (${fmtPct(d.relative_gap_pct)})`],
        ],
        d.status !== "OK" ? `Day not compared: ${d.status.toLowerCase().replace(/_/g, " ")}.` : undefined,
      );
    }),
    xAxis: { type: "category", data: days, ...AXIS_STYLE, axisLabel: { ...AXIS_STYLE.axisLabel, formatter: fmtDayShort } },
    yAxis: {
      type: "value", name: "MWh per day", nameTextStyle: { color: COLORS.expected, fontFamily: FONT, align: "left" },
      ...AXIS_STYLE, axisLabel: { ...AXIS_STYLE.axisLabel, formatter: (v: number) => fmtNumber(v / 1000, 0) },
    },
    dataZoom: days.length > 120 ? [{ type: "slider", height: 18, bottom: 8 }] : undefined,
    series: [
      {
        name: "Actual energy", type: "bar", data: daily.map((d) => d.actual_kwh), itemStyle: { color: COLORS.actual },
        barMaxWidth: 14,
        markArea: {
          silent: true, itemStyle: { color: COLORS.window },
          label: { show: true, position: "insideTop", color: COLORS.expected, fontFamily: FONT, fontSize: 11 },
          data: [[{ name: "Assessment window", xAxis: window.start }, { xAxis: window.end }]],
        },
      },
      {
        name: "Expected energy (baseline)", type: "line", data: daily.map((d) => d.expected_kwh),
        showSymbol: false, connectNulls: false, lineStyle: { color: COLORS.expected, width: 2 }, itemStyle: { color: COLORS.expected },
      },
    ],
  };
}

// ----------------------------------------------------------------------------- performance index, with reference projections

export function performanceOption(result: AnalysisResult, forecast: PerformanceForecast | null): EChartsCoreOption {
  const daily = result.gap.daily;
  const projected = forecast?.evaluable ? forecast.methods : [];
  const future = projected[0]?.points.map((p) => p.day) ?? [];
  const days = [...daily.map((d) => d.day), ...future];
  const observed = daily.map((d) => (d.performance_index === null ? null : d.performance_index * 100));
  const pad = (values: (number | null)[]) => [...values, ...future.map(() => null)];
  const step = result.trend.step;
  const window = result.gap.window;

  return {
    ...BASE,
    grid: { left: 56, right: 24, top: 60, bottom: 40 },
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 10, textStyle: { fontFamily: FONT } },
    tooltip: tooltip((i) => {
      const day = days[i] ?? "";
      if (i < daily.length) {
        return tooltipNode(fmtDayShort(day), [["Performance index", orMissing(fmtPct(observed[i], 1)), COLORS.ink]]);
      }
      const rows: TooltipRow[] = projected.map((m, k) => [
        m.label, fmtPct(m.points[i - daily.length]?.value, 1), COLORS.forecast[k % COLORS.forecast.length],
      ]);
      return tooltipNode(fmtDayShort(day), rows, "Unvalidated reference projection. Not used by any decision.");
    }),
    xAxis: { type: "category", data: days, ...AXIS_STYLE, axisLabel: { ...AXIS_STYLE.axisLabel, formatter: fmtDayShort } },
    yAxis: {
      type: "value", name: "actual / expected, %", scale: true,
      nameTextStyle: { color: COLORS.expected, fontFamily: FONT, align: "left" }, ...AXIS_STYLE,
    },
    series: [
      {
        name: "Performance index", type: "line", data: pad(observed), connectNulls: false, showSymbol: daily.length <= 62,
        symbolSize: 4, lineStyle: { color: COLORS.ink, width: 2 }, itemStyle: { color: COLORS.ink },
        markLine: {
          silent: true, symbol: "none", lineStyle: { color: COLORS.axis, type: "dashed" },
          label: { color: COLORS.expected, fontFamily: FONT, fontSize: 11 },
          data: [
            { yAxis: 100, name: "baseline", label: { formatter: "baseline", position: "insideEndTop" } },
            ...(step?.material ? [{ xAxis: step.day, name: "step", label: { formatter: "step change" } }] : []),
          ],
        },
        markArea: {
          silent: true, itemStyle: { color: COLORS.window },
          data: [[{ xAxis: window.start }, { xAxis: window.end }]],
        },
      },
      ...projected.map((method, k) => ({
        name: `${method.label} (unvalidated projection)`, type: "line",
        data: [...daily.map(() => null), ...method.points.map((p) => p.value)],
        showSymbol: false, lineStyle: { color: COLORS.forecast[k % COLORS.forecast.length], width: 1.5, type: "dashed" },
        itemStyle: { color: COLORS.forecast[k % COLORS.forecast.length] },
      })),
    ],
  };
}

// ----------------------------------------------------------------------------- loss attribution: from expected to actual

export interface BridgeStep {
  label: string;
  /** Energy removed (+) or added (-) at this step [kWh]; `null` for the two totals. */
  delta: number | null;
  /** Level before the step [kWh]. */
  from: number;
  /** Level after the step [kWh]. */
  to: number;
  kind: "total" | "factor" | "residual";
}

/** Expected -> each quantified factor -> unexplained residual -> actual. Unquantified factors are not drawn. */
export function bridgeSteps(scope: AttributionScope): BridgeStep[] {
  const steps: BridgeStep[] = [];
  if (scope.expected_kwh === null || scope.actual_kwh === null) return steps;
  let level = scope.expected_kwh;
  steps.push({ label: "Expected", delta: null, from: 0, to: level, kind: "total" });
  for (const c of scope.contributions) {
    const value = c.energy.value;
    if (value === null || (c.status !== "QUANTIFIED" && c.status !== "PARTIALLY_QUANTIFIED")) continue;
    steps.push({ label: FACTOR_LABEL[c.factor] ?? c.factor, delta: value, from: level, to: level - value, kind: "factor" });
    level -= value;
  }
  if (scope.residual_kwh !== null) {
    steps.push({ label: "Unexplained", delta: scope.residual_kwh, from: level, to: level - scope.residual_kwh, kind: "residual" });
  }
  steps.push({ label: "Actual", delta: null, from: 0, to: scope.actual_kwh, kind: "total" });
  return steps;
}

export function attributionOption(scope: AttributionScope): EChartsCoreOption {
  const steps = bridgeSteps(scope);
  const lows = steps.map((s) => Math.min(s.from, s.to));
  const heights = steps.map((s) => Math.abs(s.to - s.from));
  const floor = steps.length ? Math.min(...steps.map((s) => (s.kind === "total" ? s.to : Math.min(s.from, s.to)))) : 0;
  // Start the axis below the smallest level so that losses of a few per cent remain visible.
  const axisMin = Math.max(0, floor - (Math.max(...steps.map((s) => s.to), 0) - floor) * 0.6);
  const color = (s: BridgeStep) =>
    s.kind === "total" ? COLORS.ink : s.kind === "residual" ? COLORS.residual : (s.delta ?? 0) >= 0 ? COLORS.loss : COLORS.gain;

  return {
    ...BASE,
    grid: { left: 64, right: 24, top: 24, bottom: 64 },
    tooltip: tooltip((i) => {
      const s = steps[i];
      if (!s) return tooltipNode("", []);
      if (s.kind === "total") return tooltipNode(s.label, [["Energy", fmtEnergy(s.to)]]);
      const share = scope.expected_kwh ? ((s.delta ?? 0) / scope.expected_kwh) * 100 : null;
      return tooltipNode(
        s.label,
        [[(s.delta ?? 0) >= 0 ? "Loss" : "Gain", `${fmtEnergy(Math.abs(s.delta ?? 0))} (${fmtPct(share === null ? null : Math.abs(share), 2)} of expected)`]],
        s.kind === "residual" ? "What remains after every quantified factor. Never assigned to soiling by default." : undefined,
      );
    }),
    xAxis: {
      type: "category", data: steps.map((s) => s.label), ...AXIS_STYLE,
      axisLabel: { ...AXIS_STYLE.axisLabel, interval: 0, width: 84, overflow: "break", lineHeight: 14 },
    },
    yAxis: {
      type: "value", name: "MWh", min: axisMin, nameTextStyle: { color: COLORS.expected, fontFamily: FONT, align: "left" },
      ...AXIS_STYLE, axisLabel: { ...AXIS_STYLE.axisLabel, formatter: (v: number) => fmtNumber(v / 1000, 0) },
    },
    series: [
      {
        type: "bar", stack: "bridge", silent: true, itemStyle: { color: "transparent" },
        data: steps.map((s, i) => (s.kind === "total" ? axisMin : (lows[i] ?? 0))),
      },
      {
        type: "bar", stack: "bridge", barMaxWidth: 56,
        data: steps.map((s, i) => ({
          value: s.kind === "total" ? s.to - axisMin : (heights[i] ?? 0),
          itemStyle: { color: color(s) },
        })),
      },
    ],
  };
}

// ----------------------------------------------------------------------------- measured soiling and rain

export function hasSoilingSeries(result: AnalysisResult): boolean {
  return result.attribution.daily.some((d) => d.soiling_ratio !== null);
}

export function soilingOption(result: AnalysisResult): EChartsCoreOption {
  const daily = result.attribution.daily;
  const loss = daily.map((d) => (d.soiling_ratio === null ? null : (1 - d.soiling_ratio) * 100));
  const rain = daily.map((d) => d.precipitation_mm);
  const anyRain = rain.some((v) => v !== null);
  return {
    ...BASE,
    grid: { left: 56, right: anyRain ? 56 : 24, top: 60, bottom: 40 },
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 10, textStyle: { fontFamily: FONT } },
    tooltip: tooltip((i) => {
      const d = daily[i];
      if (!d) return tooltipNode("", []);
      const rows: TooltipRow[] = [["Measured soiling loss", orMissing(fmtPct(loss[i], 2)), COLORS.soiling]];
      if (anyRain) rows.push(["Rain", d.precipitation_mm === null ? MISSING_LABEL : `${fmtNumber(d.precipitation_mm, 1)} mm`, COLORS.rain]);
      return tooltipNode(fmtDayShort(d.day), rows);
    }),
    xAxis: { type: "category", data: daily.map((d) => d.day), ...AXIS_STYLE, axisLabel: { ...AXIS_STYLE.axisLabel, formatter: fmtDayShort } },
    yAxis: [
      { type: "value", name: "loss, %", nameTextStyle: { color: COLORS.expected, fontFamily: FONT, align: "left" }, ...AXIS_STYLE },
      ...(anyRain
        ? [{ type: "value", name: "rain, mm", nameTextStyle: { color: COLORS.expected, fontFamily: FONT, align: "right" }, ...AXIS_STYLE, splitLine: { show: false } }]
        : []),
    ],
    series: [
      {
        name: "Measured soiling loss", type: "line", data: loss, connectNulls: false, showSymbol: daily.length <= 62, symbolSize: 4,
        lineStyle: { color: COLORS.soiling, width: 2 }, itemStyle: { color: COLORS.soiling },
      },
      ...(anyRain
        ? [{ name: "Rain", type: "bar", yAxisIndex: 1, data: rain, itemStyle: { color: COLORS.rain, opacity: 0.6 }, barMaxWidth: 8 }]
        : []),
    ],
  };
}

// ----------------------------------------------------------------------------- intraday profile (sub-daily data)

export function intradayOption(result: AnalysisResult): EChartsCoreOption {
  const profile = result.intraday.profile;
  return {
    ...BASE,
    grid: { left: 64, right: 56, top: 60, bottom: 40 },
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 10, textStyle: { fontFamily: FONT } },
    tooltip: tooltip((i) => {
      const p = profile[i];
      if (!p) return tooltipNode("", []);
      return tooltipNode(`Solar hour ${p.solar_hour}:00`, [
        ["Expected", orMissing(fmtEnergy(p.expected_kwh)), COLORS.expected],
        ["Actual", orMissing(fmtEnergy(p.actual_kwh)), COLORS.actual],
        ["Loss", orMissing(fmtPct(p.loss_pct, 1)), COLORS.loss],
      ]);
    }),
    xAxis: { type: "category", data: profile.map((p) => `${p.solar_hour}h`), name: "solar time", nameLocation: "middle", nameGap: 26, ...AXIS_STYLE },
    yAxis: [
      {
        type: "value", name: "MWh over the period", nameTextStyle: { color: COLORS.expected, fontFamily: FONT, align: "left" },
        ...AXIS_STYLE, axisLabel: { ...AXIS_STYLE.axisLabel, formatter: (v: number) => fmtNumber(v / 1000, 0) },
      },
      { type: "value", name: "loss, %", nameTextStyle: { color: COLORS.expected, fontFamily: FONT, align: "right" }, ...AXIS_STYLE, splitLine: { show: false } },
    ],
    series: [
      { name: "Expected", type: "line", data: profile.map((p) => p.expected_kwh), showSymbol: false, lineStyle: { color: COLORS.expected, width: 2 }, itemStyle: { color: COLORS.expected } },
      { name: "Actual", type: "line", data: profile.map((p) => p.actual_kwh), showSymbol: false, areaStyle: { color: COLORS.actual, opacity: 0.25 }, lineStyle: { color: COLORS.actual, width: 2 }, itemStyle: { color: COLORS.actual } },
      { name: "Loss", type: "bar", yAxisIndex: 1, data: profile.map((p) => p.loss_pct), itemStyle: { color: COLORS.loss, opacity: 0.55 }, barMaxWidth: 12 },
    ],
  };
}

// ----------------------------------------------------------------------------- devices against the fleet

export function devicesOption(result: AnalysisResult): EChartsCoreOption {
  const findings = result.devices.findings;
  const threshold = result.thresholds.device_underperformance_ratio * 100;
  const ratio = (f: (typeof findings)[number]) => f.median_ratio_window ?? f.median_ratio_period;
  return {
    ...BASE,
    grid: { left: 56, right: 24, top: 24, bottom: 56 },
    tooltip: tooltip((i) => {
      const f = findings[i];
      if (!f) return tooltipNode("", []);
      return tooltipNode(
        f.device_code,
        [
          ["Yield vs fleet median, window", orMissing(fmtFractionPct(f.median_ratio_window))],
          ["Yield vs fleet median, period", orMissing(fmtFractionPct(f.median_ratio_period))],
          ["Days flagged", fmtNumber(f.days_flagged)],
          ["Days offline", fmtNumber(f.days_offline)],
          ["Energy not produced", fmtEnergy(f.lost_energy_kwh)],
        ],
        f.status === "NORMAL" ? undefined : `Status: ${f.status.toLowerCase().replace(/_/g, " ")}.`,
      );
    }),
    xAxis: { type: "category", data: findings.map((f) => f.device_code), ...AXIS_STYLE, axisLabel: { ...AXIS_STYLE.axisLabel, rotate: findings.length > 12 ? 45 : 0 } },
    yAxis: { type: "value", name: "% of fleet median", max: (v: { max: number }) => Math.max(110, Math.ceil(v.max / 10) * 10), nameTextStyle: { color: COLORS.expected, fontFamily: FONT, align: "left" }, ...AXIS_STYLE },
    series: [
      {
        type: "bar", barMaxWidth: 22,
        data: findings.map((f) => {
          const value = ratio(f);
          return { value: value === null ? null : value * 100, itemStyle: { color: f.status === "NORMAL" ? COLORS.normal : COLORS.flagged } };
        }),
        markLine: {
          silent: true, symbol: "none", lineStyle: { color: COLORS.loss, type: "dashed" },
          label: { formatter: `flag below ${fmtNumber(threshold, 0)} %`, color: COLORS.loss, fontFamily: FONT, fontSize: 11, position: "insideEndTop" },
          data: [{ yAxis: threshold }],
        },
      },
    ],
  };
}

function fmtFractionPct(value: number | null): string {
  return value === null ? "—" : fmtPct(value * 100, 1);
}

// ----------------------------------------------------------------------------- economics of one cleaning

export function economicsOption(economics: EconomicsResult): EChartsCoreOption {
  const scenarios = economics.scenarios;
  const names = scenarios.map((s) => s.name.charAt(0) + s.name.slice(1).toLowerCase());
  return {
    ...BASE,
    grid: { left: 72, right: 24, top: 60, bottom: 32 },
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 10, textStyle: { fontFamily: FONT } },
    tooltip: tooltip((i) => {
      const s = scenarios[i];
      if (!s) return tooltipNode("", []);
      return tooltipNode(
        names[i] ?? "",
        [
          ["Recoverable energy", orMissing(fmtEnergy(s.recoverable_energy_kwh))],
          ["Gross benefit", orMissing(fmtMoney(s.gross_benefit, economics.currency)), COLORS.gain],
          ["Cost", orMissing(fmtMoney(s.total_cost, economics.currency)), COLORS.loss],
          ["Net benefit", orMissing(fmtMoney(s.net_benefit, economics.currency)), COLORS.ink],
        ],
        s.description,
      );
    }),
    xAxis: { type: "category", data: names, ...AXIS_STYLE },
    yAxis: {
      type: "value", name: `million ${economics.currency}`, nameTextStyle: { color: COLORS.expected, fontFamily: FONT, align: "left" },
      ...AXIS_STYLE, axisLabel: { ...AXIS_STYLE.axisLabel, formatter: (v: number) => fmtNumber(v / 1e6, 1) },
    },
    series: [
      { name: "Gross benefit", type: "bar", data: scenarios.map((s) => s.gross_benefit), itemStyle: { color: COLORS.gain }, barMaxWidth: 36 },
      { name: "Cost", type: "bar", data: scenarios.map((s) => s.total_cost), itemStyle: { color: COLORS.loss }, barMaxWidth: 36 },
      { name: "Net benefit", type: "bar", data: scenarios.map((s) => s.net_benefit), itemStyle: { color: COLORS.ink }, barMaxWidth: 36 },
    ],
  };
}

// ----------------------------------------------------------------------------- raw series of a dataset

export function seriesOption(series: Series): EChartsCoreOption {
  const stamps = series.start_utc;
  const actual = series.columns.actual_energy_kwh ?? null;
  const expected = series.columns.expected_energy_kwh ?? null;
  const daily = series.interval_minutes === 1440;
  const label = (iso: string) => {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    // Daily intervals start at local midnight, which is the previous evening in UTC: label the local day.
    const shown = daily ? new Date(date.getTime() + 12 * 3600 * 1000) : date;
    const text = fmtDayShort(shown.toISOString().slice(0, 10));
    return daily ? text : `${text} ${String(date.getUTCHours()).padStart(2, "0")}:${String(date.getUTCMinutes()).padStart(2, "0")} UTC`;
  };
  return {
    ...BASE,
    grid: { left: 64, right: 24, top: 60, bottom: 64 },
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 10, textStyle: { fontFamily: FONT } },
    tooltip: tooltip((i) =>
      tooltipNode(label(stamps[i] ?? ""), [
        ...(expected ? [["Expected", orMissing(fmtEnergy(expected[i])), COLORS.expected] as TooltipRow] : []),
        ...(actual ? [["Actual", orMissing(fmtEnergy(actual[i])), COLORS.actual] as TooltipRow] : []),
      ]),
    ),
    xAxis: { type: "category", data: stamps, ...AXIS_STYLE, axisLabel: { ...AXIS_STYLE.axisLabel, formatter: label, hideOverlap: true } },
    yAxis: {
      type: "value", name: "kWh per interval", nameTextStyle: { color: COLORS.expected, fontFamily: FONT, align: "left" },
      ...AXIS_STYLE, axisLabel: { ...AXIS_STYLE.axisLabel, formatter: (v: number) => fmtNumber(v, 0) },
    },
    dataZoom: stamps.length > 120 ? [{ type: "slider", height: 18, bottom: 8 }] : undefined,
    series: [
      ...(actual
        ? [{ name: "Actual energy", type: daily ? "bar" : "line", data: actual, connectNulls: false, showSymbol: false, barMaxWidth: 14, itemStyle: { color: COLORS.actual }, lineStyle: { color: COLORS.actual, width: 1.5 }, areaStyle: daily ? undefined : { color: COLORS.actual, opacity: 0.2 } }]
        : []),
      ...(expected
        ? [{ name: "Expected energy", type: "line", data: expected, connectNulls: false, showSymbol: false, itemStyle: { color: COLORS.expected }, lineStyle: { color: COLORS.expected, width: 1.5 } }]
        : []),
    ],
  };
}
