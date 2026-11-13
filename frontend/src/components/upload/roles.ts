import { metricLabel, unitLabel } from "../../lib/labels";
import type { MetadataForm } from "../../lib/metadata";

/** What a column of the file is used for, as the form stands now. */
export interface ColumnUse {
  kind: "TIMESTAMP" | "DEVICE" | "QUANTITY" | "CLEANING" | "EVENTS" | "UNUSED";
  label: string;
  /** Unit the values are declared in (quantities only). */
  unit?: string;
}

export const USE_STYLE: Record<ColumnUse["kind"], string> = {
  TIMESTAMP: "border-sky-300 bg-sky-50 text-sky-900",
  DEVICE: "border-sky-300 bg-sky-50 text-sky-900",
  QUANTITY: "border-teal-300 bg-teal-50 text-teal-900",
  CLEANING: "border-amber-300 bg-amber-50 text-amber-900",
  EVENTS: "border-amber-300 bg-amber-50 text-amber-900",
  UNUSED: "border-ink-200 bg-ink-50 text-ink-600",
};

export function columnUse(form: MetadataForm | null, column: string): ColumnUse {
  if (!form) return { kind: "UNUSED", label: "Not used" };
  if (form.timestamp_column === column) return { kind: "TIMESTAMP", label: "Date and time" };
  if (form.device_column === column) return { kind: "DEVICE", label: "Device code" };
  if (form.events.cleaning_column === column) return { kind: "CLEANING", label: "Cleaning marks" };
  if (form.events.event_column === column) return { kind: "EVENTS", label: "Alarms and events" };
  const channel = form.channels.find((row) => row.column === column);
  if (channel) {
    const loss = channel.metric === "soiling_ratio" && channel.reported_as === "LOSS";
    return { kind: "QUANTITY", label: loss ? "Soiling loss" : metricLabel(channel.metric), unit: unitLabel(channel.unit) };
  }
  return { kind: "UNUSED", label: "Not used" };
}
