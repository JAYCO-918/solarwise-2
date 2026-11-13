import { describe, expect, it } from "vitest";

import { fixtures } from "../test/fixtures";
import { METRIC_LABEL, metricLabel, unitLabel } from "./labels";

describe("names and units shown to an operator", () => {
  it("has a name for every quantity the server stores", () => {
    for (const spec of fixtures.referenceSchema().metrics) {
      expect(METRIC_LABEL[spec.metric], spec.metric).toBeTruthy();
    }
    expect(metricLabel("actual_energy")).toBe("Energy produced");
    expect(metricLabel("something_new")).toBe("something new");
  });

  it("writes units as on a data sheet and leaves unknown ones as they are", () => {
    expect(unitLabel("w/m2")).toBe("W/m²");
    expect(unitLabel("kWh/m2")).toBe("kWh/m²");
    expect(unitLabel("degC")).toBe("°C");
    expect(unitLabel("percent")).toBe("%");
    expect(unitLabel("m/s")).toBe("m/s");
    expect(unitLabel(null)).toBe("");
    // Every unit the server accepts for a quantity can be shown.
    for (const spec of fixtures.referenceSchema().metrics) {
      for (const unit of spec.accepted_units ?? []) expect(unitLabel(unit).length).toBeGreaterThan(0);
    }
  });
});
