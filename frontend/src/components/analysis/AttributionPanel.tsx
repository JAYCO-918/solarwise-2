import { useMemo, useState } from "react";

import type { AnalysisResult, AttributionScope } from "../../api/types";
import { fmtDay, fmtEnergy, fmtFraction, fmtNumber, fmtPct } from "../../lib/format";
import { FACTOR_LABEL, FACTOR_STATUS_LABEL } from "../../lib/labels";
import { Chart } from "../charts/Chart";
import { attributionOption, devicesOption, intradayOption } from "../charts/options";
import { Badge, Card, CardHeader, Notice, Table, Td, Th } from "../ui";
import { cx } from "../../lib/cx";

const STATUS_STYLE: Record<string, string> = {
  QUANTIFIED: "border-ink-800 bg-ink-800 text-white",
  PARTIALLY_QUANTIFIED: "border-ink-400 bg-ink-100 text-ink-900",
  ACCOUNTED_IN_BASELINE: "border-ink-200 bg-white text-ink-600",
  NOT_QUANTIFIED: "border-dashed border-amber-500 bg-amber-50 text-amber-900",
  NOT_APPLICABLE: "border-ink-200 bg-white text-ink-500",
};

export function AttributionPanel({ result }: { result: AnalysisResult }) {
  const [scopeKey, setScopeKey] = useState<"window" | "period">("window");
  const scope: AttributionScope = result.attribution[scopeKey];
  const option = useMemo(() => attributionOption(scope), [scope]);
  const unquantified = scope.contributions.filter((c) => c.status === "NOT_QUANTIFIED");

  return (
    <div className="space-y-6">
      <Card aria-labelledby="attribution-title">
        <CardHeader
          id="attribution-title"
          title="From expected to actual energy"
          description="Each factor is quantified only from data that measure it. What cannot be quantified stays in the unexplained residual; it is never assigned to soiling."
          actions={
            <div role="group" aria-label="Scope" className="inline-flex rounded-md border border-ink-300 p-0.5 text-sm">
              {(["window", "period"] as const).map((key) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={scopeKey === key}
                  onClick={() => setScopeKey(key)}
                  className={cx("rounded px-2.5 py-1 font-medium", scopeKey === key ? "bg-ink-900 text-white" : "text-ink-700 hover:bg-ink-100")}
                >
                  {key === "window" ? "Assessment window" : "Whole period"}
                </button>
              ))}
            </div>
          }
        />
        <p className="px-5 pt-4 text-sm text-ink-600">
          {fmtDay(scope.start)} – {fmtDay(scope.end)} · {scope.matched_slots} interval(s) compared
        </p>
        {scope.expected_kwh === null || scope.actual_kwh === null ? (
          <div className="p-5"><Notice tone="warning">No interval of this scope has both an expected and an actual value: nothing can be attributed.</Notice></div>
        ) : (
          <div className="px-3 pb-2 pt-2">
            <Chart option={option} label="Bridge from expected energy to actual energy, factor by factor" />
          </div>
        )}
        <Table>
          <thead>
            <tr>
              <Th>Factor</Th><Th>Status</Th><Th numeric>Energy</Th><Th numeric>Share of expected</Th>
              <Th numeric>Data coverage</Th><Th>Basis and explanation</Th>
            </tr>
          </thead>
          <tbody>
            {scope.contributions.map((c) => (
              <tr key={c.factor}>
                <Td className="font-medium">{FACTOR_LABEL[c.factor] ?? c.factor}</Td>
                <Td><Badge className={STATUS_STYLE[c.status]}>{FACTOR_STATUS_LABEL[c.status] ?? c.status}</Badge></Td>
                <Td numeric>{fmtEnergy(c.energy.value)}</Td>
                <Td numeric>{fmtPct(c.share_of_expected_pct, 2)}</Td>
                <Td numeric>{fmtFraction(c.coverage, 0)}</Td>
                <Td className="max-w-md text-ink-700">
                  {c.explanation}
                  {c.missing_inputs.length > 0 && (
                    <span className="mt-1 block text-xs text-amber-800">Missing: {c.missing_inputs.join("; ")}</span>
                  )}
                </Td>
              </tr>
            ))}
            <tr className="bg-ink-50">
              <Td className="font-semibold">Unexplained residual</Td>
              <Td><Badge className="border-ink-300 bg-white text-ink-700">Remainder</Badge></Td>
              <Td numeric className="font-semibold">{fmtEnergy(scope.residual_kwh)}</Td>
              <Td numeric className="font-semibold">{fmtPct(scope.residual_pct, 2)}</Td>
              <Td />
              <Td className="max-w-md text-ink-700">
                Expected energy minus every quantified factor minus actual energy.
                {unquantified.length > 0 &&
                  ` Any effect of ${unquantified.map((c) => (FACTOR_LABEL[c.factor] ?? c.factor).toLowerCase()).join(", ")} is still inside it.`}
              </Td>
            </tr>
          </tbody>
        </Table>
        {result.attribution.notes.length > 0 && (
          <ul className="list-disc space-y-1 px-5 py-4 pl-10 text-sm text-ink-600">
            {result.attribution.notes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        )}
      </Card>

      <DevicesCard result={result} />
      <IntradayCard result={result} />
    </div>
  );
}

