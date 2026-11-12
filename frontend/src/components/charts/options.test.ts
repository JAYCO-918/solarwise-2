import { describe, expect, it } from "vitest";

import { fixtures } from "../../test/fixtures";
import { bridgeSteps } from "./options";

describe("the bridge from expected to actual energy", () => {
  const scope = fixtures.cleanNow().result.attribution.window;

  it("starts at the expected energy and lands on the actual energy", () => {
    const steps = bridgeSteps(scope);
    expect(steps[0]).toMatchObject({ label: "Expected", kind: "total", to: scope.expected_kwh });
    expect(steps.at(-1)).toMatchObject({ label: "Actual", kind: "total", to: scope.actual_kwh });
    const beforeActual = steps.at(-2);
    expect(beforeActual?.kind).toBe("residual");
    // Expected - quantified factors - unexplained residual = actual: nothing is lost or invented on the way.
    expect(beforeActual?.to).toBeCloseTo(scope.actual_kwh ?? Number.NaN, 3);
  });

  it("chains every step to the previous one", () => {
    const steps = bridgeSteps(scope).filter((step) => step.kind !== "total");
    let level = scope.expected_kwh ?? Number.NaN;
    for (const step of steps) {
      expect(step.from).toBeCloseTo(level, 6);
      expect(step.to).toBeCloseTo(level - (step.delta ?? Number.NaN), 6);
      level = step.to;
    }
  });

  it("draws only what was quantified: an unquantified factor is not a zero-height bar", () => {
    const drawn = bridgeSteps(scope).filter((step) => step.kind === "factor").map((step) => step.label);
    const quantified = scope.contributions.filter((c) => c.energy.value !== null && ["QUANTIFIED", "PARTIALLY_QUANTIFIED"].includes(c.status));
    const notQuantified = scope.contributions.filter((c) => c.energy.value === null);
    expect(notQuantified.length).toBeGreaterThan(0);
    expect(drawn).toHaveLength(quantified.length);
    expect(drawn).toContain("Soiling (measured)");
    expect(drawn).not.toContain("Curtailment");
    expect(drawn).not.toContain("Irradiance");
  });

  it("does not draw a factor whose value is not a quantification", () => {
    const changed = fixtures.cleanNow().result.attribution.window;
    const soiling = changed.contributions.find((c) => c.factor === "SOILING");
    if (!soiling) throw new Error("the fixture has no soiling contribution");
    soiling.status = "NOT_QUANTIFIED";
    expect(bridgeSteps(changed).map((step) => step.label)).not.toContain("Soiling (measured)");
  });

  it("draws nothing when the totals are missing", () => {
    expect(bridgeSteps({ ...scope, expected_kwh: null })).toEqual([]);
    expect(bridgeSteps({ ...scope, actual_kwh: null })).toEqual([]);
  });

  it("leaves the residual out when it could not be computed", () => {
    const steps = bridgeSteps({ ...scope, residual_kwh: null });
    expect(steps.some((step) => step.kind === "residual")).toBe(false);
    expect(steps.at(-1)?.label).toBe("Actual");
  });
});
