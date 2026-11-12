import { useMemo, useState } from "react";

import { endpoints } from "../../api/endpoints";
import type { AnalysisResult, PerformanceForecast } from "../../api/types";
import { toApiError } from "../../hooks/useAsync";
import { fmtDay, fmtEnergy, fmtFraction, fmtNumber, fmtPct, humanize } from "../../lib/format";
import { Chart } from "../charts/Chart";
import { energyOption, hasSoilingSeries, performanceOption, soilingOption } from "../charts/options";
import { Badge, Button, Card, CardHeader, ErrorNote, Notice, Stat, Table, Td, Th } from "../ui";

function significanceText(result: AnalysisResult["gap"]["significance"]): string {
  if (result.significant === null) return "Significance could not be evaluated";
  if (result.significant) return "Significant: larger than the uncertainty and the materiality threshold";
  if (result.material === false) return "Below the materiality threshold";
  return "Not distinguishable from measurement uncertainty";
}

export function GapPanel({ result, analysisId }: { result: AnalysisResult; analysisId: number | null }) {
  const gap = result.gap;
  const window = gap.window;
  const energy = useMemo(() => energyOption(result), [result]);
  const [forecast, setForecast] = useState<PerformanceForecast | null>(null);
  const [forecastError, setForecastError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const performance = useMemo(() => performanceOption(result, forecast), [result, forecast]);
  const soiling = useMemo(() => (hasSoilingSeries(result) ? soilingOption(result) : null), [result]);
  const missingDays = gap.daily.filter((d) => d.status !== "OK").length;

  async function loadForecast() {
    if (analysisId === null) return;
    setBusy(true);
    setForecastError(null);
    try {
      setForecast((await endpoints.forecast(analysisId, 14)).forecast);
    } catch (cause) {
      setForecastError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card aria-labelledby="gap-title">
        <CardHeader
          id="gap-title"
          title="Expected and actual energy"
          description="The gap is an observation. On its own it says nothing about the cause."
        />
        <dl className="grid grid-cols-2 gap-5 px-5 py-5 md:grid-cols-4">
          <Stat label="Expected (baseline)" value={fmtEnergy(gap.result.expected_kwh)} hint={humanize(result.baseline.method)} />
          <Stat label="Actual" value={fmtEnergy(gap.result.actual_kwh)} />
          <Stat label="Gap, period" value={fmtPct(gap.result.relative_gap_pct)} hint={fmtEnergy(gap.result.gap_kwh)} />
          <Stat label="Gap, assessment window" value={fmtPct(window.result.relative_gap_pct)} hint={fmtEnergy(window.result.gap_kwh)} />
        </dl>
        <div className="px-3 pb-2">
          <Chart option={energy} label="Daily expected and actual energy over the analysed period" />
        </div>
        {missingDays > 0 && (
          <div className="px-5 pb-4">
            <Notice tone="warning">
              {missingDays} day(s) have no usable comparison. They are drawn as gaps: missing values are never replaced
              by zero and never interpolated.
            </Notice>
          </div>
        )}
        <Table>
          <thead>
            <tr>
              <Th>Scope</Th><Th>Dates</Th><Th numeric>Gap</Th><Th numeric>Combined uncertainty (k = 1)</Th>
              <Th numeric>Threshold</Th><Th numeric>Days compared</Th><Th>Reading</Th>
            </tr>
          </thead>
          <tbody>
            {[
              { name: "Whole period", start: gap.period_start, end: gap.period_end, r: gap.result, s: gap.significance, c: gap.coverage },
              { name: "Assessment window", start: window.start, end: window.end, r: window.result, s: window.significance, c: window.coverage },
            ].map((row) => (
              <tr key={row.name}>
                <Td className="font-medium">{row.name}</Td>
                <Td>{fmtDay(row.start)} – {fmtDay(row.end)}</Td>
                <Td numeric>{fmtPct(row.r.relative_gap_pct, 2)}</Td>
                <Td numeric>{fmtPct(row.s.combined_std_uncertainty_pct, 2)}</Td>
                <Td numeric>{fmtPct(row.s.threshold_pct, 2)}</Td>
                <Td numeric>{row.c.days_complete} / {row.c.days_total} ({fmtFraction(row.c.fraction, 0)})</Td>
                <Td>{significanceText(row.s)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {gap.limitations.length > 0 && (
          <ul className="list-disc space-y-1 px-5 py-4 pl-10 text-sm text-ink-600">
            {gap.limitations.map((item) => <li key={item}>{item}</li>)}
          </ul>
        )}
      </Card>

      <Card aria-labelledby="pi-title">
        <CardHeader
          id="pi-title"
          title="Performance index"
          description="Actual energy divided by expected energy, day by day."
          actions={
            analysisId !== null && !forecast ? (
              <Button size="sm" busy={busy} onClick={loadForecast}>Add reference projections</Button>
            ) : forecast ? (
              <Badge className="border-violet-300 bg-violet-50 text-violet-900">UNVALIDATED projections shown</Badge>
            ) : undefined
          }
        />
        <div className="px-3 pb-2 pt-3">
          <Chart option={performance} label="Daily performance index, with reference projections when requested" />
        </div>
        <div className="space-y-3 px-5 pb-5">
          {forecastError && <ErrorNote error={forecastError} />}
          {forecast && <ForecastNotes forecast={forecast} />}
          <TrendNotes result={result} />
        </div>
      </Card>

      {soiling && (
        <Card aria-labelledby="soiling-title">
          <CardHeader
            id="soiling-title"
            title="Measured soiling loss"
            description="From the soiling-ratio channel of the dataset. Rain is shown as context: it does not measure dust on the modules."
          />
          <div className="px-3 pb-3 pt-3">
            <Chart option={soiling} height={280} label="Measured soiling loss and rain, day by day" />
          </div>
        </Card>
      )}
    </div>
  );
}

function ForecastNotes({ forecast }: { forecast: PerformanceForecast }) {
  return (
    <Notice tone="simulated" title={`${forecast.validation_status} reference projections - not used by any decision`}>
      {!forecast.evaluable && <p>{forecast.reason ?? "The history is too short to project."}</p>}
      <ul className="list-disc space-y-1 pl-5">
        {forecast.notes.map((note) => <li key={note}>{note}</li>)}
      </ul>
      {forecast.evaluable && (
        <div className="relative mt-3 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-violet-900">
                <th className="py-1 pr-4 font-semibold">Method</th>
                <th className="py-1 pr-4 font-semibold">How</th>
                <th className="py-1 pr-4 text-right font-semibold">Back-test error (index points)</th>
                <th className="py-1 pr-4 text-right font-semibold">Bias</th>
                <th className="py-1 text-right font-semibold">Samples</th>
              </tr>
            </thead>
            <tbody>
              {forecast.methods.map((m) => (
                <tr key={m.method} className="border-t border-violet-200">
                  <td className="py-1 pr-4 font-medium">{m.label}</td>
                  <td className="py-1 pr-4">{m.description}</td>
                  <td className="tabular py-1 pr-4 text-right">{m.backtest ? fmtNumber(m.backtest.mean_absolute_error, 2) : "not evaluated"}</td>
                  <td className="tabular py-1 pr-4 text-right">{m.backtest ? fmtNumber(m.backtest.bias, 2) : "—"}</td>
                  <td className="tabular py-1 text-right">{m.backtest ? m.backtest.samples : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Notice>
  );
}

function TrendNotes({ result }: { result: AnalysisResult }) {
  const trend = result.trend;
  if (!trend.evaluable) {
    return <p className="text-sm text-ink-600">Trend not evaluated: {trend.reason ?? "not enough data"}.</p>;
  }
  const step = trend.step;
  return (
    <div className="space-y-1 text-sm text-ink-700">
      <p>
        Trend over the current dry spell ({trend.spell_days ?? "—"} day(s) since {fmtDay(trend.spell_start)}):{" "}
        <span className="tabular font-medium text-ink-900">{fmtNumber(trend.slope_pct_per_day, 3)} % per day</span>{" "}
        ({fmtNumber((trend.confidence_level ?? 0) * 100, 0)} % interval {fmtNumber(trend.slope_low_pct_per_day, 3)} to{" "}
        {fmtNumber(trend.slope_high_pct_per_day, 3)}).{" "}
        {trend.declining ? "The decline is statistically distinguishable from zero." : "No decline distinguishable from zero."}
      </p>
      {step && (
        <p>
          Largest step: {fmtNumber(step.drop_pct, 1)} points on {fmtDay(step.day)}
          {step.material ? " - material. A sudden step points to an event, not to gradual soiling." : " - not material."}
        </p>
      )}
      {trend.reset_events.map((event) => (
        <p key={`${event.day}-${event.kind}`}>
          Reset on {fmtDay(event.day)}: {humanize(event.kind)}{event.detail ? ` - ${event.detail}` : ""}.
        </p>
      ))}
      <p className="text-xs text-ink-500">{trend.method}</p>
    </div>
  );
}
