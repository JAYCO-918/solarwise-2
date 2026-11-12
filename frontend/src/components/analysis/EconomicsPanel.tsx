import { useMemo } from "react";

import type { AnalysisResult, EconomicsResult, RecoverableEnergy } from "../../api/types";
import { fmtEnergy, fmtMoney, fmtNumber, fmtPct, humanize } from "../../lib/format";
import { Chart } from "../charts/Chart";
import { economicsOption } from "../charts/options";
import { Badge, Card, CardHeader, Notice, Stat, Table, Td, Th } from "../ui";

const VERDICT_STYLE: Record<string, string> = {
  PROFITABLE: "border-teal-700 bg-teal-700 text-white",
  MARGINAL: "border-amber-400 bg-amber-50 text-amber-950",
  UNPROFITABLE: "border-rose-300 bg-rose-50 text-rose-900",
  UNDETERMINED: "border-dashed border-ink-400 bg-white text-ink-700",
};

const VERDICT_TEXT: Record<string, string> = {
  PROFITABLE: "Cleaning pays even in the conservative case.",
  MARGINAL: "Cleaning pays in the base case but not in the conservative case.",
  UNPROFITABLE: "Cleaning costs more than it recovers in the base case.",
  UNDETERMINED: "The inputs do not allow a verdict.",
};

const CLASSIFICATION_STYLE: Record<string, string> = {
  OFFICIAL_REFERENCE: "border-emerald-300 bg-emerald-50 text-emerald-900",
  TECHNICAL_REFERENCE: "border-sky-300 bg-sky-50 text-sky-900",
  USER_ASSUMPTION: "border-amber-300 bg-amber-50 text-amber-900",
  DERIVED_FROM_DATA: "border-ink-300 bg-ink-50 text-ink-800",
};

function assumptionValue(value: number | null, unit: string): string {
  if (value === null) return "not supplied";
  if (unit === "fraction") return fmtPct(value * 100, 0);
  if (unit === "%") return fmtPct(value, 1);
  if (unit === "kWh/day") return `${fmtEnergy(value)} per day`;
  return `${fmtNumber(value, Number.isInteger(value) ? 0 : 2)} ${unit}`;
}

