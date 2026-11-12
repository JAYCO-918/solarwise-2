import { describe, expect, it } from "vitest";

import { fixtures } from "../test/fixtures";
import { buildMetadata, channelsFor, emptyMetadataForm, readCsvHeader, readJsonColumns } from "./metadata";
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
