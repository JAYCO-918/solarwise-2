import { AlertTriangle, CheckCircle2, OctagonX } from "lucide-react";

import type { AnalysisResult, Stage } from "../../api/types";
import { fmtFraction, fmtNumber, fmtPct, humanize } from "../../lib/format";
import { PROVENANCE_MEANING } from "../../lib/labels";
import { ProvenanceBadge } from "../badges";
import { Badge, Card, CardHeader, DefinitionList, Notice, Table, Td, Th } from "../ui";
import { cx } from "../../lib/cx";

const STAGE = {
  OK: { Icon: CheckCircle2, className: "text-teal-700", label: "OK" },
  WARNING: { Icon: AlertTriangle, className: "text-amber-600", label: "Warning" },
  BLOCKED: { Icon: OctagonX, className: "text-rose-700", label: "Blocked" },
} as const;

const SEVERITY_STYLE: Record<string, string> = {
  BLOCKING: "border-rose-400 bg-rose-50 text-rose-900",
  ERROR: "border-rose-300 bg-rose-50 text-rose-900",
  WARNING: "border-amber-300 bg-amber-50 text-amber-900",
  INFO: "border-ink-200 bg-ink-50 text-ink-700",
};

const QUALITY_STYLE: Record<string, string> = {
  GOOD: "border-teal-700 bg-teal-700 text-white",
  DEGRADED: "border-amber-400 bg-amber-50 text-amber-950",
  INSUFFICIENT: "border-rose-300 bg-rose-50 text-rose-900",
  HIGH: "border-ink-800 bg-ink-800 text-white",
  MEDIUM: "border-ink-300 bg-ink-100 text-ink-900",
  LOW: "border-ink-300 bg-white text-ink-700",
};

export function StagesStrip({ stages }: { stages: Stage[] }) {
  return (
    <ol className="grid grid-cols-2 gap-2 sm:grid-cols-5">
      {stages.map((stage, index) => {
        const style = STAGE[stage.state];
        return (
          <li key={stage.key} title={stage.message} className="rounded-md border border-ink-200 bg-white px-3 py-2">
            <div className="flex items-center gap-1.5">
              <style.Icon className={cx("size-4 shrink-0", style.className)} aria-hidden />
              <span className="tabular text-xs text-ink-400">{index + 1}</span>
              <span className="sr-only">{style.label}:</span>
              <span className="truncate text-sm font-medium text-ink-900">{stage.title}</span>
            </div>
            <p className="mt-1 line-clamp-2 text-xs text-ink-600">{stage.message}</p>
          </li>
        );
      })}
    </ol>
  );
}

