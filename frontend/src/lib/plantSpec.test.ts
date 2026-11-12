import { describe, expect, it } from "vitest";

import { fixtures } from "../test/fixtures";
import { emptySpecValues, parseSpec, specValuesFrom } from "./plantSpec";

const REQUIRED = { name: "Test plant", capacity_dc_kwp: "1000", latitude: "33.49", longitude: "6.8" };

describe("the description of a plant", () => {
  it("has no default for what only the operator knows", () => {
    const { spec, errors } = parseSpec(emptySpecValues(), {});
    expect(spec).toBeNull();
    expect(Object.keys(errors).sort()).toEqual(["capacity_dc_kwp", "latitude", "longitude", "name"]);
  });

  it("leaves optional parameters empty instead of assuming a typical value", () => {
    const { spec, errors } = parseSpec({ ...emptySpecValues(), ...REQUIRED }, { capacity_dc_kwp: " nameplate ", tilt_deg: "  " });
    expect(errors).toEqual({});
    expect(spec).toMatchObject({ name: "Test plant", capacity_dc_kwp: 1000, timezone: "Africa/Algiers", tilt_deg: null, system_loss_fraction: null, module_temp_coeff_per_c: null, commissioning_date: null });
    expect(spec?.parameter_notes).toEqual({ capacity_dc_kwp: "nameplate" });
  });

  it("stores percentages as fractions", () => {
    const { spec } = parseSpec({ ...emptySpecValues(), ...REQUIRED, system_loss_fraction: "14", module_temp_coeff_per_c: "-0,35", annual_degradation_rate: "0.5" }, {});
    expect(spec?.system_loss_fraction).toBeCloseTo(0.14, 12);
    expect(spec?.module_temp_coeff_per_c).toBeCloseTo(-0.0035, 12);
    expect(spec?.annual_degradation_rate).toBeCloseTo(0.005, 12);
  });

  it("refuses values outside the physical range", () => {
    const { spec, errors } = parseSpec({ ...emptySpecValues(), ...REQUIRED, latitude: "95", tilt_deg: "-5", capacity_dc_kwp: "0", commissioning_date: "2019" }, {});
    expect(spec).toBeNull();
    expect(errors.latitude).toBe("Must be at least -90 and at most 90.");
    expect(errors.tilt_deg).toMatch(/at least 0/);
    expect(errors.capacity_dc_kwp).toMatch(/above 0/);
    expect(errors.commissioning_date).toMatch(/YYYY-MM-DD/);
  });

  it("shows a stored description back without rounding noise", () => {
    const stored = fixtures.plant().spec;
    const values = specValuesFrom(stored);
    expect(values.capacity_dc_kwp).toBe("300000");
    expect(values.name).toBe(stored.name);
    const { spec, errors } = parseSpec(values, stored.parameter_notes ?? {});
    expect(errors).toEqual({});
    expect(spec?.capacity_dc_kwp).toBe(stored.capacity_dc_kwp);
    expect(spec?.system_loss_fraction ?? null).toBe(stored.system_loss_fraction ?? null);
  });
});
