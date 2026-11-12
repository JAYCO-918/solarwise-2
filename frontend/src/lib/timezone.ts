/** Offset of `timeZone` from UTC at the instant `utcMs`, in minutes (east positive). */
function offsetMinutes(utcMs: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(new Date(utcMs));
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return Math.round((asUtc - utcMs) / 60_000);
}

/**
 * A wall-clock time typed at the plant ("2026-06-27T10:00") as an ISO instant with the plant's UTC offset.
 * Evidence is dated in the plant's time zone, whatever the time zone of the person entering it.
 * Returns `null` when the text or the time zone is not usable.
 */
export function zonedIso(local: string, timeZone: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local);
  if (!match) return null;
  const [, year, month, day, hour, minute] = match.map(Number) as [number, number, number, number, number, number];
  const wall = Date.UTC(year, month - 1, day, hour, minute);
  let offset: number;
  try {
    offset = offsetMinutes(wall, timeZone);
    // Second pass: the offset that applies at the instant itself (matters around a clock change).
    offset = offsetMinutes(wall - offset * 60_000, timeZone);
  } catch {
    return null;
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  const magnitude = Math.abs(offset);
  return `${local}:00${offset >= 0 ? "+" : "-"}${pad(Math.floor(magnitude / 60))}:${pad(magnitude % 60)}`;
}
