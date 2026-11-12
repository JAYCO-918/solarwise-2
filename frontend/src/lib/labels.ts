import type { Decision, Provenance } from "../api/types";

export const DECISION_LABEL: Record<Decision, string> = {
  CLEAN_NOW: "Clean now",
  INVESTIGATE: "Investigate",
  MONITOR: "Monitor",
};

export const DECISION_MEANING: Record<Decision, string> = {
  CLEAN_NOW: "Every gate is passed: measured soiling explains the loss and cleaning pays.",
  INVESTIGATE: "Something is not established. Find out before acting.",
  MONITOR: "Nothing calls for action now. Keep observing.",
};

/** Class names per decision. Colour is always accompanied by the label and an icon. */
export const DECISION_STYLE: Record<Decision, { solid: string; soft: string; text: string; border: string }> = {
  CLEAN_NOW: {
    solid: "bg-teal-700 text-white",
    soft: "bg-teal-50 text-teal-900",
    text: "text-teal-800",
    border: "border-teal-600",
  },
  INVESTIGATE: {
    solid: "bg-amber-500 text-ink-950",
    soft: "bg-amber-50 text-amber-950",
    text: "text-amber-800",
    border: "border-amber-500",
  },
  MONITOR: {
    solid: "bg-ink-600 text-white",
    soft: "bg-ink-100 text-ink-900",
    text: "text-ink-700",
    border: "border-ink-500",
  },
};

export const PROVENANCE_STYLE: Record<Provenance, string> = {
  MEASURED: "bg-emerald-50 text-emerald-900 border-emerald-300",
  MODELLED: "bg-sky-50 text-sky-900 border-sky-300",
  SYNTHETIC: "bg-violet-50 text-violet-900 border-violet-300",
  UNKNOWN: "bg-ink-100 text-ink-700 border-ink-300 border-dashed",
};

export const PROVENANCE_MEANING: Record<Provenance, string> = {
  MEASURED: "Read from an identified instrument. Can support a decision.",
  MODELLED: "Computed by a model or a satellite product. Context or baseline, never proof of soiling.",
  SYNTHETIC: "Artificial values. Demonstration only.",
  UNKNOWN: "Origin not documented. Cannot support a decision.",
};

export const FACTOR_LABEL: Record<string, string> = {
  IRRADIANCE: "Irradiance",
  TEMPERATURE: "Temperature",
  DEGRADATION: "Degradation",
  DOWNTIME: "Downtime",
  EQUIPMENT_AVAILABILITY: "Equipment",
  CURTAILMENT: "Curtailment",
  SOILING: "Soiling (measured)",
};

export const FACTOR_STATUS_LABEL: Record<string, string> = {
  QUANTIFIED: "Quantified",
  PARTIALLY_QUANTIFIED: "Partly quantified",
  ACCOUNTED_IN_BASELINE: "Already in the baseline",
  NOT_QUANTIFIED: "Not quantified",
  NOT_APPLICABLE: "Not applicable",
};

export const SUPPORT_LABEL: Record<string, string> = {
  STRONG: "Strong support",
  MODERATE: "Moderate support",
  WEAK: "Weak support",
  NOT_SUPPORTED: "Not supported",
  NOT_EVALUABLE: "Cannot be evaluated",
};

export const SUPPORT_STYLE: Record<string, string> = {
  STRONG: "bg-ink-800 text-white border-ink-800",
  MODERATE: "bg-ink-200 text-ink-900 border-ink-300",
  WEAK: "bg-ink-50 text-ink-700 border-ink-300",
  NOT_SUPPORTED: "bg-white text-ink-500 border-ink-200",
  NOT_EVALUABLE: "bg-white text-ink-500 border-ink-300 border-dashed",
};

export const ROLE_LABEL: Record<string, string> = {
  ADMIN: "Administrator",
  ENGINEER: "Engineer",
  VIEWER: "Viewer",
  OWNER: "Owner",
  EDITOR: "Editor",
};

export function isDecision(value: string): value is Decision {
  return value === "CLEAN_NOW" || value === "INVESTIGATE" || value === "MONITOR";
}

export function isProvenance(value: string): value is Provenance {
  return value === "MEASURED" || value === "MODELLED" || value === "SYNTHETIC" || value === "UNKNOWN";
}

/** May this plant role change the plant's data? */
export function canEdit(role: string): boolean {
  return role === "OWNER" || role === "EDITOR";
}

FACTOR_LABEL.BASELINE_SOILING_ALLOWANCE = "Soiling allowance of the baseline";