function DevicesCard({ result }: { result: AnalysisResult }) {
  const devices = result.devices;
  const option = useMemo(() => (devices.evaluable ? devicesOption(result) : null), [devices.evaluable, result]);
  const flagged = devices.findings.filter((f) => f.status !== "NORMAL");
  return (
    <Card aria-labelledby="devices-title">
      <CardHeader
        id="devices-title"
        title="Devices against the fleet"
        description="Specific yield of each device compared with the fleet median. A device far below the others points to equipment, not to soiling, which affects the whole array."
      />
      {!devices.evaluable || !option ? (
        <p className="px-5 py-5 text-sm text-ink-600">Not evaluated: {devices.reason ?? "the dataset has no device-level energy"}.</p>
      ) : (
        <>
          <p className="px-5 pt-4 text-sm text-ink-700">
            {devices.n_devices} device(s) over {devices.n_days} day(s): {devices.flagged_devices} flagged, {devices.active_in_window} still
            affected in the assessment window. Energy not produced: <span className="tabular font-medium">{fmtEnergy(devices.lost_energy_kwh)}</span>.
          </p>
          <div className="px-3 pb-2 pt-2">
            <Chart option={option} height={280} label="Specific yield of each device relative to the fleet median" />
          </div>
          {flagged.length > 0 && (
            <Table>
              <thead>
                <tr>
                  <Th>Device</Th><Th>Status</Th><Th numeric>vs fleet, window</Th><Th numeric>Days flagged</Th>
                  <Th numeric>Days offline</Th><Th>First – last flagged</Th><Th numeric>Energy not produced</Th>
                </tr>
              </thead>
              <tbody>
                {flagged.map((f) => (
                  <tr key={f.device_code}>
                    <Td className="font-mono font-medium">{f.device_code}</Td>
                    <Td>{f.status.replace(/_/g, " ").toLowerCase()}</Td>
                    <Td numeric>{fmtFraction(f.median_ratio_window, 1)}</Td>
                    <Td numeric>{f.days_flagged}</Td>
                    <Td numeric>{f.days_offline}</Td>
                    <Td>{fmtDay(f.first_flagged)} – {fmtDay(f.last_flagged)}</Td>
                    <Td numeric>{fmtEnergy(f.lost_energy_kwh)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          <ul className="list-disc space-y-1 px-5 py-4 pl-10 text-xs text-ink-500">
            {devices.notes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        </>
      )}
    </Card>
  );
}

function IntradayCard({ result }: { result: AnalysisResult }) {
  const intraday = result.intraday;
  const option = useMemo(() => (intraday.evaluable ? intradayOption(result) : null), [intraday.evaluable, result]);
  return (
    <Card aria-labelledby="intraday-title">
      <CardHeader
        id="intraday-title"
        title="Profile over the day"
        description="Needs sub-daily data. A loss concentrated at one end of the day suggests shading; a flat top suggests a power limit. Both are patterns, not proof."
      />
      {!intraday.evaluable || !option ? (
        <p className="px-5 py-5 text-sm text-ink-600">Not evaluated: {intraday.reason ?? "the dataset has daily values only"}.</p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-4 px-5 pt-4 text-sm md:grid-cols-4">
            <div><dt className="text-ink-500">Loss, morning</dt><dd className="tabular font-medium">{fmtPct(intraday.loss_morning_pct)}</dd></div>
            <div><dt className="text-ink-500">Loss, midday</dt><dd className="tabular font-medium">{fmtPct(intraday.loss_midday_pct)}</dd></div>
            <div><dt className="text-ink-500">Loss, evening</dt><dd className="tabular font-medium">{fmtPct(intraday.loss_evening_pct)}</dd></div>
            <div><dt className="text-ink-500">Days evaluated</dt><dd className="tabular font-medium">{fmtNumber(intraday.days_evaluated)}</dd></div>
          </dl>
          <div className="px-3 pb-2 pt-2">
            <Chart option={option} height={280} label="Expected and actual energy by solar hour, with the loss in each hour" />
          </div>
          <div className="space-y-2 px-5 pb-5 text-sm text-ink-700">
            {intraday.shading_signature && (
              <p>
                Shading pattern: the {intraday.edge_side?.toLowerCase()} loss exceeds the midday loss by{" "}
                {fmtNumber(intraday.edge_excess_pct, 1)} points on {intraday.days_with_edge_excess} day(s)
                ({fmtEnergy(intraday.shading_excess_loss_kwh)} above the midday level).
              </p>
            )}
            {intraday.plateau_signature && (
              <p>
                Power-limit pattern on {intraday.plateau_days} day(s), at about {fmtFraction(intraday.plateau_level_of_ac, 0)} of the
                AC rating ({fmtEnergy(intraday.plateau_excess_loss_kwh)} above the plateau).
              </p>
            )}
            {!intraday.shading_signature && !intraday.plateau_signature && <p>No shading or power-limit pattern found.</p>}
            <ul className="list-disc space-y-1 pl-5 text-xs text-ink-500">
              {intraday.notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
          </div>
        </>
      )}
    </Card>
  );
}
