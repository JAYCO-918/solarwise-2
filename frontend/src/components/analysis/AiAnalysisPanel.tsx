import { Bot, Check, Download, X } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { download } from "../../api/client";
import { endpoints } from "../../api/endpoints";
import type { AnalysisResult, Insight, InsightCause, InsightItem, InsightOut } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { toApiError, useAsync } from "../../hooks/useAsync";
import { cx } from "../../lib/cx";
import { fmtEnergy, fmtInstant, fmtPct, humanize } from "../../lib/format";
import { DECISION_STYLE, FACTOR_STATUS_LABEL, SUPPORT_LABEL, SUPPORT_STYLE, isDecision } from "../../lib/labels";
import { SourceTag } from "../SourceTag";
import { SimulatedTag } from "../badges";
import { Badge, Button, Card, CardHeader, ErrorNote, Loading, Notice } from "../ui";

const REPORT_FORMATS = [
  { key: "pdf", label: "PDF" },
  { key: "html", label: "HTML" },
  { key: "json", label: "JSON" },
] as const;

/** A block of the page with a tag saying who produced it. */
function Section({ id, title, source, children, note }: {
  id: string;
  title: string;
  source: "engine" | "ai";
  children: ReactNode;
  note?: string;
}) {
  return (
    <section aria-labelledby={id} className={cx("border-l-4 px-5 py-4", source === "ai" ? "border-l-indigo-300" : "border-l-ink-300")}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={id} className="text-sm font-semibold uppercase tracking-wide text-ink-600">{title}</h3>
        <SourceTag source={source} />
        {note && <span className="text-xs text-ink-500">{note}</span>}
      </div>
      <div className="mt-2 max-w-4xl space-y-2 text-sm text-ink-800">{children}</div>
    </section>
  );
}