function AssumptionsTable({ rows }: { rows: { name: string; value: number | null; unit: string; classification: string; source: string }[] }) {
  if (rows.length === 0) return null;
  return (
    <Table>
      <thead><tr><Th>Input</Th><Th numeric>Value</Th><Th>Classification</Th><Th>Source</Th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.name}>
            <Td className="font-medium">{row.name}</Td>
            <Td numeric>{assumptionValue(row.value, row.unit)}</Td>
            <Td><Badge className={CLASSIFICATION_STYLE[row.classification] ?? "border-ink-300 bg-white text-ink-700"}>{humanize(row.classification)}</Badge></Td>
            <Td className="max-w-md text-ink-700">{row.source}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

export function RecoverableCard({ recoverable }: { recoverable: RecoverableEnergy }) {
  const estimated = recoverable.status === "ESTIMATED";
  return (
    <Card aria-labelledby="recoverable-title">
      <CardHeader
        id="recoverable-title"
        title="Energy a cleaning could recover"
        description="A projection, never a measurement: measured soiling loss × assumed cleaning effectiveness × projected clean-array energy × assumed horizon. Nothing is assumed by default."
        actions={<Badge className={estimated ? "border-ink-800 bg-ink-800 text-white" : "border-dashed border-ink-400 bg-white text-ink-700"}>{humanize(recoverable.status)}</Badge>}
      />
      {estimated ? (
        <dl className="grid grid-cols-2 gap-5 px-5 py-5 md:grid-cols-4">
          <Stat label="Low" value={fmtEnergy(recoverable.recoverable.low)} />
          <Stat label="Central" value={fmtEnergy(recoverable.recoverable.central)} hint={`over ${fmtNumber(recoverable.horizon_days, 0)} days`} />
          <Stat label="High" value={fmtEnergy(recoverable.recoverable.high)} />
          <Stat label="Measured soiling loss" value={fmtPct(recoverable.soiling_loss_pct)} hint={`${fmtPct(recoverable.soiling_loss_low_pct)} to ${fmtPct(recoverable.soiling_loss_high_pct)}`} />
        </dl>
      ) : (
        <div className="px-5 py-5">
          <Notice tone="neutral" title="No recoverable energy is estimated">
            The figure is left empty rather than guessed.
          </Notice>
        </div>
      )}
      <ul className="list-disc space-y-1 px-5 pb-4 pl-10 text-sm text-ink-700">
        {recoverable.reasons.map((reason) => <li key={reason}>{reason}</li>)}
        {recoverable.warnings.map((warning) => <li key={warning} className="text-amber-900">{warning}</li>)}
      </ul>
      <AssumptionsTable rows={recoverable.assumptions} />
      {(recoverable.uncertainty_statement || recoverable.method) && (
        <div className="space-y-1 px-5 py-4 text-xs text-ink-500">
          {recoverable.uncertainty_statement && <p>{recoverable.uncertainty_statement}</p>}
          {recoverable.method && <p className="font-mono">{recoverable.method}</p>}
        </div>
      )}
    </Card>
  );
}

export function EconomicsCard({ economics }: { economics: EconomicsResult }) {
  const hasFigures = economics.scenarios.some((s) => s.net_benefit !== null);
  const option = useMemo(() => (hasFigures ? economicsOption(economics) : null), [economics, hasFigures]);
  const currency = economics.currency;
  return (
    <Card aria-labelledby="economics-title">
      <CardHeader
        id="economics-title"
        title="Economics of one cleaning"
        description="Arithmetic on the figures supplied with the analysis. No price is built in; an input that was not supplied is reported as missing."
        actions={<Badge className={VERDICT_STYLE[economics.verdict]}>{humanize(economics.verdict)}</Badge>}
      />
      <div className="space-y-3 px-5 py-4 text-sm">
        <p className="text-ink-800">{VERDICT_TEXT[economics.verdict]}</p>
        {!economics.decision_grade && (
          <Notice tone="warning" title="Not decision-grade">
            {economics.energy_value_basis === "CONSUMER_TARIFF_PROXY"
              ? "A consumer tariff is what a customer pays, not what the plant earns: it can illustrate, not justify a decision."
              : "The inputs are incomplete or their basis does not allow a cleaning decision to rest on them."}
          </Notice>
        )}
        {economics.missing_inputs.length > 0 && (
          <Notice tone="warning" title="Missing inputs">
            <ul className="list-disc pl-5">{economics.missing_inputs.map((m) => <li key={m}>{m}</li>)}</ul>
          </Notice>
        )}
      </div>
      {option && (
        <div className="px-3 pb-2">
          <Chart option={option} height={260} label="Gross benefit, cost and net benefit in the conservative, base and optimistic cases" />
        </div>
      )}
      <Table>
        <thead>
          <tr>
            <Th>Case</Th><Th numeric>Recoverable energy</Th><Th numeric>Gross benefit</Th><Th numeric>Cost</Th>
            <Th numeric>Net benefit</Th><Th numeric>Return</Th><Th>Assumes</Th>
          </tr>
        </thead>
        <tbody>
          {economics.scenarios.map((s) => (
            <tr key={s.name}>
              <Td className="font-medium">{humanize(s.name)}</Td>
              <Td numeric>{fmtEnergy(s.recoverable_energy_kwh)}</Td>
              <Td numeric>{fmtMoney(s.gross_benefit, currency)}</Td>
              <Td numeric>{fmtMoney(s.total_cost, currency)}</Td>
              <Td numeric className="font-semibold">{fmtMoney(s.net_benefit, currency)}</Td>
              <Td numeric>{fmtPct(s.roi_pct, 0)}</Td>
              <Td className="text-ink-700">{s.description}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <dl className="grid grid-cols-2 gap-5 px-5 py-5 md:grid-cols-4">
        <Stat label="Cost of the cleaning" value={fmtMoney(economics.cost.total, currency)} hint={economics.cost.total === null ? `incomplete: ${economics.cost.missing.join(", ")}` : undefined} />
        <Stat label="Energy value" value={economics.energy_value_per_kwh === null ? "—" : `${fmtNumber(economics.energy_value_per_kwh, 2)} ${currency}/kWh`} hint={humanize(economics.energy_value_basis)} />
        <Stat label="Break-even energy" value={fmtEnergy(economics.break_even_energy_kwh)} hint={economics.break_even_soiling_loss_pct === null ? undefined : `soiling loss of ${fmtPct(economics.break_even_soiling_loss_pct, 2)}`} />
        <Stat label="Payback" value={economics.payback_days === null ? "—" : `${fmtNumber(economics.payback_days, 1)} days`} hint={economics.horizon_days === null ? undefined : `horizon ${fmtNumber(economics.horizon_days, 0)} days`} />
      </dl>
      <Table>
        <thead><tr><Th>Cost item</Th><Th numeric>Amount</Th><Th>Basis</Th><Th>Detail</Th></tr></thead>
        <tbody>
          {economics.cost.items.map((item) => (
            <tr key={item.name}>
              <Td className="font-medium">{humanize(item.name)}</Td>
              <Td numeric>{item.amount === null ? "not supplied" : fmtMoney(item.amount, currency)}</Td>
              <Td>{humanize(item.basis)}</Td>
              <Td className="font-mono text-xs text-ink-600">{item.detail ?? ""}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <AssumptionsTable rows={economics.assumptions} />
      <div className="space-y-2 px-5 py-4 text-sm">
        {economics.warnings.map((warning) => <p key={warning} className="text-amber-900">{warning}</p>)}
        <ul className="font-mono text-xs text-ink-500">
          {economics.formulae.map((formula) => <li key={formula}>{formula}</li>)}
        </ul>
      </div>
    </Card>
  );
}

export function EconomicsPanel({ result }: { result: AnalysisResult }) {
  return (
    <div className="space-y-6">
      <RecoverableCard recoverable={result.recoverable} />
      <EconomicsCard economics={result.economics} />
    </div>
  );
}
