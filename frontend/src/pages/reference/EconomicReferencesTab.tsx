import { endpoints } from "../../api/endpoints";
import { Badge, Card, CardHeader, ErrorNote, Loading, Notice } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { fmtNumber, humanize } from "../../lib/format";

const CLASS_STYLE: Record<string, string> = {
  OFFICIAL_REFERENCE: "border-sky-300 bg-sky-50 text-sky-900",
  TECHNICAL_REFERENCE: "border-teal-300 bg-teal-50 text-teal-900",
  DEMONSTRATION_VALUE: "border-violet-300 bg-violet-50 text-violet-900",
  USER_ASSUMPTION: "border-ink-300 bg-ink-50 text-ink-800",
};

export function EconomicReferencesTab() {
  const references = useAsync((signal) => endpoints.economicReferences(signal), []);
  if (references.loading && !references.data) return <Loading label="Loading the economic references" />;
  if (references.error) return <ErrorNote error={references.error} onRetry={references.reload} />;
  if (!references.data) return null;
  const groups = new Map<string, typeof references.data.entries>();
  for (const entry of references.data.entries) groups.set(entry.classification, [...(groups.get(entry.classification) ?? []), entry]);

  return (
    <div className="space-y-6">
      <Notice tone="info" title="No price is built into SolarWise DZ">{references.data.statement}</Notice>
      {[...groups.entries()].map(([classification, entries]) => (
        <Card key={classification} aria-labelledby={`refs-${classification}`}>
          <CardHeader
            id={`refs-${classification}`}
            title={humanize(classification)}
            description={
              classification === "OFFICIAL_REFERENCE"
                ? "Regulatory texts an input may be taken from. No amount is stored: read the text in force and enter the value that applies to your case, citing it as the source."
                : classification === "DEMONSTRATION_VALUE"
                  ? "Arbitrary figures used by the demonstration scenarios so that the calculation can be shown end to end. They are not prices, tariffs or quotations."
                  : undefined
            }
          />
          <ul className="divide-y divide-ink-100">
            {entries.map((entry) => (
              <li key={entry.key} className="px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <h3 className="font-medium text-ink-950">{entry.label}</h3>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className={CLASS_STYLE[entry.classification] ?? CLASS_STYLE.USER_ASSUMPTION}>{humanize(entry.category)}</Badge>
                    {entry.verification_status !== "NOT_APPLICABLE" && (
                      <Badge className="border-amber-300 bg-amber-50 text-amber-900">{humanize(entry.verification_status)}</Badge>
                    )}
                  </div>
                </div>
                <p className="tabular mt-2 text-sm">
                  <span className="text-ink-500">Amount: </span>
                  {entry.amount === null ? (
                    <span className="font-medium text-ink-800">none stored</span>
                  ) : (
                    <span className="font-medium text-ink-950">{fmtNumber(entry.amount, Number.isInteger(entry.amount) ? 0 : 2)} {entry.currency} {entry.unit}</span>
                  )}
                </p>
                <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[9rem_minmax(0,1fr)]">
                  <dt className="text-ink-500">Source</dt>
                  <dd className="text-ink-800">{entry.source_title}<span className="block text-xs text-ink-500">{entry.source_reference}</span></dd>
                  <dt className="text-ink-500">Applicability</dt>
                  <dd className="text-ink-800">{entry.applicability}</dd>
                  {entry.notes && (<><dt className="text-ink-500">Notes</dt><dd className="text-ink-800">{entry.notes}</dd></>)}
                </dl>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}