function Items({ items, narrative, empty }: { items: InsightItem[]; narrative: "engine" | "ai"; empty: string }) {
  if (items.length === 0) return <p className="text-ink-600">{empty}</p>;
  return (
    <ol className="list-decimal space-y-2 pl-5">
      {items.map((item) => (
        <li key={item.id}>
          <span>{item.text}</span>
          {item.why && (
            <span className="mt-0.5 flex flex-wrap items-start gap-1.5 text-ink-700">
              <SourceTag source={narrative}>{narrative === "ai" ? "Why, says the AI" : "Why"}</SourceTag>
              <span className="min-w-0 flex-1">{item.why}</span>
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

function CauseCard({ cause, narrative }: { cause: InsightCause; narrative: "engine" | "ai" }) {
  const support = SUPPORT_LABEL[cause.engine_support] ?? FACTOR_STATUS_LABEL[cause.engine_support] ?? humanize(cause.engine_support);
  const style = SUPPORT_STYLE[cause.engine_support] ?? "bg-white text-ink-700 border-ink-300";
  const evidence = cause.evidence_for.length + cause.evidence_against.length + cause.context.length + cause.missing_evidence.length;
  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="font-medium text-ink-950">{cause.title}</h4>
        <Badge className={style} title="Rated by the engine from the evidence">{support}</Badge>
        {cause.active_now && <Badge className="border-amber-300 bg-amber-50 text-amber-900">present in the assessment window</Badge>}
        {cause.estimated_loss_kwh !== null && cause.estimated_loss_kwh > 0 && (
          <span className="text-xs text-ink-600">
            engine estimate {fmtEnergy(cause.estimated_loss_kwh)}{cause.share_of_gap_pct !== null ? `, ${fmtPct(cause.share_of_gap_pct)} of the gap` : ""}
          </span>
        )}
      </div>
      <div className="mt-2 grid gap-2 text-sm md:grid-cols-[auto_minmax(0,1fr)]">
        <SourceTag source="engine" className="h-fit justify-self-start" />
        <p className="text-ink-800">{cause.engine_summary}</p>
        {cause.interpretation && (
          <>
            <SourceTag source={narrative} className="h-fit justify-self-start" />
            <p className="text-ink-800">{cause.interpretation}</p>
          </>
        )}
      </div>
      {evidence > 0 && (
        <details className="mt-2 text-sm text-ink-700">
          <summary className="cursor-pointer font-medium text-ink-700">Evidence held by the engine ({evidence})</summary>
          <ul className="mt-1.5 space-y-1 pl-1">
            {cause.evidence_for.map((item) => <li key={`f-${item}`}><span className="font-medium text-teal-800">Supports: </span>{item}</li>)}
            {cause.evidence_against.map((item) => <li key={`a-${item}`}><span className="font-medium text-rose-800">Contradicts: </span>{item}</li>)}
            {cause.context.map((item) => <li key={`c-${item}`}><span className="font-medium">Context: </span>{item}</li>)}
            {cause.missing_evidence.map((item) => <li key={`m-${item}`}><span className="font-medium text-amber-800">Missing: </span>{item}</li>)}
          </ul>
        </details>
      )}
    </li>
  );
}

function Origin({ insight, stored }: { insight: Insight; stored: boolean }) {
  const ai = insight.generated_by === "AI";
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-700">
      <SourceTag source={ai ? "ai" : "engine"}>{ai ? "Narrative written by a language model" : "Narrative assembled by the engine"}</SourceTag>
      {ai ? (
        <span>
          <span className="font-mono text-xs">{insight.provider} · {insight.model}</span> · {fmtInstant(insight.generated_at)} ·{" "}
          {insight.checks.filter((c) => c.passed).length} checks passed
        </span>
      ) : (
        <span>{stored ? `kept since ${fmtInstant(insight.generated_at)}` : "assembled for this page; no language model was involved"}</span>
      )}
    </div>
  );
}

/**
 * What the findings of the engine mean, section by section, with a tag on each saying who produced it.
 * The decision, the gates, the support of each cause, the evidence, the steps and every figure are the engine's.
 * A language model, when one is configured, writes the narrative only - and the server checks it first.
 */
export function AiAnalysisPanel({ result, analysisId }: { result: AnalysisResult; analysisId: number }) {
  const { meta, user } = useAuth();
  const loaded = useAsync((signal) => endpoints.insight(analysisId, signal), [analysisId]);
  const [generated, setGenerated] = useState<InsightOut | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const aiEnabled = meta?.ai.enabled ?? false;
  const readOnly = user?.role === "VIEWER";

  async function generate() {
    setBusy("generate");
    setError(null);
    try {
      setGenerated(await endpoints.generateInsight(analysisId));
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function saveReport(format: string) {
    setBusy(format);
    setError(null);
    try {
      await download(`/analyses/${analysisId}/operational-report.${format}`, `solarwise-operational-report-${analysisId}.${format}`);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(null);
    }
  }

  const current = generated ?? loaded.data;
  if (loaded.loading && !current) return <Loading label="Loading the analysis of the findings" />;
  if (loaded.error && !current) return <ErrorNote error={loaded.error} onRetry={loaded.reload} />;
  if (!current) return null;
  const insight = current.insight;
  const narrative = insight.generated_by === "AI" ? "ai" : "engine";
  const decision = insight.decision;
  const passed = insight.gates.filter((g) => g.passed === true);
  const failed = insight.gates.filter((g) => g.passed === false);
  const unknown = insight.gates.filter((g) => g.passed === null);
  const style = isDecision(decision.value) ? DECISION_STYLE[decision.value] : null;

  return (
    <div className="space-y-6">
      <Card aria-labelledby="ai-title">
        <CardHeader
          id="ai-title"
          title="AI analysis of the findings"
          description="An interpretation of what the engine found: what it means, which explanations the evidence supports, what is uncertain or missing, and what matters most. It explains the engine's decision; it does not take one."
          actions={
            <div className="no-print flex flex-wrap items-center gap-2">
              {!readOnly && (
                <Button size="sm" variant={aiEnabled && narrative !== "ai" ? "primary" : "secondary"} busy={busy === "generate"} disabled={busy !== null || !aiEnabled} onClick={() => void generate()}>
                  <Bot className="size-4" aria-hidden /> {narrative === "ai" ? "Generate again" : "Generate the AI analysis"}
                </Button>
              )}
            </div>
          }
        />
        <div className="space-y-4 px-5 py-4">
          <Origin insight={insight} stored={current.stored} />
          {!aiEnabled && (
            <Notice tone="neutral" title="No language model is configured on this server">
              The deterministic fallback is active: every section below is assembled by the engine from its own
              findings, and it is complete. With a model configured, the sections marked as narrative are written by it
              and checked against the findings.
            </Notice>
          )}
          {insight.fallback_reason && (
            <Notice tone="warning" title="A language model was asked, and its answer was not used">
              {insight.fallback_reason}. The engine&apos;s own text is shown instead.
              {insight.provider && <span className="mt-1 block font-mono text-xs">{insight.provider}{insight.model ? ` · ${insight.model}` : ""}</span>}
            </Notice>
          )}
          {error && <ErrorNote error={error} />}
          <div role="group" aria-label="Download the operational report" className="no-print flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-sm text-ink-600">
              <Download className="size-4" aria-hidden /> Operational report
            </span>
            {REPORT_FORMATS.map((format) => (
              <Button key={format.key} size="sm" aria-label={`Operational report as ${format.label}`} busy={busy === format.key} disabled={busy !== null} onClick={() => void saveReport(format.key)}>
                {format.label}
              </Button>
            ))}
            <span className="text-xs text-ink-500">Eight sections, each saying who wrote it; the engine&apos;s tables in annex.</span>
          </div>
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-ink-100 pt-3 text-xs text-ink-600">
            How to read this page:
            <span className="inline-flex items-center gap-1.5"><SourceTag source="engine" /> a result of the deterministic engine - authoritative</span>
            <span className="inline-flex items-center gap-1.5"><SourceTag source="ai" /> text written by a language model from those results</span>
          </p>
        </div>
      </Card>

      <Card aria-labelledby="ai-decision-title" className={cx("border-l-8", style?.border ?? "border-l-ink-300")}>
        <div className="px-5 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id="ai-decision-title" className="text-sm font-semibold uppercase tracking-wide text-ink-600">The engine&apos;s decision</h3>
            <SourceTag source="engine" />
            {decision.simulated && <SimulatedTag />}
          </div>
          <p className="mt-2 text-lg font-semibold text-ink-950">{decision.statement}</p>
          <p className="mt-1 max-w-4xl text-sm text-ink-700">{decision.headline}</p>
          <p className="mt-1 text-xs text-ink-500">
            Rule {decision.rule} · {passed.length} of {insight.gates.length} gates passed · {decision.authorization_note}
          </p>
        </div>
      </Card>

      <Card aria-label="Reading of the findings">
        <div className="divide-y divide-ink-100">
          <Section id="ai-summary" title="Summary" source={narrative}><p>{insight.executive_summary}</p></Section>
          <Section id="ai-performance" title="Plant performance" source={narrative}><p>{insight.performance_overview}</p></Section>
          <Section id="ai-anomalies" title="Main anomalies" source={narrative}>
            {insight.anomalies.length === 0
              ? <p className="text-ink-600">The findings contain no anomaly.</p>
              : <ul className="list-disc space-y-1 pl-5">{insight.anomalies.map((item) => <li key={item}>{item}</li>)}</ul>}
          </Section>
        </div>
      </Card>

      <Card aria-labelledby="ai-causes-title">
        <CardHeader
          id="ai-causes-title"
          title="Possible explanations of the deviation"
          description="The support given to each explanation and the evidence behind it are the engine's. No probability is stated. A production gap alone is never taken as soiling."
        />
        <ul className="divide-y divide-ink-100">
          {insight.causes.map((cause) => <CauseCard key={cause.category} cause={cause} narrative={narrative} />)}
        </ul>
      </Card>

      <Card aria-label="Data, economics and decision">
        <div className="divide-y divide-ink-100">
          <Section id="ai-quality" title="Data quality" source={narrative} note={`engine status: ${humanize(insight.data_quality_status).toLowerCase()}`}>
            <p>{insight.data_quality_assessment}</p>
          </Section>
          <Section
            id="ai-economics" title="Economic implications" source={narrative}
            note={`engine status: ${humanize(insight.economics_status).toLowerCase()}; ${insight.economics_decision_grade ? "decision grade" : "not decision grade"}`}
          >
            <p>{insight.economic_implications}</p>
          </Section>
          <Section id="ai-rationale" title="Why the engine decided this" source={narrative}><p>{insight.decision_rationale}</p></Section>
          <Section id="ai-gates" title="Gates behind the decision" source="engine">
            <ul className="space-y-1.5">
              {[...failed, ...unknown, ...passed].map((gate) => (
                <li key={gate.id} className="flex items-start gap-2">
                  {gate.passed === true && <Check className="mt-0.5 size-4 shrink-0 text-teal-700" aria-hidden />}
                  {gate.passed === false && <X className="mt-0.5 size-4 shrink-0 text-rose-700" aria-hidden />}
                  {gate.passed === null && <span className="mt-0.5 inline-block size-4 shrink-0 text-center text-ink-400" aria-hidden>?</span>}
                  <span>
                    <span className="font-medium">{gate.label}</span>
                    <span className="sr-only">{gate.passed === true ? " - passed" : gate.passed === false ? " - not passed" : " - not evaluable"}</span>
                    <span className="text-ink-600"> - {gate.basis}</span>
                  </span>
                </li>
              ))}
            </ul>
          </Section>
          <Section id="ai-change" title="What would change the decision" source="engine">
            {insight.what_would_change.length === 0
              ? <p className="text-ink-600">Nothing is listed.</p>
              : <ul className="list-disc space-y-1 pl-5">{insight.what_would_change.map((item) => <li key={item}>{item}</li>)}</ul>}
          </Section>
        </div>
      </Card>

      <Card aria-label="What to do and what is missing">
        <div className="divide-y divide-ink-100">
          <Section id="ai-steps" title="Recommended next steps" source="engine" note={narrative === "ai" ? "the order and the reasons are the AI's; the steps are the engine's" : undefined}>
            <Items items={insight.next_steps} narrative={narrative} empty="The engine proposes no step." />
          </Section>
          <Section id="ai-missing" title="Information that is missing" source="engine" note={narrative === "ai" ? "the order and the reasons are the AI's" : undefined}>
            <Items items={insight.missing_information} narrative={narrative} empty="The engine lists no missing input." />
          </Section>
          <Section id="ai-limits" title="Uncertainty and limitations" source={narrative}>
            <ul className="list-disc space-y-1 pl-5">
              {[...insight.uncertainty, ...insight.limitations].map((item) => <li key={item}>{item}</li>)}
            </ul>
          </Section>
        </div>
      </Card>

      {insight.checks.length > 0 && (
        <Card aria-labelledby="ai-checks-title">
          <CardHeader
            id="ai-checks-title"
            title="Checks applied to the model's text"
            description="Before any sentence of a language model is shown, the server checks it against the engine's findings. One failed check and the whole answer is discarded."
          />
          <ul className="space-y-1.5 px-5 py-4 text-sm">
            {insight.checks.map((check) => (
              <li key={check.name} className="flex items-start gap-2">
                {check.passed
                  ? <Check className="mt-0.5 size-4 shrink-0 text-teal-700" aria-hidden />
                  : <X className="mt-0.5 size-4 shrink-0 text-rose-700" aria-hidden />}
                <span>
                  <span className="font-medium">{humanize(check.name)}</span>
                  <span className="sr-only">{check.passed ? " passed" : " failed"}</span>
                  {check.detail && <span className="text-ink-600"> - {check.detail}</span>}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <p className="text-xs text-ink-500">
        {insight.notice} Evidence packet SHA-256 <span className="break-all font-mono">{insight.packet_sha256}</span>.
        {current.history.length > 1 && ` ${current.history.length} interpretations are kept for this analysis; the latest is shown.`}
        {result.recommendation.simulated && " The decision is simulated: nothing on this page is an operational instruction."}
      </p>
    </div>
  );
}