export function ProvenancePanel({ result }: { result: AnalysisResult }) {
  const quality = result.quality;
  const baseline = result.baseline;
  const issues = [...quality.issues, ...quality.import_issues];
  return (
    <div className="space-y-6">
      <Card aria-labelledby="provenance-title">
        <CardHeader
          id="provenance-title"
          title="Where every value comes from"
          description="Provenance is declared with the dataset and travels with each value. Synthetic, modelled and undocumented data never support an operational decision."
        />
        <Table>
          <thead>
            <tr><Th>Quantity</Th><Th>Declared provenance</Th><Th>Counts here as</Th><Th>Source</Th><Th>Unit</Th><Th numeric>Declared uncertainty</Th></tr>
          </thead>
          <tbody>
            {result.provenance.map((row) => (
              <tr key={row.metric}>
                <Td className="font-medium">{row.label}</Td>
                <Td><ProvenanceBadge label={row.provenance} /></Td>
                <Td>{humanize(row.effective_class)}</Td>
                <Td className="max-w-sm text-ink-700">
                  {row.source || "not declared"}
                  {row.method && <span className="block text-xs text-ink-500">{row.method}</span>}
                </Td>
                <Td className="font-mono text-xs">{row.unit}</Td>
                <Td numeric>
                  {row.uncertainty_pct !== null ? fmtPct(row.uncertainty_pct, 1) : row.uncertainty_abs !== null ? `± ${fmtNumber(row.uncertainty_abs, 2)} ${row.unit}` : "not declared"}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <dl className="grid gap-x-6 gap-y-2 border-t border-ink-100 px-5 py-4 text-sm sm:grid-cols-2">
          {(Object.keys(PROVENANCE_MEANING) as (keyof typeof PROVENANCE_MEANING)[]).map((key) => (
            <div key={key} className="flex items-start gap-2">
              <dt className="shrink-0"><ProvenanceBadge label={key} /></dt>
              <dd className="text-ink-600">{PROVENANCE_MEANING[key]}</dd>
            </div>
          ))}
        </dl>
        {result.evidence.synthetic_evidence_present && (
          <div className="px-5 pb-5">
            <Notice tone="simulated" title="Synthetic evidence is present">
              The result illustrates the method. It cannot authorise field work, whatever the decision.
            </Notice>
          </div>
        )}
      </Card>

      <Card aria-labelledby="quality-title">
        <CardHeader
          id="quality-title"
          title="Data quality"
          description={quality.summary}
          actions={<Badge className={QUALITY_STYLE[quality.status]}>{humanize(quality.status)}</Badge>}
        />
        <Table>
          <thead>
            <tr><Th>Channel</Th><Th>Column</Th><Th numeric>Values</Th><Th numeric>Completeness</Th><Th numeric>Longest gap</Th><Th numeric>Min</Th><Th numeric>Mean</Th><Th numeric>Max</Th></tr>
          </thead>
          <tbody>
            {quality.channels.map((channel) => (
              <tr key={channel.metric}>
                <Td className="font-medium">{humanize(channel.metric)}</Td>
                <Td className="font-mono text-xs">{channel.column}</Td>
                <Td numeric>{channel.observed_slots} / {channel.expected_slots}</Td>
                <Td numeric>{fmtFraction(channel.completeness, 1)}</Td>
                <Td numeric>{channel.longest_gap_slots}</Td>
                <Td numeric>{fmtNumber(channel.minimum, 2)}</Td>
                <Td numeric>{fmtNumber(channel.mean, 2)}</Td>
                <Td numeric>{fmtNumber(channel.maximum, 2)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {issues.length > 0 && (
          <ul className="divide-y divide-ink-100 border-t border-ink-100">
            {issues.map((issue) => (
              <li key={`${issue.code}-${issue.metric ?? ""}-${issue.message}`} className="flex flex-wrap items-start gap-3 px-5 py-3 text-sm">
                <Badge className={SEVERITY_STYLE[issue.severity] ?? SEVERITY_STYLE.INFO}>{humanize(issue.severity)}</Badge>
                <div className="min-w-0 flex-1">
                  <p className="break-words text-ink-800">{issue.message}</p>
                  <p className="font-mono text-xs text-ink-500">{issue.code}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
        <ul className="list-disc space-y-1 px-5 py-4 pl-10 text-sm text-ink-600">
          {quality.notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      </Card>

      <Card aria-labelledby="baseline-title">
        <CardHeader
          id="baseline-title"
          title="Baseline: what “expected” means here"
          description="The gap is only as good as the reference it is measured against."
          actions={<Badge className={baseline.status === "OK" ? "border-ink-300 bg-white text-ink-800" : "border-rose-300 bg-rose-50 text-rose-900"}>{humanize(baseline.status)}</Badge>}
        />
        <div className="px-5 py-5">
          <DefinitionList
            items={[
              ["Method", humanize(baseline.method)],
              ["Description", baseline.descriptor.description ?? "not documented"],
              ["Provenance", <ProvenanceBadge key="p" label={baseline.meta.tag.emulates ? `${baseline.meta.tag.provenance} (emulates ${baseline.meta.tag.emulates})` : baseline.meta.tag.provenance} />],
              ["Declared uncertainty", baseline.meta.uncertainty_pct === null ? "not declared" : fmtPct(baseline.meta.uncertainty_pct, 1)],
              ["Adjusted for irradiance", yesNoUnknown(baseline.descriptor.irradiance_adjusted)],
              ["Adjusted for temperature", yesNoUnknown(baseline.descriptor.temperature_adjusted)],
              ["Adjusted for degradation", yesNoUnknown(baseline.descriptor.degradation_adjusted)],
              ["Soiling allowance inside the baseline", baseline.descriptor.soiling_allowance_fraction === null ? "not declared" : fmtFraction(baseline.descriptor.soiling_allowance_fraction, 1)],
            ]}
          />
          {[...baseline.limitations, ...baseline.notes].length > 0 && (
            <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-ink-600">
              {baseline.limitations.map((item) => <li key={item}>{item}</li>)}
              {baseline.notes.map((item) => <li key={item}>{item}</li>)}
            </ul>
          )}
        </div>
      </Card>

      <Card aria-labelledby="evidence-quality-title">
        <CardHeader
          id="evidence-quality-title"
          title="Kinds of evidence available"
          description={result.evidence.quality_note}
          actions={<Badge className={QUALITY_STYLE[result.evidence.quality] ?? QUALITY_STYLE.LOW}>{humanize(result.evidence.quality)}</Badge>}
        />
        <ul className="divide-y divide-ink-100">
          {result.evidence.quality_checks.map((check) => (
            <li key={check.label} className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-3 px-5 py-3 text-sm">
              <span className={cx("font-semibold", check.met ? "text-teal-800" : "text-ink-500")}>{check.met ? "Available" : "Missing"}</span>
              <span>
                <span className="font-medium text-ink-900">{check.label}</span>
                <span className="block text-ink-600">{check.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </Card>

      <Card aria-labelledby="thresholds-title">
        <CardHeader id="thresholds-title" title="Thresholds used by this analysis" description="Stored with the result, so that it can be reproduced exactly." />
        <dl className="grid gap-x-8 gap-y-2 px-5 py-5 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(result.thresholds).map(([name, value]) => (
            <div key={name} className="flex justify-between gap-4 border-b border-ink-100 pb-1.5">
              <dt className="font-mono text-xs text-ink-600">{name}</dt>
              <dd className="tabular font-medium">{fmtNumber(value, Number.isInteger(value) ? 0 : 2)}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}

function yesNoUnknown(value: boolean | null): string {
  return value === null ? "not declared" : value ? "yes" : "no";
}
