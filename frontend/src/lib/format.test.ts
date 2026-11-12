import { describe, expect, it } from "vitest";

import {
  MISSING, fmtDay, fmtEnergy, fmtFraction, fmtInstant, fmtMoney, fmtNumber, fmtPct, fmtPeriod, fmtPower, humanize,
  parseOptionalNumber, plural,
} from "./format";

describe("a missing value", () => {
  it("is shown as missing by every formatter, never as zero", () => {
    for (const absent of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(fmtNumber(absent)).toBe(MISSING);
      expect(fmtPct(absent)).toBe(MISSING);
      expect(fmtFraction(absent)).toBe(MISSING);
      expect(fmtEnergy(absent)).toBe(MISSING);
      expect(fmtPower(absent)).toBe(MISSING);
      expect(fmtMoney(absent, "DZD")).toBe(MISSING);
    }
    expect(fmtDay(null)).toBe(MISSING);
    expect(fmtInstant(undefined)).toBe(MISSING);
    expect(humanize(null)).toBe(MISSING);
  });

  it("is told apart from a measured zero", () => {
    expect(fmtNumber(0)).toBe("0");
    expect(fmtEnergy(0)).toBe("0.0 kWh");
    expect(fmtPct(0)).toBe("0.0 %");
    expect(fmtMoney(0, "DZD")).toBe("0 DZD");
  });
});

describe("numbers", () => {
  it("are grouped and rounded, without a negative zero", () => {
    expect(fmtNumber(1234567.891, 1)).toBe("1,234,567.9");
    expect(fmtNumber(-0.004, 2)).toBe("0.00");
    expect(fmtNumber(-0.006, 2)).toBe("-0.01");
    expect(fmtFraction(0.0851)).toBe("8.5 %");
  });

  it("carry the unit that keeps them readable", () => {
    expect(fmtEnergy(950)).toBe("950 kWh");
    expect(fmtEnergy(12.34)).toBe("12.3 kWh");
    expect(fmtEnergy(3_784_300)).toBe("3.78 GWh");
    expect(fmtEnergy(-9_500)).toBe("-9.5 MWh");
    expect(fmtPower(300_000, true)).toBe("300 MWp");
    expect(fmtPower(2_500)).toBe("2.5 MW");
    expect(fmtPower(750)).toBe("750 kW");
    expect(fmtMoney(14_401_568.4, "DZD")).toBe("14,401,568 DZD");
    expect(plural(1, "row")).toBe("1 row");
    expect(plural(1200, "row")).toBe("1,200 rows");
  });
});

describe("dates", () => {
  it("show calendar days as written and instants in UTC", () => {
    expect(fmtDay("2026-06-29")).toBe("29 Jun 2026");
    expect(fmtPeriod("2026-05-01", "2026-06-29")).toBe("1 May 2026 – 29 Jun 2026");
    expect(fmtInstant("2026-07-01T23:30:00+01:00")).toBe("1 Jul 2026, 22:30 UTC");
    expect(fmtDay("not a date")).toBe("not a date");
  });
});

describe("text typed into a numeric field", () => {
  it("is null when empty - an empty field is not a zero", () => {
    expect(parseOptionalNumber("")).toBeNull();
    expect(parseOptionalNumber("   ")).toBeNull();
    expect(parseOptionalNumber("0")).toBe(0);
  });

  it("accepts a decimal comma and refuses what is not a number", () => {
    expect(parseOptionalNumber(" 12,5 ")).toBe(12.5);
    expect(parseOptionalNumber("-3.2")).toBe(-3.2);
    expect(parseOptionalNumber("12 kWh")).toBe("invalid");
    expect(parseOptionalNumber("abc")).toBe("invalid");
  });
});

it("turns a code into words", () => {
  expect(humanize("SINGLE_EXPLANATION")).toBe("Single explanation");
});
