import { CheckCircle2, XCircle } from "lucide-react";
import type { ReactNode } from "react";

import type { ValidationReport } from "../api/types";
import { fmtDay, fmtInterval, fmtNumber, humanize } from "../lib/format";
import { metricLabel, unitLabel } from "../lib/labels";
import { ProvenanceBadge } from "./badges";
import { Badge, Table, Td, Th } from "./ui";
import { cx } from "../lib/cx";

const SEVERITY_STYLE: Record<string, string> = {
  BLOCKING: "border-rose-400 bg-rose-100 text-rose-900",
  ERROR: "border-rose-300 bg-rose-50 text-rose-900",
  WARNING: "border-amber-300 bg-amber-50 text-amber-900",
  INFO: "border-ink-200 bg-ink-50 text-ink-700",
};

const SEVERITY_ORDER = ["BLOCKING", "ERROR", "WARNING", "INFO"];

/**
 * What the server found in a file: accepted or not, what was read, the events it carries, and every issue with
 * examples and with what to do about it. `actions` holds the downloads (report, rejected rows).
 */
export function ValidationReportView({ report, actions }: { report: ValidationReport; actions?: ReactNode }) {
  const issues = [...report.issues].sort((a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity));
  // Reports stored before events could be read from a file carry no such list.
  const events = (report as Partial<ValidationReport>).events ?? [];
  return (
    <div className="overflow-hidden rounded-md border border-ink-200">
      <div className={cx("flex items-start gap-3 px-4 py-3", report.accepted ? "bg-teal-50 text-teal-950" : "bg-rose-50 text-rose-950")}>
        {report.accepted ? <CheckCircle2 className="mt-0.5 size-5 shrink-0" aria-hidden /> : <XCircle className="mt-0.5 size-5 shrink-0" aria-hidden />}
        <div className="min-w-0 text-sm">
          <p className="font-semibold">{report.accepted ? "The file can be imported" : "The file cannot be imported"}</p>
          <p className="mt-0.5 break-words">{report.summary}</p>
        </div>
        {actions && <div className="no-print ml-auto flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
      <dl className="grid grid-cols-2 gap-4 border-t border-ink-200 px-4 py-3 text-sm sm:grid-cols-4">
        <div><dt className="text-ink-500">Rows</dt><dd className="tabular font-medium">{fmtNumber(report.rows_plant)} plant · {fmtNumber(report.rows_device)} device</dd></div>
        <div><dt className="text-ink-500">Period</dt><dd className="font-medium">{report.first_local_day ? `${fmtDay(report.first_local_day)} – ${fmtDay(report.last_local_day)}` : "not established"}</dd></div>
        <div><dt className="text-ink-500">Interval</dt><dd className="font-medium">{report.interval_minutes === null ? "not established" : fmtInterval(report.interval_minutes)}{report.timezone ? ` · ${report.timezone}` : ""}</dd></div>
        <div><dt className="text-ink-500">Rejected</dt><dd className="tabular font-medium">{fmtNumber(report.rows_rejected)} rows · {fmtNumber(report.values_rejected)} values · {fmtNumber(report.missing_intervals)} missing intervals</dd></div>
      </dl>
      {report.channels.length > 0 && (
        <div className="border-t border-ink-200">
          <Table>
            <thead><tr><Th>Quantity</Th><Th>Column</Th><Th>Unit</Th><Th>Declared provenance</Th><Th numeric>Values</Th><Th numeric>Empty</Th><Th numeric>Rejected</Th><Th numeric>Range</Th></tr></thead>
            <tbody>
              {report.channels.map((channel) => (
                <tr key={channel.metric}>
                  <Td className="font-medium">{metricLabel(channel.metric)}</Td>
                  <Td className="font-mono text-xs">{channel.source_column}</Td>
                  <Td className="text-xs">
                    {channel.unit_in.toLowerCase() === channel.unit.toLowerCase()
                      ? unitLabel(channel.unit)
                      : `${unitLabel(channel.unit_in)}, converted to ${unitLabel(channel.unit)}`}
                  </Td>
                  <Td><ProvenanceBadge label={channel.provenance} /></Td>
                  <Td numeric>{fmtNumber(channel.values)}</Td>
                  <Td numeric>{fmtNumber(channel.missing)}</Td>
                  <Td numeric>{fmtNumber(channel.rejected)}</Td>
                  <Td numeric>{channel.minimum === null ? "—" : `${fmtNumber(channel.minimum, 2)} – ${fmtNumber(channel.maximum, 2)}`}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
      {events.length > 0 && (
        <div className="border-t border-ink-200">
          <p className="px-4 pt-3 text-sm font-medium text-ink-900">
            Events read from the file
            <span className="ml-2 font-normal text-ink-600">each becomes an evidence record of the dataset; none becomes a number</span>
          </p>
          <Table>
            <thead><tr><Th>Reference</Th><Th>Read as</Th><Th>When</Th><Th>Text in the file</Th><Th>Declared provenance</Th></tr></thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.reference}>
                  <Td className="font-mono text-xs">{event.reference}</Td>
                  <Td>
                    <span className="font-medium">{humanize(event.evidence_type)}</span>
                    {event.evidence_type === "OTHER" && <span className="block text-xs text-amber-800">not used by the diagnosis</span>}
                  </Td>
                  <Td className="whitespace-nowrap">
                    {event.first_day === event.last_day ? fmtDay(event.first_day) : `${fmtDay(event.first_day)} – ${fmtDay(event.last_day)}`}
                    {event.open_at_end && <span className="block text-xs text-amber-800">still marked on the last row: not closed</span>}
                  </Td>
                  <Td className="max-w-sm break-words">{event.text}{event.device_code ? ` (${event.device_code})` : ""}</Td>
                  <Td><ProvenanceBadge label={event.provenance} /></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
      {issues.length > 0 && (
        <ul className="divide-y divide-ink-100 border-t border-ink-200">
          {issues.map((issue) => (
            <li key={`${issue.code}-${issue.column ?? ""}-${issue.message}`} className="flex flex-wrap items-start gap-3 px-4 py-3 text-sm">
              <Badge className={SEVERITY_STYLE[issue.severity] ?? SEVERITY_STYLE.INFO}>{humanize(issue.severity)}</Badge>
              <div className="min-w-0 flex-1">
                <p className="break-words text-ink-800">{issue.message}</p>
                <p className="mt-0.5 font-mono text-xs text-ink-500">
                  {issue.code}{issue.column ? ` · ${issue.column}` : ""}{issue.count > 1 ? ` · ${fmtNumber(issue.count)} occurrences` : ""}
                </p>
                {issue.examples.length > 0 && (
                  <p className="mt-0.5 break-words font-mono text-xs text-ink-600">e.g. {issue.examples.slice(0, 5).join(" · ")}</p>
                )}
                {issue.hint && issue.severity !== "INFO" && (
                  <p className="mt-1 break-words text-ink-700"><span className="font-medium">What to do:</span> {issue.hint}</p>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="border-t border-ink-200 bg-ink-50 px-4 py-2 text-xs text-ink-600">
        An empty cell means “not observed”. It is never read as zero and never interpolated.
      </p>
    </div>
  );
}
