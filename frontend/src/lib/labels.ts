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

/** The quantities of a file, in the words of somebody who runs a plant. */
export const METRIC_LABEL: Record<string, string> = {
  actual_energy: "Energy produced",
  expected_energy: "Expected production",
  baseline_irradiation: "Irradiation assumed by the baseline",
  availability: "Availability",
  curtailed_energy: "Curtailed energy",
  soiling_ratio: "Soiling ratio",
  poa_irradiation: "In-plane irradiation",
  ghi: "Horizontal irradiation",
  ambient_temp: "Ambient temperature",
  module_temp: "Module temperature",
  wind_speed: "Wind speed",
  relative_humidity: "Relative humidity",
  precipitation: "Rainfall",
  device_energy: "Energy of a device",
};

export function metricLabel(metric: string): string {
  return METRIC_LABEL[metric] ?? metric.replace(/_/g, " ");
}

const UNIT_LABEL: Record<string, string> = {
  kwh: "kWh", mwh: "MWh", gwh: "GWh", wh: "Wh", j: "J", kj: "kJ", mj: "MJ",
  "kwh/m2": "kWh/m²", "wh/m2": "Wh/m²", "mj/m2": "MJ/m²", "j/m2": "J/m²", "w/m2": "W/m²", "kw/m2": "kW/m²",
  degc: "°C", degf: "°F", k: "K", percent: "%", fraction: "fraction (0 to 1)",
};

/** A unit as it is written on a data sheet; the symbol the server understands stays the value that is sent. */
export function unitLabel(unit: string | null | undefined): string {
  if (!unit) return "";
  return UNIT_LABEL[unit.toLowerCase()] ?? unit;
}

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
