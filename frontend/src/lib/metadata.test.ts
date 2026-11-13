import { describe, expect, it } from "vitest";

import { fixtures } from "../test/fixtures";
import { applySuggestion, buildMetadata, channelsFor, emptyMetadataForm, formFromPreview, readCsvHeader, readJsonColumns, unitOptions } from "./metadata";
import type { MetadataForm } from "./metadata";

const metrics = fixtures.referenceSchema().metrics;
const COLUMNS = ["timestamp", "actual_energy_kwh", "expected_energy_kwh", "soiling_ratio", "note"];

function form(change: (draft: MetadataForm) => void = () => {}): MetadataForm {
  const draft = emptyMetadataForm(metrics, COLUMNS, "june.csv");
  change(draft);
  return draft;
}

function channel(draft: MetadataForm, metric: string) {
  const row = draft.channels.find((c) => c.metric === metric);
  if (!row) throw new Error(`no row for ${metric}`);
  return row;
}

describe("the header of a file", () => {
  it("is read with the delimiter the file uses", () => {
    expect(readCsvHeader("timestamp,actual_energy_kwh\n2026-06-01,1\n")).toEqual(["timestamp", "actual_energy_kwh"]);
    expect(readCsvHeader("timestamp;actual_energy_kwh;note\r\n")).toEqual(["timestamp", "actual_energy_kwh", "note"]);
    expect(readCsvHeader("timestamp\tactual_energy_kwh")).toEqual(["timestamp", "actual_energy_kwh"]);
    expect(readCsvHeader('\uFEFF"time, local",energy')).toEqual(["time, local", "energy"]);
    expect(readCsvHeader("")).toEqual([]);
  });

  it("is read from JSON rows, and an embedded declaration is noticed", () => {
    const records = [{ timestamp: "2026-06-01", actual_energy_kwh: 1 }, { timestamp: "2026-06-02", soiling_ratio: 0.97 }];
    expect(readJsonColumns(JSON.stringify({ metadata: { name: "x" }, records })))
      .toEqual({ columns: ["timestamp", "actual_energy_kwh", "soiling_ratio"], embeddedMetadata: true });
    expect(readJsonColumns(JSON.stringify(records)))
      .toEqual({ columns: ["timestamp", "actual_energy_kwh", "soiling_ratio"], embeddedMetadata: false });
    expect(readJsonColumns(JSON.stringify({ metadata: { name: "x" } }))).toBeNull();
    expect(readJsonColumns("not json")).toBeNull();
  });
});

