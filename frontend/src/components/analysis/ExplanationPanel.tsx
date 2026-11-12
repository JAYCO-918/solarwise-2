import { Bot, Check, Cpu, X } from "lucide-react";
import { useState } from "react";

import { endpoints } from "../../api/endpoints";
import type { AiExplanation, AnalysisResult } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { toApiError } from "../../hooks/useAsync";
import { humanize } from "../../lib/format";
import { Button, Card, CardHeader, ErrorNote, Notice } from "../ui";

/**
 * The explanation written by the engine, and - on request - a rephrasing by a language model.
 * The model receives the finished result and may only reword it; the server checks its text against the result
 * and falls back to the engine's text when a check fails.
 */
export function ExplanationPanel({ result, analysisId }: { result: AnalysisResult; analysisId: number | null }) {
  const { meta } = useAuth();
  const explanation = result.explanation;
  const [rephrased, setRephrased] = useState<AiExplanation | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  async function rephrase() {
    if (analysisId === null) return;
    setBusy(true);
    setError(null);
    try {
      setRephrased(await endpoints.explanation(analysisId));
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card aria-labelledby="explanation-title">
        <CardHeader
          id="explanation-title"
          title={explanation.title}
          description={
            <span className="inline-flex items-center gap-1.5">
              <Cpu className="size-4" aria-hidden /> Written by the deterministic engine from the result. No language model was involved.
            </span>
          }
        />
        <div className="space-y-6 px-5 py-5">
          <p className="max-w-4xl text-ink-800">{explanation.summary}</p>
          {explanation.sections.map((section) => (
            <section key={section.key} aria-labelledby={`section-${section.key}`}>
              <h3 id={`section-${section.key}`} className="text-sm font-semibold uppercase tracking-wide text-ink-500">{section.title}</h3>
              <div className="mt-2 max-w-4xl space-y-2 text-sm text-ink-800">
                {section.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
                {section.bullets.length > 0 && (
                  <ul className="list-disc space-y-1 pl-5">
                    {section.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}
                  </ul>
                )}
              </div>
            </section>
          ))}
          <p className="max-w-4xl border-t border-ink-100 pt-4 text-xs text-ink-500">{explanation.provenance_statement}</p>
        </div>
      </Card>

      {analysisId !== null && (
        <Card aria-labelledby="rephrase-title">
          <CardHeader
            id="rephrase-title"
            title="Plain-language version"
            description="Optional. A language model may reword the explanation above. It never decides, never adds a figure, and its text is checked against the result before it is shown."
            actions={<Button size="sm" busy={busy} onClick={rephrase}><Bot className="size-4" aria-hidden /> {rephrased ? "Request again" : "Request"}</Button>}
          />
          <div className="space-y-4 px-5 py-5">
            {meta && !meta.ai.enabled && !rephrased && (
              <p className="text-sm text-ink-600">
                No language model is configured on this server. A request returns the engine&apos;s own text, and says so.
              </p>
            )}
            {error && <ErrorNote error={error} />}
            {rephrased && (
              <>
                <Notice tone={rephrased.generated_by === "AI_REPHRASED" ? "info" : "neutral"} title={rephrased.generated_by === "AI_REPHRASED" ? "Reworded by a language model" : "Engine text"}>
                  {rephrased.notice}
                  {rephrased.provider && <span className="block font-mono text-xs">{rephrased.provider}{rephrased.model ? ` · ${rephrased.model}` : ""}</span>}
                  {rephrased.fallback_reason && <span className="mt-1 block">Why the engine text is shown: {rephrased.fallback_reason}</span>}
                </Notice>
                <p className="text-sm font-semibold text-ink-900">{rephrased.decision_statement}</p>
                <div className="max-w-4xl space-y-2 whitespace-pre-line text-sm text-ink-800">{rephrased.text}</div>
                {rephrased.checks.length > 0 && (
                  <div>
                    <p className="text-sm font-medium text-ink-900">Checks applied to the model&apos;s text</p>
                    <ul className="mt-2 space-y-1.5 text-sm">
                      {rephrased.checks.map((check) => (
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
                  </div>
                )}
              </>
            )}
          </div>
        </Card>
      )}

      {result.disclaimers.length > 0 && (
        <Card aria-labelledby="disclaimers-title">
          <CardHeader id="disclaimers-title" title="Statements that apply to this result" />
          <ul className="list-disc space-y-2 px-5 py-5 pl-10 text-sm text-ink-700">
            {result.disclaimers.map((disclaimer) => <li key={disclaimer}>{disclaimer}</li>)}
          </ul>
        </Card>
      )}
    </div>
  );
}
