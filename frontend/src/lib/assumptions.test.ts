import { describe, expect, it } from "vitest";

import { assumptionsFrom, emptyAssumptions, hasErrors, parseAssumptions, toAnalysisOptions } from "./assumptions";

describe("assumptions typed into the form", () => {
  it("send nothing when nothing was typed: no default is invented", () => {
    const parsed = parseAssumptions(emptyAssumptions());
    expect(parsed.errors).toEqual({});
    expect(toAnalysisOptions(parsed)).toEqual({ cleaning: null, economics: null });
  });

  it("keep an empty field as null, not as zero", () => {
    const parsed = parseAssumptions({ ...emptyAssumptions(), cleaning_effectiveness_pct: "90", water_cost: "0", energy_value_per_kwh: "5", energy_value_basis: "INTERNAL_VALUATION" });
    expect(parsed.errors).toEqual({});
    expect(parsed.cleaning).toMatchObject({ cleaning_effectiveness: 0.9, benefit_horizon_days: null, cleaning_effectiveness_low: null });
    expect(parsed.economics).toMatchObject({ energy_value_per_kwh: 5, water_cost: 0, labour_cost: null, equipment_cost: null, currency: "DZD" });
  });

  it("converts percentages to fractions and back", () => {
    const fields = assumptionsFrom(
      { cleaning_effectiveness: 0.9, cleaning_effectiveness_low: 0.8, cleaning_effectiveness_high: 0.98, benefit_horizon_days: 30 },
      { currency: "DZD", energy_value_per_kwh: 5, energy_value_basis: "INTERNAL_VALUATION", energy_value_classification: "USER_ASSUMPTION", cost_classification: "USER_ASSUMPTION", water_cost: null },
    );
    expect(fields.cleaning_effectiveness_pct).toBe("90");
    expect(fields.cleaning_effectiveness_high_pct).toBe("98");
    expect(fields.water_cost).toBe("");
    const parsed = parseAssumptions(fields);
    expect(parsed.errors).toEqual({});
    expect(parsed.cleaning?.cleaning_effectiveness_low).toBeCloseTo(0.8, 12);
    expect(parsed.cleaning?.cleaning_effectiveness_high).toBeCloseTo(0.98, 12);
    expect(parsed.economics?.water_cost).toBeNull();
  });

  it("refuses what cannot be right, and says where", () => {
    const { errors } = parseAssumptions({
      ...emptyAssumptions(),
      cleaning_effectiveness_pct: "80", cleaning_effectiveness_low_pct: "90",
      benefit_horizon_days_high: "45",
      water_cost: "a lot",
      energy_value_per_kwh: "5",
      currency: "dinar",
    });
    expect(hasErrors(errors)).toBe(true);
    expect(errors.cleaning_effectiveness_low_pct).toMatch(/exceeds the central value/);
    expect(errors.benefit_horizon_days).toMatch(/central value/);
    expect(errors.water_cost).toMatch(/Enter a number/);
    expect(errors.energy_value_basis).toMatch(/what the energy value represents/);
    expect(errors.currency).toMatch(/Three-letter/);
  });
});
