/**
 * Cleaning and economic assumptions typed into a form.
 *
 * Every field is text while it is edited. An empty field means "not supplied" and is sent as `null`: the engine then
 * reports the input as missing. An empty field is never turned into zero and nothing is pre-filled with a default.
 */
import type { AnalysisOptionsIn, CleaningAssumptionsIn, EconomicInputsIn } from "../api/types";
import { parseOptionalNumber } from "./format";

export const NUMERIC_FIELDS = [
  "cleaning_effectiveness_pct", "cleaning_effectiveness_low_pct", "cleaning_effectiveness_high_pct",
  "benefit_horizon_days", "benefit_horizon_days_low", "benefit_horizon_days_high",
  "projected_daily_clean_energy_kwh",
  "energy_value_per_kwh",
  "water_cost", "water_volume_m3", "water_price_per_m3",
  "labour_cost", "labour_hours", "labour_rate_per_hour",
  "equipment_cost", "operational_cost", "downtime_cost", "downtime_energy_kwh", "cost_uncertainty_pct",
] as const;

export const TEXT_FIELDS = [
  "source_note", "currency", "energy_value_basis", "energy_value_classification", "energy_value_source",
  "cost_classification", "cost_source",
] as const;

export type NumericField = (typeof NUMERIC_FIELDS)[number];
export type TextField = (typeof TEXT_FIELDS)[number];
export type AssumptionField = NumericField | TextField;
export type AssumptionFields = Record<AssumptionField, string>;
export type AssumptionErrors = Partial<Record<AssumptionField, string>>;

export function emptyAssumptions(): AssumptionFields {
  const fields = {} as AssumptionFields;
  for (const name of NUMERIC_FIELDS) fields[name] = "";
  for (const name of TEXT_FIELDS) fields[name] = "";
  fields.currency = "DZD";
  fields.energy_value_classification = "USER_ASSUMPTION";
  fields.cost_classification = "USER_ASSUMPTION";
  return fields;
}

function text(value: number | null | undefined, scale = 1): string {
  if (value === null || value === undefined) return "";
  // Avoid binary noise such as 0.9 * 100 = 90.00000000000001.
  return String(Number((value * scale).toPrecision(12)));
}

/** Fill the form from stored assumptions (a demonstration scenario, or the options of an earlier analysis). */
export function assumptionsFrom(
  cleaning: CleaningAssumptionsIn | null | undefined,
  economics: EconomicInputsIn | null | undefined,
): AssumptionFields {
  const fields = emptyAssumptions();
  if (cleaning) {
    fields.cleaning_effectiveness_pct = text(cleaning.cleaning_effectiveness, 100);
    fields.cleaning_effectiveness_low_pct = text(cleaning.cleaning_effectiveness_low, 100);
    fields.cleaning_effectiveness_high_pct = text(cleaning.cleaning_effectiveness_high, 100);
    fields.benefit_horizon_days = text(cleaning.benefit_horizon_days);
    fields.benefit_horizon_days_low = text(cleaning.benefit_horizon_days_low);
    fields.benefit_horizon_days_high = text(cleaning.benefit_horizon_days_high);
    fields.projected_daily_clean_energy_kwh = text(cleaning.projected_daily_clean_energy_kwh);
    fields.source_note = cleaning.source_note ?? "";
  }
  if (economics) {
    fields.currency = economics.currency ?? "DZD";
    fields.energy_value_per_kwh = text(economics.energy_value_per_kwh);
    fields.energy_value_basis = economics.energy_value_basis ?? "";
    fields.energy_value_classification = economics.energy_value_classification ?? "USER_ASSUMPTION";
    fields.energy_value_source = economics.energy_value_source ?? "";
    fields.water_cost = text(economics.water_cost);
    fields.water_volume_m3 = text(economics.water_volume_m3);
    fields.water_price_per_m3 = text(economics.water_price_per_m3);
    fields.labour_cost = text(economics.labour_cost);
    fields.labour_hours = text(economics.labour_hours);
    fields.labour_rate_per_hour = text(economics.labour_rate_per_hour);
    fields.equipment_cost = text(economics.equipment_cost);
    fields.operational_cost = text(economics.operational_cost);
    fields.downtime_cost = text(economics.downtime_cost);
    fields.downtime_energy_kwh = text(economics.downtime_energy_kwh);
    fields.cost_uncertainty_pct = text(economics.cost_uncertainty_pct);
    fields.cost_classification = economics.cost_classification ?? "USER_ASSUMPTION";
    fields.cost_source = economics.cost_source ?? "";
  }
  return fields;
}

interface Bounds {
  min?: number;
  /** The minimum itself is not allowed. */
  exclusiveMin?: boolean;
  max?: number;
}

const BOUNDS: Record<NumericField, Bounds> = {
  cleaning_effectiveness_pct: { min: 0, exclusiveMin: true, max: 100 },
  cleaning_effectiveness_low_pct: { min: 0, exclusiveMin: true, max: 100 },
  cleaning_effectiveness_high_pct: { min: 0, exclusiveMin: true, max: 100 },
  benefit_horizon_days: { min: 0, exclusiveMin: true, max: 366 },
  benefit_horizon_days_low: { min: 0, exclusiveMin: true, max: 366 },
  benefit_horizon_days_high: { min: 0, exclusiveMin: true, max: 366 },
  projected_daily_clean_energy_kwh: { min: 0, exclusiveMin: true },
  energy_value_per_kwh: { min: 0 },
  water_cost: { min: 0 }, water_volume_m3: { min: 0 }, water_price_per_m3: { min: 0 },
  labour_cost: { min: 0 }, labour_hours: { min: 0 }, labour_rate_per_hour: { min: 0 },
  equipment_cost: { min: 0 }, operational_cost: { min: 0 }, downtime_cost: { min: 0 }, downtime_energy_kwh: { min: 0 },
  cost_uncertainty_pct: { min: 0, max: 100 },
};

