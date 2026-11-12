/**
 * The engineering description of a plant, as typed into a form. An empty optional field is sent as `null`
 * ("not known"); the engine then leaves out what depends on it instead of assuming a typical value.
 */
import type { PlantSpec, PlantSpecIn } from "../api/types";
import { parseOptionalNumber } from "./format";

export interface SpecField {
  name: keyof PlantSpecIn & string;
  label: string;
  hint?: string;
  required?: boolean;
  /** Shown as a percentage, stored as a fraction. */
  percent?: boolean;
  min?: number;
  max?: number;
  exclusiveMin?: boolean;
  exclusiveMax?: boolean;
}

export const SPEC_NUMBERS: SpecField[] = [
  { name: "capacity_dc_kwp", label: "Installed DC capacity, kWp", required: true, min: 0, exclusiveMin: true },
  { name: "capacity_ac_kw", label: "AC rating, kW", hint: "Needed to recognise clipping and power limits.", min: 0, exclusiveMin: true },
  { name: "latitude", label: "Latitude, °", required: true, min: -90, max: 90, hint: "North positive." },
  { name: "longitude", label: "Longitude, °", required: true, min: -180, max: 180, hint: "East positive." },
  { name: "tilt_deg", label: "Tilt, °", min: 0, max: 90 },
  { name: "azimuth_deg", label: "Azimuth, °", min: 0, max: 360, exclusiveMax: true, hint: "0 = north, 90 = east, 180 = south." },
  { name: "module_temp_coeff_per_c", label: "Power temperature coefficient, % per °C", percent: true, min: -1, max: 0, exclusiveMin: true, exclusiveMax: true, hint: "Negative, from the module datasheet. For example -0.35." },
  { name: "noct_c", label: "Nominal operating cell temperature, °C", min: 30, max: 60 },
  { name: "system_loss_fraction", label: "System losses of a clean array, %", percent: true, min: 0, max: 60, exclusiveMax: true, hint: "Wiring, inverter, mismatch - everything except temperature and soiling." },
  { name: "module_area_m2", label: "Total module area, m²", min: 0, exclusiveMin: true },
  { name: "annual_degradation_rate", label: "Degradation, % per year", percent: true, min: 0, max: 5, exclusiveMax: true },
];

export type SpecValues = Record<string, string>;

export function emptySpecValues(): SpecValues {
  const values: SpecValues = { name: "", timezone: "Africa/Algiers", tracking: "FIXED", commissioning_date: "" };
  for (const field of SPEC_NUMBERS) values[field.name] = "";
  return values;
}

export function specValuesFrom(spec: PlantSpec): SpecValues {
  const values = emptySpecValues();
  values.name = spec.name;
  values.timezone = spec.timezone;
  values.tracking = spec.tracking;
  values.commissioning_date = spec.commissioning_date ?? "";
  for (const field of SPEC_NUMBERS) {
    const value = spec[field.name as keyof PlantSpec] as number | null;
    values[field.name] = value === null ? "" : String(Number((value * (field.percent ? 100 : 1)).toPrecision(12)));
  }
  return values;
}

export interface ParsedSpec {
  spec: PlantSpecIn | null;
  errors: Record<string, string>;
}

export function parseSpec(values: SpecValues, notes: Record<string, string>): ParsedSpec {
  const errors: Record<string, string> = {};
  const numbers: Record<string, number | null> = {};
  if ((values.name ?? "").trim() === "") errors.name = "Give the plant a name.";
  if ((values.timezone ?? "").trim() === "") errors.timezone = "Give the IANA time zone, for example Africa/Algiers.";

  for (const field of SPEC_NUMBERS) {
    const parsed = parseOptionalNumber(values[field.name] ?? "");
    if (parsed === "invalid") {
      errors[field.name] = "Enter a number.";
      continue;
    }
    if (parsed === null) {
      if (field.required) errors[field.name] = "Required: it has no default.";
      numbers[field.name] = null;
      continue;
    }
    const tooLow = field.min !== undefined && (field.exclusiveMin ? parsed <= field.min : parsed < field.min);
    const tooHigh = field.max !== undefined && (field.exclusiveMax ? parsed >= field.max : parsed > field.max);
    if (tooLow || tooHigh) {
      const low = field.min === undefined ? null : `${field.exclusiveMin ? "above" : "at least"} ${field.min}`;
      const high = field.max === undefined ? null : `${field.exclusiveMax ? "below" : "at most"} ${field.max}`;
      errors[field.name] = `Must be ${[low, high].filter(Boolean).join(" and ")}.`;
    }
    numbers[field.name] = field.percent ? parsed / 100 : parsed;
  }

  const commissioning = (values.commissioning_date ?? "").trim();
  if (commissioning !== "" && !/^\d{4}-\d{2}-\d{2}$/.test(commissioning)) errors.commissioning_date = "Use the form YYYY-MM-DD.";

  if (Object.keys(errors).length > 0) return { spec: null, errors };
  const cleanNotes: Record<string, string> = {};
  for (const [key, note] of Object.entries(notes)) if (note.trim() !== "") cleanNotes[key] = note.trim();
  const spec = {
    name: (values.name ?? "").trim(),
    timezone: (values.timezone ?? "").trim(),
    tracking: values.tracking as PlantSpecIn["tracking"],
    commissioning_date: commissioning === "" ? null : commissioning,
    parameter_notes: cleanNotes,
    ...numbers,
  } as PlantSpecIn;
  return { spec, errors };
}
