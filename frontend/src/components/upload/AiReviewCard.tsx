import { Bot, Check } from "lucide-react";
import { useState } from "react";

import { endpoints } from "../../api/endpoints";
import type { DataReview, DataSuggestion } from "../../api/types";
import { toApiError } from "../../hooks/useAsync";
import { fmtInstant } from "../../lib/format";
import { metricLabel, unitLabel } from "../../lib/labels";
import { SourceTag } from "../SourceTag";
import { Button, ErrorNote, Notice } from "../ui";

function describe(suggestion: DataSuggestion): string {
  if (suggestion.role === "QUANTITY" && suggestion.metric) {
    const loss = suggestion.metric === "soiling_ratio" && suggestion.reported_as === "LOSS";
    return `${loss ? "Soiling loss" : metricLabel(suggestion.metric)}, in ${unitLabel(suggestion.unit) || "the stored unit"}`;
  }
  return { TIMESTAMP: "Date and time", DEVICE: "Device code", CLEANING: "Cleaning marks", EVENTS: "Alarms and events", UNUSED: "Not used", QUANTITY: "A quantity" }[suggestion.role];
}

function current(suggestion: DataSuggestion): string {
  const now = suggestion.current;
  if (now.role === "QUANTITY" && now.metric) return `${metricLabel(now.metric).toLowerCase()}${now.unit ? `, in ${unitLabel(now.unit)}` : ""}`;
  return { TIMESTAMP: "date and time", DEVICE: "device code", CLEANING: "cleaning marks", EVENTS: "alarms and events", UNUSED: "not used" }[now.role] ?? "not used";
}

/**
 * A second reading of the file by a language model. It sees column names, a few sample values and simple statistics -
 * not the file. Each suggestion was checked by the server; none is applied until the uploader accepts it, and the file
 * is validated in the same way whatever is accepted.
 */
export function AiReviewCard({ plantId, file, enabled, applied, onApply }: {
  plantId: number;
  file: File;
  /** A language model is configured on this server. */
  enabled: boolean;
  /** Columns whose suggestion was accepted. */
  applied: string[];
  onApply: (suggestion: DataSuggestion) => void;
}) {
  const [review, setReview] = useState<DataReview | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  async function ask() {
    setBusy(true);
    setError(null);
    try {
      setReview(await endpoints.reviewUpload(plantId, file));
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  const byAi = review?.generated_by === "AI";
  return (
    <section aria-labelledby="ai-review-title" className="border-t border-ink-100 px-5 py-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id="ai-review-title" className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink-900">
            Second reading by the AI assistant <SourceTag source="ai">Optional</SourceTag>
          </h3>
          <p className="mt-1 max-w-3xl text-sm text-ink-600">
            Useful when a header is abbreviated or ambiguous. The assistant is sent the column names, a few sample
            values and simple statistics - never the file. It can only suggest: you accept or ignore each suggestion,
            and it never says where data come from.
          </p>
        </div>
        <Button size="sm" busy={busy} disabled={!enabled} onClick={() => void ask()}>
          <Bot className="size-4" aria-hidden /> {review ? "Ask again" : "Ask the AI assistant"}
        </Button>
      </div>
      {!enabled && (
        <p className="mt-3 text-sm text-ink-600">
          No language model is configured on this server. The reading above is the deterministic one, and it is complete:
          every column can be assigned by hand below.
        </p>
      )}
      {error && <div className="mt-3"><ErrorNote error={error} /></div>}
      {review && (
        <div className="mt-4 space-y-4">
          <Notice tone={byAi ? "info" : "neutral"} title={byAi ? "Suggestions of a language model" : "No suggestion from a language model"}>
            {review.notice}
            {review.fallback_reason && <span className="mt-1 block">Why: {review.fallback_reason}.</span>}
            {review.provider && (
              <span className="mt-1 block font-mono text-xs">
                {review.provider}{review.model ? ` · ${review.model}` : ""} · {fmtInstant(review.generated_at)}
              </span>
            )}
          </Notice>
          {byAi && review.suggestions.length === 0 && (
            <p className="text-sm text-ink-700">The assistant suggests no change to the mapping.</p>
          )}
          {review.suggestions.length > 0 && (
            <ul className="divide-y divide-ink-100 rounded-md border border-ink-200" aria-label="Suggestions of the AI assistant">
              {review.suggestions.map((suggestion) => {
                const done = applied.includes(suggestion.column);
                return (
                  <li key={suggestion.column} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 text-sm">
                    <div className="min-w-0">
                      <p className="text-ink-900">
                        Use <span className="font-mono text-xs">{suggestion.column}</span> as{" "}
                        <span className="font-medium">{describe(suggestion)}</span>
                        <span className="text-ink-500"> (now: {current(suggestion)})</span>
                      </p>
                      <p className="mt-0.5 text-ink-600">{suggestion.reason}</p>
                    </div>
                    {done ? (
                      <span className="inline-flex items-center gap-1 text-sm font-medium text-teal-800"><Check className="size-4" aria-hidden /> Accepted</span>
                    ) : (
                      <Button size="sm" aria-label={`Accept the suggestion for ${suggestion.column}`} onClick={() => onApply(suggestion)}>
                        Accept
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {review.observations.length > 0 && (
            <div>
              <p className="text-sm font-medium text-ink-900">What the assistant remarks about the values <span className="font-normal text-ink-500">- to verify, nothing was changed</span></p>
              <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-ink-700">
                {review.observations.map((observation) => (
                  <li key={observation.text}>
                    {observation.column && <span className="font-mono text-xs">{observation.column}: </span>}{observation.text}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {review.missing_context.length > 0 && (
            <div>
              <p className="text-sm font-medium text-ink-900">Context the assistant says is missing</p>
              <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-ink-700">
                {review.missing_context.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
          )}
          {review.discarded.length > 0 && (
            <details className="text-sm text-ink-600">
              <summary className="cursor-pointer font-medium text-ink-700">
                {review.discarded.length} proposal(s) of the assistant were discarded by the server's checks
              </summary>
              <ul className="mt-1.5 list-disc space-y-1 pl-5">
                {review.discarded.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
