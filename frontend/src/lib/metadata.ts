/**
 * The declaration that accompanies an uploaded file: which column is which quantity, in which unit, and - above all -
 * where each quantity comes from. Nothing is assumed: a channel whose provenance is not declared is UNKNOWN.
 */
import type { ChannelDeclarationIn, DatasetMetadataIn, MetricSpec, Provenance } from "../api/types";
import { parseOptionalNumber } from "./format";

export interface ChannelRow {
  metric: string;
  /** Column of the file; empty = the quantity is not in the file. */
  column: string;
  unit: string;
  provenance: Provenance;
  source: string;
  method: string;
  uncertainty_pct: string;
  boundary: string;
  plane: string;
  soiling_method: string;
}

export interface BaselineFields {
  method: string;
  irradiance_adjusted: "" | "true" | "false";
  temperature_adjusted: "" | "true" | "false";
  degradation_adjusted: "" | "true" | "false";
  soiling_allowance_pct: string;
  description: string;
}

export interface MetadataForm {
  name: string;
  description: string;
  timezone: string;
  interval: "" | "15" | "30" | "60" | "1440";
  timestamp_column: string;
  device_column: string;
  channels: ChannelRow[];
  baseline: BaselineFields;
}

/** Column names of a delimited text file. The delimiter is detected like the server does: comma, semicolon or tab. */
export function readCsvHeader(text: string): string[] {
  const clean = text.replace(/^\uFEFF/, "");
  const line = clean.split(/\r?\n/, 1)[0] ?? "";
  const counts: [string, number][] = [",", ";", "\t"].map((d) => [d, line.split(d).length - 1]);
  const [delimiter, count] = counts.reduce((best, item) => (item[1] > best[1] ? item : best));
  if (count === 0) return line.trim() ? [line.trim()] : [];
  const cells: string[] = [];
  let current = "";
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (quoted) {
      if (char === '"' && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        current += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === delimiter) {
      cells.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  cells.push(current.trim());
  return cells;
}

/** Keys of the records of a JSON upload, and whether the file carries its own declaration. */
export function readJsonColumns(text: string): { columns: string[]; embeddedMetadata: boolean } | null {
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return null;
  }
  const isObject = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null && !Array.isArray(value);
  const records = Array.isArray(payload) ? payload : isObject(payload) ? payload.records : null;
  if (!Array.isArray(records)) return null;
  const columns: string[] = [];
  for (const record of records.slice(0, 200)) {
    if (!isObject(record)) continue;
    for (const key of Object.keys(record)) if (!columns.includes(key)) columns.push(key);
  }
  return { columns, embeddedMetadata: isObject(payload) && isObject(payload.metadata) };
}

export function emptyChannel(spec: MetricSpec, column = ""): ChannelRow {
  return {
    metric: spec.metric, column, unit: spec.unit, provenance: "UNKNOWN", source: "", method: "",
    uncertainty_pct: "", boundary: "", plane: "", soiling_method: "",
  };
}

/**
 * One row per quantity the server knows. A column is pre-selected only when the file uses the canonical column name -
 * that is a naming convention, not a guess about the data. Provenance always starts as UNKNOWN.
 */
export function channelsFor(metrics: MetricSpec[], columns: string[]): ChannelRow[] {
  // Device-level energy shares the column of the plant-level energy (rows are told apart by the device column),
  // so it is not declared separately.
  return metrics
    .filter((spec) => spec.metric !== "device_energy")
    .map((spec) => emptyChannel(spec, columns.includes(spec.column) ? spec.column : ""));
}

export function emptyMetadataForm(metrics: MetricSpec[], columns: string[], fileName: string): MetadataForm {
  return {
    name: fileName.replace(/\.[^.]+$/, ""),
    description: "",
    timezone: "",
    interval: "",
    timestamp_column: columns.includes("timestamp") ? "timestamp" : "",
    device_column: columns.includes("device_code") ? "device_code" : "",
    channels: channelsFor(metrics, columns),
    baseline: { method: "", irradiance_adjusted: "", temperature_adjusted: "", degradation_adjusted: "", soiling_allowance_pct: "", description: "" },
  };
}

export interface BuiltMetadata {
  metadata: DatasetMetadataIn | null;
  errors: string[];
}

const bool = (value: "" | "true" | "false") => (value === "" ? null : value === "true");

export function buildMetadata(form: MetadataForm): BuiltMetadata {
  const errors: string[] = [];
  if (form.name.trim() === "") errors.push("Give the dataset a name.");
  if (form.timestamp_column.trim() === "") errors.push("Say which column holds the start of each interval.");

  const channels: Record<string, ChannelDeclarationIn> = {};
  const used = new Map<string, string>();
  for (const row of form.channels) {
    if (row.column === "") continue;
    const other = used.get(row.column);
    if (other) errors.push(`Column “${row.column}” is assigned to both ${other} and ${row.metric}.`);
    used.set(row.column, row.metric);
    const uncertainty = parseOptionalNumber(row.uncertainty_pct);
    if (uncertainty === "invalid" || (uncertainty !== null && (uncertainty < 0 || uncertainty > 100))) {
      errors.push(`${row.metric}: the uncertainty must be a percentage between 0 and 100, or empty.`);
    }
    if (row.provenance !== "UNKNOWN" && row.source.trim() === "") {
      errors.push(`${row.metric}: name the source (instrument, model or product) behind a ${row.provenance} declaration.`);
    }
    if (row.provenance === "SYNTHETIC") {
      errors.push(`${row.metric}: synthetic data need a generator record; declare them with a declaration file.`);
    }
    channels[row.metric] = {
      column: row.column,
      unit: row.unit,
      provenance: row.provenance,
      source: row.source.trim(),
      method: row.method.trim() || null,
      uncertainty_pct: uncertainty === "invalid" ? null : uncertainty,
      boundary: (row.boundary || null) as ChannelDeclarationIn["boundary"],
      plane: (row.plane || null) as ChannelDeclarationIn["plane"],
      soiling_method: (row.soiling_method || null) as ChannelDeclarationIn["soiling_method"],
    };
  }
  if (!channels.actual_energy) errors.push("Assign the column that holds the actual energy.");

  const allowance = parseOptionalNumber(form.baseline.soiling_allowance_pct);
  if (allowance === "invalid" || (allowance !== null && (allowance < 0 || allowance >= 50))) {
    errors.push("The soiling allowance of the baseline must be a percentage below 50, or empty.");
  }
  const baseline: DatasetMetadataIn["baseline"] =
    channels.expected_energy && form.baseline.method !== ""
      ? {
          method: form.baseline.method as NonNullable<DatasetMetadataIn["baseline"]>["method"],
          irradiance_adjusted: bool(form.baseline.irradiance_adjusted),
          temperature_adjusted: bool(form.baseline.temperature_adjusted),
          degradation_adjusted: bool(form.baseline.degradation_adjusted),
          soiling_allowance_fraction: allowance === "invalid" || allowance === null ? null : allowance / 100,
          description: form.baseline.description.trim() || null,
        }
      : null;

  if (errors.length > 0) return { metadata: null, errors };
  const metadata: DatasetMetadataIn = {
    name: form.name.trim(),
    description: form.description.trim(),
    timezone: form.timezone.trim() || null,
    interval_minutes: form.interval === "" ? null : Number(form.interval),
    timestamp_column: form.timestamp_column.trim(),
    // The server's default name; when the file has no such column, every row is a plant-level row.
    device_column: form.device_column.trim() || "device_code",
    channels: channels as DatasetMetadataIn["channels"],
    baseline,
  };
  return { metadata, errors };
}
