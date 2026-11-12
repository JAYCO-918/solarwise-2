/**
 * Formatting. One rule above all: a missing value is shown as missing. `null` never becomes "0".
 */

export const MISSING = "—";
export const MISSING_LABEL = "not available";

function isNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

const cache = new Map<string, Intl.NumberFormat>();

function formatter(minimum: number, maximum: number): Intl.NumberFormat {
  const key = `${minimum}:${maximum}`;
  let found = cache.get(key);
  if (!found) {
    found = new Intl.NumberFormat("en-GB", { minimumFractionDigits: minimum, maximumFractionDigits: maximum });
    cache.set(key, found);
  }
  return found;
}

export function fmtNumber(value: number | null | undefined, digits = 0): string {
  if (!isNumber(value)) return MISSING;
  // Avoid "-0".
  const rounded = Math.abs(value) < 0.5 * 10 ** -digits ? 0 : value;
  return formatter(digits, digits).format(rounded);
}

export function fmtPct(value: number | null | undefined, digits = 1): string {
  return isNumber(value) ? `${fmtNumber(value, digits)} %` : MISSING;
}

/** A fraction (0-1) shown as a percentage. */
export function fmtFraction(value: number | null | undefined, digits = 1): string {
  return isNumber(value) ? fmtPct(value * 100, digits) : MISSING;
}

export function fmtEnergy(kwh: number | null | undefined): string {
  if (!isNumber(kwh)) return MISSING;
  const magnitude = Math.abs(kwh);
  if (magnitude >= 1e6) return `${fmtNumber(kwh / 1e6, 2)} GWh`;
  if (magnitude >= 1e3) return `${fmtNumber(kwh / 1e3, 1)} MWh`;
  return `${fmtNumber(kwh, magnitude >= 100 ? 0 : 1)} kWh`;
}

export function fmtPower(kw: number | null | undefined, peak = false): string {
  if (!isNumber(kw)) return MISSING;
  const suffix = peak ? "p" : "";
  if (Math.abs(kw) >= 1000) return `${fmtNumber(kw / 1000, kw % 1000 === 0 ? 0 : 1)} MW${suffix}`;
  return `${fmtNumber(kw, 0)} kW${suffix}`;
}

export function fmtMoney(amount: number | null | undefined, currency: string | null | undefined): string {
  if (!isNumber(amount)) return MISSING;
  return `${fmtNumber(amount, 0)} ${currency ?? ""}`.trim();
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-06-29" -> "29 Jun 2026". Calendar days are shown as written: no time-zone arithmetic. */
export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return MISSING;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${Number(match[3])} ${month} ${match[1]}` : iso;
}

export function fmtDayShort(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${Number(match[3])} ${month}` : iso;
}

export function fmtPeriod(start: string, end: string): string {
  return `${fmtDay(start)} – ${fmtDay(end)}`;
}

/** An instant, shown in UTC so that everyone reads the same thing. */
export function fmtInstant(iso: string | null | undefined): string {
  if (!iso) return MISSING;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  const month = MONTHS[date.getUTCMonth()] ?? "";
  return `${date.getUTCDate()} ${month} ${date.getUTCFullYear()}, ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
}

export function fmtInterval(minutes: number): string {
  if (minutes === 1440) return "daily";
  if (minutes === 60) return "hourly";
  return `${minutes}-minute`;
}

/** "SINGLE_EXPLANATION" -> "Single explanation". */
export function humanize(value: string | null | undefined): string {
  if (!value) return MISSING;
  const text = value.replace(/_/g, " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${fmtNumber(count)} ${count === 1 ? singular : pluralForm}`;
}

/** Text typed into a form field -> number, or `null` when the field is empty. Never zero for "empty". */
export function parseOptionalNumber(text: string): number | null | "invalid" {
  const trimmed = text.trim().replace(",", ".");
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : "invalid";
}
