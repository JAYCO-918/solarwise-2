import { ArrowRight, Check, CircleSlash, FlaskConical, Minus, ShieldAlert, ShieldCheck, X } from "lucide-react";

import type { AnalysisResult, Gate } from "../../api/types";
import { fmtDay, fmtPct, humanize } from "../../lib/format";
import { DECISION_STYLE, isDecision } from "../../lib/labels";
import { DecisionBadge, ProvenanceBadge } from "../badges";
import { Card, CardHeader } from "../ui";
import { cx } from "../../lib/cx";

function tagLabel(tag: { provenance: string; emulates: string | null }): string {
  return tag.emulates ? `${tag.provenance} (emulates ${tag.emulates})` : tag.provenance;
}

/** The decision, its marking, the reasons and what follows from it. Nothing here is computed in the browser. */
export function DecisionPanel({ result }: { result: AnalysisResult }) {
  const rec = result.recommendation;
  const style = isDecision(rec.decision) ? DECISION_STYLE[rec.decision] : DECISION_STYLE.MONITOR;
  const window = result.gap.window;

  return (
    <Card aria-labelledby="decision-title" className={cx("overflow-hidden border-l-4", style.border)}>
      {rec.simulated && (
        <div className="simulated-stripes flex items-start gap-2 border-b border-violet-300 bg-violet-50 px-5 py-2.5 text-sm text-violet-950">
          <FlaskConical className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>
            <strong className="font-semibold">SIMULATED DECISION.</strong> It rests on demonstration data and is not an
            operational instruction.
          </p>
        </div>
      )}
      <div className="grid gap-6 px-5 py-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Decision of the rule engine · rule {rec.rule} · {humanize(rec.reason_code)}
          </p>
          <div className="mt-2">
            <DecisionBadge decision={rec.decision} simulated={rec.simulated} size="lg" />
          </div>
          <h2 id="decision-title" className="mt-3 text-lg font-semibold leading-snug text-ink-950">{rec.headline}</h2>

          <div
            className={cx(
              "mt-4 flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
              rec.operational_authorization ? "border-teal-300 bg-teal-50 text-teal-950" : "border-ink-200 bg-ink-50 text-ink-800",
            )}
          >
            {rec.operational_authorization
              ? <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
              : <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />}
            <p>
              <strong className="font-semibold">
                {rec.operational_authorization ? "Operational authorisation issued." : "No operational authorisation."}
              </strong>{" "}
              {rec.authorization_note}
            </p>
          </div>
          {rec.safety_interlock_triggered && (
            <p role="alert" className="mt-3 rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-900">
              The safety interlock withheld a cleaning decision that the gates did not justify.
            </p>
          )}
        </div>

        <dl className="grid grid-cols-2 gap-4 self-start rounded-md bg-ink-50 p-4 lg:grid-cols-1">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-500">Gap, assessment window</dt>
            <dd className="tabular mt-0.5 text-2xl font-semibold text-ink-950">{fmtPct(window.result.relative_gap_pct)}</dd>
            <dd className="text-xs text-ink-500">{fmtDay(window.start)} – {fmtDay(window.end)}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-500">Gap, whole period</dt>
            <dd className="tabular mt-0.5 text-2xl font-semibold text-ink-950">{fmtPct(result.gap.result.relative_gap_pct)}</dd>
            <dd className="text-xs text-ink-500">{fmtDay(result.period_start)} – {fmtDay(result.period_end)}</dd>
          </div>
          <div className="col-span-2 lg:col-span-1">
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-500">Diagnostic status</dt>
            <dd className="mt-0.5 text-sm font-medium text-ink-900">{humanize(result.diagnostics.status)}</dd>
          </div>
        </dl>
      </div>

      <div className="grid gap-x-8 gap-y-6 border-t border-ink-100 px-5 py-5 md:grid-cols-2">
        <ListBlock title="Why" items={rec.reasons} />
        <div className="space-y-6">
          <ListBlock title="Next steps" items={rec.next_actions} icon />
          <ListBlock title="What would change this decision" items={rec.would_change_decision} />
          {rec.review_after_days !== null && (
            <p className="text-sm text-ink-700">Review after {rec.review_after_days} day(s).</p>
          )}
        </div>
      </div>

      <div className="border-t border-ink-100 px-5 py-4">
        <h3 className="text-sm font-semibold text-ink-900">Evidence the decision rests on</h3>
        {rec.decisive_evidence.length === 0 ? (
          <p className="mt-1 text-sm text-ink-600">No decisive evidence: nothing in the data is strong enough to carry a decision.</p>
        ) : (
          <ul className="mt-2 flex flex-wrap gap-x-6 gap-y-2 text-sm">
            {rec.decisive_evidence.map((item) => (
              <li key={item.label} className="flex flex-wrap items-center gap-2">
                <span className="text-ink-800">{item.label}</span>
                <ProvenanceBadge label={tagLabel(item.tag)} />
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 font-mono text-xs text-ink-500">Rule trace: {rec.rule_trace.join(" › ")}</p>
      </div>
    </Card>
  );
}

function ListBlock({ title, items, icon = false }: { title: string; items: string[]; icon?: boolean }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
      <ul className="mt-2 space-y-1.5 text-sm text-ink-800">
        {items.map((item) => (
          <li key={item} className="flex gap-2">
            {icon
              ? <ArrowRight className="mt-0.5 size-4 shrink-0 text-ink-400" aria-hidden />
              : <span className="mt-2 size-1.5 shrink-0 rounded-full bg-ink-400" aria-hidden />}
            <span className="min-w-0 break-words">{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function gateState(gate: Gate): { label: string; className: string; Icon: typeof Check } {
  if (gate.passed === true) return { label: "Passed", className: "bg-teal-700 text-white", Icon: Check };
  if (gate.passed === false) return { label: "Not passed", className: "bg-rose-700 text-white", Icon: X };
  return { label: "Not evaluated", className: "border border-dashed border-ink-400 bg-white text-ink-600", Icon: Minus };
}

/** The ten gates. CLEAN_NOW requires all of them; each one shows what it found. */
export function GatesPanel({ result }: { result: AnalysisResult }) {
  const gates = result.recommendation.gates;
  const passed = gates.filter((g) => g.passed === true).length;
  return (
    <Card aria-labelledby="gates-title">
      <CardHeader
        id="gates-title"
        title={`Gates: ${passed} of ${gates.length} passed`}
        description="“Clean now” is issued only when every gate is passed. A gate that could not be evaluated counts as not passed."
      />
      <ol className="divide-y divide-ink-100">
        {gates.map((gate, index) => {
          const state = gateState(gate);
          return (
            <li key={gate.id} className="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-3 px-5 py-3 sm:grid-cols-[2rem_minmax(0,1fr)_8.5rem]">
              <span className="tabular pt-0.5 text-sm text-ink-400">{index + 1}</span>
              <div className="min-w-0">
                <p className="font-medium text-ink-900">{gate.label}</p>
                <p className="mt-0.5 break-words text-sm text-ink-600">{gate.detail}</p>
              </div>
              <div className="col-start-2 mt-2 sm:col-start-3 sm:mt-0 sm:justify-self-end">
                <span className={cx("inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold", state.className)}>
                  <state.Icon className="size-3.5" aria-hidden />
                  {state.label}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
      {result.evidence.reasons_production_unreliable.length > 0 && (
        <div className="border-t border-ink-100 px-5 py-4 text-sm">
          <p className="flex items-center gap-2 font-semibold text-ink-900">
            <CircleSlash className="size-4" aria-hidden /> Why production does not count as reliably measured
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-6 text-ink-700">
            {result.evidence.reasons_production_unreliable.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </div>
      )}
    </Card>
  );
}
