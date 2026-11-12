import { CircleHelp, Eye, FlaskConical, Gauge, Search, SprayCan, Waypoints } from "lucide-react";
import type { ReactNode } from "react";

import type { Decision } from "../api/types";
import { DECISION_LABEL, DECISION_STYLE, PROVENANCE_MEANING, PROVENANCE_STYLE, isDecision, isProvenance } from "../lib/labels";
import { Badge } from "./ui";
import { cx } from "../lib/cx";

const DECISION_ICON: Record<Decision, typeof Eye> = { CLEAN_NOW: SprayCan, INVESTIGATE: Search, MONITOR: Eye };

/** The decision, always with its label and - when it applies - the word "simulated". */
export function DecisionBadge({ decision, simulated, size = "md" }: {
  decision: string; simulated: boolean; size?: "sm" | "md" | "lg";
}) {
  const known = isDecision(decision) ? decision : null;
  const Icon = known ? DECISION_ICON[known] : CircleHelp;
  const style = known ? DECISION_STYLE[known].solid : "bg-ink-200 text-ink-900";
  const sizing = { sm: "px-2 py-0.5 text-xs gap-1", md: "px-2.5 py-1 text-sm gap-1.5", lg: "px-4 py-2 text-lg gap-2" }[size];
  const icon = { sm: "size-3.5", md: "size-4", lg: "size-5" }[size];
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className={cx("inline-flex items-center rounded-md font-semibold", style, sizing)}>
        <Icon className={icon} aria-hidden />
        {known ? DECISION_LABEL[known] : decision}
      </span>
      {simulated && <SimulatedTag size={size === "lg" ? "md" : "sm"} />}
    </span>
  );
}

export function SimulatedTag({ size = "sm" }: { size?: "sm" | "md" }) {
  return (
    <span
      title="Simulated decision on demonstration data. Not an operational instruction."
      className={cx(
        "simulated-stripes inline-flex items-center gap-1 rounded-md border border-violet-400 bg-violet-50 font-semibold uppercase tracking-wide text-violet-900",
        size === "md" ? "px-2.5 py-1.5 text-sm" : "px-1.5 py-0.5 text-[0.6875rem]",
      )}
    >
      <FlaskConical className={size === "md" ? "size-4" : "size-3"} aria-hidden />
      Simulated
    </span>
  );
}

const PROVENANCE_ICON = { MEASURED: Gauge, MODELLED: Waypoints, SYNTHETIC: FlaskConical, UNKNOWN: CircleHelp };

/**
 * Provenance as declared. `label` may be the server's full label, for example "SYNTHETIC (emulates MEASURED)";
 * the colour follows the declared class, never the class it stands in for.
 */
export function ProvenanceBadge({ label, children }: { label: string; children?: ReactNode }) {
  const declared = label.split(" ")[0] ?? label;
  const known = isProvenance(declared) ? declared : "UNKNOWN";
  const Icon = PROVENANCE_ICON[known];
  return (
    <Badge className={PROVENANCE_STYLE[known]} title={PROVENANCE_MEANING[known]}>
      <Icon className="size-3" aria-hidden />
      {children ?? label}
    </Badge>
  );
}