describe("the declaration form", () => {
  it("pre-selects columns by their canonical name only, and never a provenance", () => {
    const rows = channelsFor(metrics, COLUMNS);
    expect(channel({ channels: rows } as MetadataForm, "actual_energy").column).toBe("actual_energy_kwh");
    expect(channel({ channels: rows } as MetadataForm, "module_temp").column).toBe("");
    expect(new Set(rows.map((row) => row.provenance))).toEqual(new Set(["UNKNOWN"]));
    expect(rows.some((row) => row.metric === "device_energy")).toBe(false);
  });

  it("is valid as it stands, declaring every origin unknown", () => {
    const { metadata, errors } = buildMetadata(form());
    expect(errors).toEqual([]);
    expect(metadata).toMatchObject({ name: "june", timestamp_column: "timestamp", timezone: null, interval_minutes: null, baseline: null });
    expect(Object.keys(metadata?.channels ?? {}).sort()).toEqual(["actual_energy", "expected_energy", "soiling_ratio"]);
    expect(metadata?.channels?.actual_energy).toMatchObject({ provenance: "UNKNOWN", uncertainty_pct: null, boundary: null });
  });

  it("asks for the source behind a declared origin", () => {
    const { metadata, errors } = buildMetadata(form((draft) => { channel(draft, "actual_energy").provenance = "MEASURED"; }));
    expect(metadata).toBeNull();
    expect(errors).toEqual(["actual_energy: name the source (instrument, model or product) behind a MEASURED declaration."]);
  });

  it("cannot declare synthetic data: that takes a declaration file with a generator record", () => {
    const { metadata, errors } = buildMetadata(form((draft) => {
      const row = channel(draft, "actual_energy");
      row.provenance = "SYNTHETIC";
      row.source = "a generator";
    }));
    expect(metadata).toBeNull();
    expect(errors.join(" ")).toMatch(/synthetic data need a generator record/);
  });

  it("names what is missing", () => {
    const { errors } = buildMetadata(form((draft) => {
      draft.name = " ";
      draft.timestamp_column = "";
      channel(draft, "actual_energy").column = "";
      channel(draft, "expected_energy").column = "soiling_ratio";
      channel(draft, "soiling_ratio").uncertainty_pct = "150";
      draft.baseline.soiling_allowance_pct = "60";
    }));
    expect(errors).toEqual(expect.arrayContaining([
      "Give the dataset a name.",
      "Say which column holds the start of each interval.",
      "Assign the column that holds the actual energy.",
      "Column “soiling_ratio” is assigned to both expected_energy and soiling_ratio.",
      "soiling_ratio: the uncertainty must be a percentage between 0 and 100, or empty.",
      "The soiling allowance of the baseline must be a percentage below 50, or empty.",
    ]));
  });

  it("builds what the server expects from a complete declaration", () => {
    const { metadata, errors } = buildMetadata(form((draft) => {
      draft.interval = "1440";
      draft.timezone = "Africa/Algiers";
      Object.assign(channel(draft, "actual_energy"), { provenance: "MEASURED", source: " Revenue meter ", uncertainty_pct: "0,5", boundary: "GRID_METER" });
      Object.assign(channel(draft, "expected_energy"), { provenance: "MODELLED", source: "Performance model" });
      Object.assign(channel(draft, "soiling_ratio"), { provenance: "MEASURED", source: "Soiling station", soiling_method: "SOILING_STATION" });
      Object.assign(draft.baseline, { method: "TELEMETRY_MODEL", irradiance_adjusted: "true", temperature_adjusted: "false", soiling_allowance_pct: "2" });
    }));
    expect(errors).toEqual([]);
    expect(metadata).toMatchObject({ interval_minutes: 1440, timezone: "Africa/Algiers", device_column: "device_code" });
    expect(metadata?.channels?.actual_energy).toMatchObject({ column: "actual_energy_kwh", provenance: "MEASURED", source: "Revenue meter", uncertainty_pct: 0.5, boundary: "GRID_METER" });
    expect(metadata?.channels?.soiling_ratio).toMatchObject({ soiling_method: "SOILING_STATION" });
    expect(metadata?.baseline).toMatchObject({ method: "TELEMETRY_MODEL", irradiance_adjusted: true, temperature_adjusted: false, degradation_adjusted: null });
    expect(metadata?.baseline?.soiling_allowance_fraction).toBeCloseTo(0.02, 12);
  });
});