function check(value: number, bounds: Bounds): string | null {
  if (bounds.min !== undefined && (bounds.exclusiveMin ? value <= bounds.min : value < bounds.min)) {
    return bounds.exclusiveMin ? `Must be greater than ${bounds.min}.` : `Must not be below ${bounds.min}.`;
  }
  if (bounds.max !== undefined && value > bounds.max) return `Must not exceed ${bounds.max}.`;
  return null;
}

export interface ParsedAssumptions {
  cleaning: CleaningAssumptionsIn | null;
  economics: EconomicInputsIn | null;
  errors: AssumptionErrors;
}

export function parseAssumptions(fields: AssumptionFields): ParsedAssumptions {
  const errors: AssumptionErrors = {};
  const numbers = {} as Record<NumericField, number | null>;
  for (const name of NUMERIC_FIELDS) {
    const parsed = parseOptionalNumber(fields[name]);
    if (parsed === "invalid") {
      errors[name] = "Enter a number, or leave the field empty.";
      numbers[name] = null;
      continue;
    }
    numbers[name] = parsed;
    if (parsed !== null) {
      const problem = check(parsed, BOUNDS[name]);
      if (problem) errors[name] = problem;
    }
  }

  for (const [low, mid, high] of [
    ["cleaning_effectiveness_low_pct", "cleaning_effectiveness_pct", "cleaning_effectiveness_high_pct"],
    ["benefit_horizon_days_low", "benefit_horizon_days", "benefit_horizon_days_high"],
  ] as const) {
    const [l, m, h] = [numbers[low], numbers[mid], numbers[high]];
    if (m === null && (l !== null || h !== null)) errors[mid] ??= "A range needs a central value.";
    if (l !== null && m !== null && l > m) errors[low] ??= "The low value exceeds the central value.";
    if (h !== null && m !== null && h < m) errors[high] ??= "The high value is below the central value.";
  }

  const currency = fields.currency.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(currency)) errors.currency = "Three-letter currency code, for example DZD.";
  if (numbers.energy_value_per_kwh !== null && fields.energy_value_basis === "") {
    errors.energy_value_basis = "Say what the energy value represents.";
  }

  const fraction = (value: number | null) => (value === null ? null : value / 100);
  const note = (value: string) => (value.trim() === "" ? null : value.trim());

  const cleaningNumbers: NumericField[] = [
    "cleaning_effectiveness_pct", "cleaning_effectiveness_low_pct", "cleaning_effectiveness_high_pct",
    "benefit_horizon_days", "benefit_horizon_days_low", "benefit_horizon_days_high", "projected_daily_clean_energy_kwh",
  ];
  const anyCleaning = cleaningNumbers.some((name) => numbers[name] !== null) || fields.source_note.trim() !== "";
  const cleaning: CleaningAssumptionsIn | null = anyCleaning
    ? {
        cleaning_effectiveness: fraction(numbers.cleaning_effectiveness_pct),
        cleaning_effectiveness_low: fraction(numbers.cleaning_effectiveness_low_pct),
        cleaning_effectiveness_high: fraction(numbers.cleaning_effectiveness_high_pct),
        benefit_horizon_days: numbers.benefit_horizon_days,
        benefit_horizon_days_low: numbers.benefit_horizon_days_low,
        benefit_horizon_days_high: numbers.benefit_horizon_days_high,
        projected_daily_clean_energy_kwh: numbers.projected_daily_clean_energy_kwh,
        source_note: note(fields.source_note),
      }
    : null;

  const economicNumbers: NumericField[] = [
    "energy_value_per_kwh", "water_cost", "water_volume_m3", "water_price_per_m3", "labour_cost", "labour_hours",
    "labour_rate_per_hour", "equipment_cost", "operational_cost", "downtime_cost", "downtime_energy_kwh", "cost_uncertainty_pct",
  ];
  const anyEconomics = economicNumbers.some((name) => numbers[name] !== null) || fields.energy_value_basis !== "";
  const economics: EconomicInputsIn | null = anyEconomics
    ? {
        currency,
        energy_value_per_kwh: numbers.energy_value_per_kwh,
        energy_value_basis: (fields.energy_value_basis || null) as EconomicInputsIn["energy_value_basis"],
        energy_value_classification: fields.energy_value_classification as EconomicInputsIn["energy_value_classification"],
        energy_value_source: note(fields.energy_value_source),
        water_cost: numbers.water_cost,
        water_volume_m3: numbers.water_volume_m3,
        water_price_per_m3: numbers.water_price_per_m3,
        labour_cost: numbers.labour_cost,
        labour_hours: numbers.labour_hours,
        labour_rate_per_hour: numbers.labour_rate_per_hour,
        equipment_cost: numbers.equipment_cost,
        operational_cost: numbers.operational_cost,
        downtime_cost: numbers.downtime_cost,
        downtime_energy_kwh: numbers.downtime_energy_kwh,
        cost_uncertainty_pct: numbers.cost_uncertainty_pct,
        cost_classification: fields.cost_classification as EconomicInputsIn["cost_classification"],
        cost_source: note(fields.cost_source),
      }
    : null;

  return { cleaning, economics, errors };
}

export function toAnalysisOptions(parsed: ParsedAssumptions): AnalysisOptionsIn {
  return { cleaning: parsed.cleaning, economics: parsed.economics };
}

export function hasErrors(errors: AssumptionErrors): boolean {
  return Object.keys(errors).length > 0;
}
