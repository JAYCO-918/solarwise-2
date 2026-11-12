import { AlertOctagon, Check as CheckIcon, Minus, ThumbsDown, ThumbsUp, X } from "lucide-react";

import type { AnalysisResult, Hypothesis, SoilingEvidence } from "../../api/types";
import { fmtDay, fmtEnergy, fmtNumber, fmtPct, humanize } from "../../lib/format";
import { SUPPORT_LABEL, SUPPORT_STYLE } from "../../lib/labels";
import { ProvenanceBadge } from "../badges";
import { Badge, Card, CardHeader } from "../ui";
import { cx } from "../../lib/cx";

const DIRECTION = {
  SUPPORTS: { Icon: ThumbsUp, label: "Supports", className: "text-teal-800" },
  CONTRADICTS: { Icon: ThumbsDown, label: "Contradicts", className: "text-rose-800" },
  CONTEXT: { Icon: Minus, label: "Context", className: "text-ink-500" },
} as const;

function tagLabel(tag: { provenance: string; emulates: string | null }): string {
  return tag.emulates ? `${tag.provenance} (emulates ${tag.emulates})` : tag.provenance;
}

export function HypothesesPanel({ result }: { result: AnalysisResult }) {
  const diagnostics = result.diagnostics;
  return (
    <div className="space-y-6">
      <Card aria-labelledby="diagnostic-title">
        <CardHeader
          id="diagnostic-title"
          title={`Diagnosis: ${humanize(diagnostics.status).toLowerCase()}`}
          description={diagnostics.headline}
        />
        <div className="space-y-4 px-5 py-4 text-sm">
          <p className="text-ink-700">
            Hypotheses are graded by the kind of evidence behind them - strong, moderate, weak, not supported, cannot be
            evaluated. They are not probabilities: no percentage of confidence is computed or shown.
          </p>
          {diagnostics.technical_issues.length > 0 && (
            <div>
              <p className="font-semibold text-ink-900">Open technical issues</p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-ink-700">
                {diagnostics.technical_issues.map((issue) => <li key={issue}>{issue}</li>)}
              </ul>
            </div>
          )}
          <p className="text-ink-700">
            Unexplained residual in the assessment window:{" "}
            <span className="tabular font-medium text-ink-900">{fmtPct(diagnostics.unexplained_residual_pct, 2)}</span>
            {diagnostics.unexplained_residual_material === true && " - material: part of the loss has no established cause."}
            {diagnostics.unexplained_residual_material === false && " - not material."}
            {diagnostics.unexplained_residual_material === null && " - could not be evaluated."}
          </p>
        </div>
      </Card>

      {diagnostics.conflicts.length > 0 && (
        <Card aria-labelledby="conflicts-title" className="border-rose-300">
          <CardHeader id="conflicts-title" title="Conflicting evidence" description="Sources that disagree. A critical conflict blocks any cleaning decision until it is resolved." />
          <ul className="divide-y divide-ink-100">
            {diagnostics.conflicts.map((conflict) => (
              <li key={conflict.code} className="flex gap-3 px-5 py-4 text-sm">
                <AlertOctagon className="mt-0.5 size-5 shrink-0 text-rose-700" aria-hidden />
                <div className="min-w-0">
                  <p className="font-medium text-ink-900">
                    {conflict.description}{" "}
                    <Badge className="ml-1 border-rose-300 bg-rose-50 text-rose-900">{humanize(conflict.severity)}</Badge>
                  </p>
                  <p className="mt-1 text-ink-700">How to resolve it: {conflict.resolution}</p>
                  <p className="mt-1 font-mono text-xs text-ink-500">{conflict.code}</p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <SoilingEvidenceCard evidence={diagnostics.soiling_evidence} />

      <div className="space-y-4">
        {diagnostics.hypotheses.map((hypothesis) => (
          <HypothesisCard key={hypothesis.category} hypothesis={hypothesis} leading={diagnostics.leading.includes(hypothesis.category)} />
        ))}
      </div>
    </div>
  );
}

function Check({ ok, children }: { ok: boolean | null; children: string }) {
  return (
    <li className="flex items-center gap-2">
      <span
        className={cx(
          "grid size-5 shrink-0 place-items-center rounded-full text-xs font-bold",
          ok === true ? "bg-teal-700 text-white" : ok === false ? "bg-rose-700 text-white" : "border border-dashed border-ink-400 text-ink-500",
        )}
        aria-hidden
      >
        {ok === true ? <CheckIcon className="size-3" strokeWidth={3.5} /> : ok === false ? <X className="size-3" strokeWidth={3.5} /> : "?"}
      </span>
      <span>
        {children}: <span className="font-medium">{ok === true ? "yes" : ok === false ? "no" : "not evaluated"}</span>
      </span>
    </li>
  );
}

function SoilingEvidenceCard({ evidence }: { evidence: SoilingEvidence }) {
  return (
    <Card aria-labelledby="soiling-evidence-title">
      <CardHeader
        id="soiling-evidence-title"
        title="Is there credible evidence of soiling?"
        description="Soiling counts only when it is measured directly, recently, above the noise floor, and when it matches the loss it is meant to explain."
      />
      {!evidence.available ? (
        <p className="px-5 py-5 text-sm text-ink-700">
          No soiling measurement is available. Without one, a production gap cannot be attributed to soiling.
        </p>
      ) : (
        <div className="grid gap-6 px-5 py-5 md:grid-cols-2">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-ink-500">Measured loss</dt>
            <dd className="tabular font-medium">
              {fmtPct(evidence.loss_pct, 2)}
              {evidence.std_uncertainty_pct !== null && ` ± ${fmtNumber(evidence.std_uncertainty_pct, 2)} points (k = 1)`}
            </dd>
            <dt className="text-ink-500">Method</dt>
            <dd>{humanize(evidence.method)}</dd>
            <dt className="text-ink-500">Source</dt>
            <dd className="flex flex-wrap items-center gap-2">
              {evidence.reference ?? humanize(evidence.source)}
              {evidence.tag && <ProvenanceBadge label={tagLabel(evidence.tag)} />}
            </dd>
            <dt className="text-ink-500">Last reading</dt>
            <dd>{fmtDay(evidence.observed_on)}{evidence.age_days !== null && ` (${evidence.age_days} day(s) before the end of the period)`}</dd>
            <dt className="text-ink-500">Gap to explain</dt>
            <dd className="tabular">{fmtPct(evidence.gap_to_explain_pct, 2)} (difference {fmtNumber(evidence.gap_minus_soiling_pct, 2)} points, tolerance {fmtNumber(evidence.tolerance_pct, 2)})</dd>
          </dl>
          <div>
            <ul className="space-y-2 text-sm text-ink-800">
              <Check ok={evidence.quantified}>Quantified by a direct method</Check>
              <Check ok={evidence.measured_class}>Counts as a measurement</Check>
              <Check ok={evidence.recent}>Recent enough</Check>
              <Check ok={evidence.above_floor}>Above the credibility floor</Check>
              <Check ok={evidence.consistent_with_gap}>Consistent with the gap</Check>
            </ul>
            <p className="mt-3 text-sm font-semibold text-ink-900">
              {evidence.credible ? "Credible soiling evidence." : "Not credible soiling evidence."}
            </p>
            {evidence.notes.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-600">
                {evidence.notes.map((note) => <li key={note}>{note}</li>)}
              </ul>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function HypothesisCard({ hypothesis, leading }: { hypothesis: Hypothesis; leading: boolean }) {
  const quiet = hypothesis.support === "NOT_SUPPORTED" || hypothesis.support === "NOT_EVALUABLE";
  return (
    <Card as="article" className={cx(leading && "border-ink-800")}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
        <div className="min-w-0">
          <h3 className="font-semibold text-ink-950">
            {hypothesis.title}
            {leading && <span className="ml-2 text-xs font-medium uppercase tracking-wide text-ink-500">leading explanation</span>}
          </h3>
          <p className="mt-1 max-w-3xl text-sm text-ink-700">{hypothesis.summary}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {hypothesis.active_in_window && <Badge className="border-ink-300 bg-white text-ink-700">Active in the window</Badge>}
          <Badge className={SUPPORT_STYLE[hypothesis.support]}>{SUPPORT_LABEL[hypothesis.support] ?? hypothesis.support}</Badge>
        </div>
      </div>
      <details className="border-t border-ink-100" open={!quiet}>
        <summary className="cursor-pointer px-5 py-2.5 text-sm font-medium text-ink-700 hover:bg-ink-50">
          Evidence and reasoning ({hypothesis.evidence.length})
        </summary>
        <div className="space-y-4 px-5 pb-5 pt-1 text-sm">
          {hypothesis.estimated_loss && hypothesis.estimated_loss.value !== null && (
            <p className="text-ink-800">
              Estimated loss: <span className="tabular font-medium">{fmtEnergy(hypothesis.estimated_loss.value)}</span>
              {hypothesis.estimated_loss_share_of_gap_pct !== null && ` (${fmtPct(hypothesis.estimated_loss_share_of_gap_pct, 0)} of the gap)`}
              {hypothesis.estimated_loss.basis && ` · ${humanize(hypothesis.estimated_loss.basis).toLowerCase()}`}
            </p>
          )}
          {hypothesis.uncertainty_note && <p className="text-ink-600">{hypothesis.uncertainty_note}</p>}
          {hypothesis.evidence.length > 0 && (
            <ul className="space-y-2">
              {hypothesis.evidence.map((item) => {
                const direction = DIRECTION[item.direction];
                return (
                  <li key={`${item.code}-${item.statement}`} className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3">
                    <span className={cx("inline-flex items-center gap-1.5 text-xs font-semibold", direction.className)}>
                      <direction.Icon className="size-3.5" aria-hidden />
                      {direction.label}
                    </span>
                    <span className="min-w-0">
                      <span className="break-words text-ink-800">{item.statement}</span>{" "}
                      <span className="mt-1 flex flex-wrap items-center gap-2">
                        <ProvenanceBadge label={tagLabel(item.tag)} />
                        <span className="text-xs text-ink-500">{humanize(item.kind)}</span>
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
          <Bullets title="Rules applied" items={hypothesis.rules} mono />
          <Bullets title="Other explanations that fit the same data" items={hypothesis.competing_explanations} />
          <Bullets title="Evidence that is missing" items={hypothesis.missing_evidence} />
          <Bullets title="How to investigate" items={hypothesis.recommended_investigation} />
        </div>
      </details>
    </Card>
  );
}

function Bullets({ title, items, mono = false }: { title: string; items: string[]; mono?: boolean }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="font-medium text-ink-900">{title}</p>
      <ul className={cx("mt-1 list-disc space-y-1 pl-5 text-ink-700", mono && "font-mono text-xs")}>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  );
}