describe("a form filled in from the server's first look at a file", () => {
  const preview = () => fixtures.uploadPreview().preview;
  const proposed = () => formFromPreview(metrics, preview(), "may-2026-export.csv");

  it("takes the columns and the units the reader proposed, and no provenance", () => {
    const draft = proposed();
    expect(draft.name).toBe("may-2026-export");
    expect(draft.timestamp_column).toBe("Date");
    expect(draft.events).toEqual({ cleaning_column: "Cleaning", event_column: "Alarms", provenance: "UNKNOWN", source: "" });
    expect(channel(draft, "actual_energy")).toMatchObject({ column: "Energy (kWh)", unit: "kWh", origin: "DETECTED", certainty: "NAME" });
    expect(channel(draft, "poa_irradiation")).toMatchObject({ column: "Irradiance (W/m2)", unit: "w/m2", certainty: "AMBIGUOUS" });
    expect(channel(draft, "soiling_ratio")).toMatchObject({ column: "Soiling loss (%)", unit: "percent", reported_as: "LOSS" });
    expect(channel(draft, "ambient_temp")).toMatchObject({ column: "", origin: "" });
    expect(new Set(draft.channels.map((row) => row.provenance))).toEqual(new Set(["UNKNOWN"]));
    expect(draft.channels.filter((row) => row.column !== "").every((row) => row.reason.length > 0)).toBe(true);
  });

  it("is valid as proposed and says a loss is a loss; events are declared with the file", () => {
    const { metadata, errors } = buildMetadata(proposed());
    expect(errors).toEqual([]);
    expect(metadata?.channels?.soiling_ratio).toMatchObject({ column: "Soiling loss (%)", unit: "percent", reported_as: "LOSS", provenance: "UNKNOWN" });
    expect(metadata?.channels?.actual_energy).not.toHaveProperty("reported_as");
    expect(metadata?.events).toEqual({ cleaning_column: "Cleaning", event_column: "Alarms", provenance: "UNKNOWN", source: "" });
  });

  it("leaves the events out of the declaration when no column holds any", () => {
    const { metadata } = buildMetadata(form());
    expect(metadata).not.toHaveProperty("events");
    expect(metadata?.channels?.soiling_ratio).not.toHaveProperty("reported_as");
  });

  it("asks for the source of events that are declared measured, and keeps their columns apart", () => {
    const draft = proposed();
    draft.events.provenance = "MEASURED";
    expect(buildMetadata(draft).errors).toEqual(["Events: name the source (log, system or person) behind a MEASURED declaration."]);
    draft.events.source = "SCADA event log";
    expect(buildMetadata(draft).errors).toEqual([]);
    draft.events.event_column = "Cleaning";
    expect(buildMetadata(draft).errors).toContain("The cleaning marks and the alarms need two different columns.");
    draft.events.event_column = "Energy (kWh)";
    expect(buildMetadata(draft).errors).toContain("Column “Energy (kWh)” is assigned to both actual_energy and the alarms and events.");
  });

  it("offers irradiance as a unit of irradiation, and the canonical unit first", () => {
    const spec = (name: string) => metrics.find((m) => m.metric === name)!;
    const units = fixtures.referenceSchema().units;
    expect(unitOptions(spec("poa_irradiation"), units)).toEqual(expect.arrayContaining(["kWh/m2", "wh/m2", "w/m2", "kw/m2"]));
    expect(unitOptions(spec("poa_irradiation"), units)[0]).toBe("kWh/m2");
    expect(unitOptions(spec("actual_energy"), units)).not.toContain("w/m2");
    expect(unitOptions(spec("actual_energy"), units).filter((u) => u.toLowerCase() === "kwh")).toEqual(["kWh"]);
    // A server that predates the list falls back on the units of the dimension.
    expect(unitOptions({ ...spec("module_temp"), accepted_units: undefined }, units)).toEqual(["degC", "k", "degf"]);
  });
});

describe("a suggestion of the language model, once the uploader accepts it", () => {
  const suggestions = () => fixtures.dataReview().suggestions;
  const start = () => formFromPreview(metrics, fixtures.uploadPreview().preview, "may-2026-export.csv");

  it("assigns the column, says who proposed it, and declares nothing about its origin", () => {
    const [ambient] = suggestions();
    const next = applySuggestion(start(), ambient!);
    expect(channel(next, "ambient_temp")).toMatchObject({ column: "T2", unit: "degC", origin: "AI", provenance: "UNKNOWN", source: "" });
    expect(channel(next, "ambient_temp").reason).toBe(ambient!.reason);
    expect(channel(start(), "ambient_temp").column).toBe("");  // a suggestion that is not accepted changes nothing
  });

  it("moves a column from one quantity to another without leaving it in both", () => {
    const horizontal = suggestions().find((s) => s.metric === "ghi")!;
    const next = applySuggestion(start(), horizontal);
    expect(channel(next, "ghi")).toMatchObject({ column: "Irradiance (W/m2)", unit: "w/m2", origin: "AI" });
    expect(channel(next, "poa_irradiation")).toMatchObject({ column: "", origin: "" });
    expect(buildMetadata(next).errors).toEqual([]);
  });

  it("can give a column another role than a quantity", () => {
    const base = start();
    const next = applySuggestion(base, { column: "Alarms", role: "UNUSED", metric: null, unit: null, reported_as: null, reason: "Routine status text.", current: { role: "EVENTS", metric: null, unit: null } });
    expect(next.events.event_column).toBe("");
    const dated = applySuggestion(base, { column: "T2", role: "TIMESTAMP", metric: null, unit: null, reported_as: null, reason: "x", current: { role: "UNUSED", metric: null, unit: null } });
    expect(dated.timestamp_column).toBe("T2");
    expect(base.timestamp_column).toBe("Date");  // the form that was given is not modified
  });
});
