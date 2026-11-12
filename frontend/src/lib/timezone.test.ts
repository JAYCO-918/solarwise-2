import { describe, expect, it } from "vitest";

import { zonedIso } from "./timezone";

describe("a time typed at the plant", () => {
  it("gets the UTC offset of the plant, not of the person typing", () => {
    expect(zonedIso("2026-06-27T10:00", "Africa/Algiers")).toBe("2026-06-27T10:00:00+01:00");
    expect(zonedIso("2026-01-15T08:30", "Africa/Algiers")).toBe("2026-01-15T08:30:00+01:00");
    expect(zonedIso("2026-06-27T10:00", "UTC")).toBe("2026-06-27T10:00:00+00:00");
    expect(zonedIso("2026-06-27T10:00", "Asia/Kolkata")).toBe("2026-06-27T10:00:00+05:30");
  });

  it("follows daylight saving time where there is one", () => {
    expect(zonedIso("2026-07-01T12:00", "America/New_York")).toBe("2026-07-01T12:00:00-04:00");
    expect(zonedIso("2026-01-01T12:00", "America/New_York")).toBe("2026-01-01T12:00:00-05:00");
    // The morning of a clock change: the offset is the one in force at that instant, not a few hours earlier.
    expect(zonedIso("2026-03-08T03:30", "America/New_York")).toBe("2026-03-08T03:30:00-04:00");
    expect(zonedIso("2026-03-08T01:30", "America/New_York")).toBe("2026-03-08T01:30:00-05:00");
  });

  it("is refused rather than guessed when the text or the zone is unusable", () => {
    expect(zonedIso("27/06/2026 10:00", "Africa/Algiers")).toBeNull();
    expect(zonedIso("2026-06-27", "Africa/Algiers")).toBeNull();
    expect(zonedIso("2026-06-27T10:00", "Not/AZone")).toBeNull();
  });
});
