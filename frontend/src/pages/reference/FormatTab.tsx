import { endpoints } from "../../api/endpoints";
import { ProvenanceBadge } from "../../components/badges";
import { Badge, Card, CardHeader, ErrorNote, Loading, Table, Td, Th } from "../../components/ui";
import { TemplateDownloads } from "../../components/upload/TemplateDownloads";
import { useAsync } from "../../hooks/useAsync";
import { fmtNumber, humanize } from "../../lib/format";

export function FormatTab() {
  const schema = useAsync((signal) => endpoints.referenceSchema(signal), []);
  if (schema.loading && !schema.data) return <Loading label="Loading the data format" />;
  if (schema.error) return <ErrorNote error={schema.error} onRetry={schema.reload} />;
  if (!schema.data) return null;
  const data = schema.data;
  return (
    <div className="space-y-6">
      <Card className="border-l-4 border-l-sun-500 px-5 py-4">
        <p className="text-base font-medium text-ink-950">{data.missing_values}</p>
        <p className="mt-1 text-sm text-ink-600">
          One row per interval (15, 30 or 60 minutes, or one day). At most {fmtNumber(data.limits.max_rows)} rows and{" "}
          {data.limits.max_columns} columns per file. A file is uploaded from the page of its plant.
        </p>
      </Card>

      {data.templates && data.templates.length > 0 && (
        <Card aria-labelledby="templates-title">
          <CardHeader
            id="templates-title"
            title="Templates and examples"
            description="CSV and JSON. The templates hold column names and no data. The examples hold invented values for a hypothetical plant: they show the format and describe no real installation."
          />
          <div className="px-5 py-4"><TemplateDownloads templates={data.templates} /></div>
        </Card>
      )}

      <Card aria-labelledby="provenance-title">
        <CardHeader id="provenance-title" title="Provenance" description="Declared for every column and every evidence record, and shown with every figure derived from it." />
        <ul className="divide-y divide-ink-100">
          {data.provenance.map((item) => (
            <li key={item.value} className="grid gap-2 px-5 py-3 sm:grid-cols-[11rem_minmax(0,1fr)] sm:items-start">
              <div><ProvenanceBadge label={item.value} /></div>
              <p className="text-sm text-ink-700">{item.meaning}</p>
            </li>
          ))}
        </ul>
      </Card>

      <Card aria-labelledby="columns-title">
        <CardHeader id="columns-title" title="Quantities" description="Canonical column names and units. A file may use other column names and any accepted unit: columns are recognised from their headers at upload, and the declaration says which is which. Irradiance in W/m² is accepted for irradiation: it is read as the mean over each interval and converted with the length of the interval." />
        <Table>
          <thead><tr><Th>Quantity</Th><Th>Canonical column</Th><Th>Unit</Th><Th>Accepted units</Th><Th numeric>Plausible range</Th></tr></thead>
          <tbody>
            {data.metrics.map((metric) => (
              <tr key={metric.metric}>
                <Td className="max-w-md">
                  <span className="font-medium">{humanize(metric.metric)}</span>
                  <span className="block text-xs text-ink-600">{metric.description}</span>
                </Td>
                <Td className="font-mono text-xs">{metric.column}</Td>
                <Td className="font-mono text-xs">{metric.unit}</Td>
                <Td className="font-mono text-xs">{(metric.accepted_units ?? data.units[metric.dimension]?.accepted ?? []).join(", ")}</Td>
                <Td numeric>
                  {metric.minimum === null ? "—" : fmtNumber(metric.minimum)} to {metric.maximum === null ? "no upper limit" : fmtNumber(metric.maximum, 2)}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Card aria-labelledby="soiling-title">
        <CardHeader id="soiling-title" title="Soiling measurement methods" description="Only a direct method can make soiling credible. Indirect estimates are recorded and shown, and they can raise a question, but they never justify a cleaning by themselves." />
        <ul className="flex flex-wrap gap-2 px-5 py-4">
          {data.soiling_methods.map((method) => (
            <li key={method.value}>
              <Badge className={method.direct ? "border-teal-300 bg-teal-50 text-teal-900" : "border-ink-300 bg-ink-50 text-ink-700"}>
                {humanize(method.value)} · {method.direct ? "direct" : "indirect"}
              </Badge>
            </li>
          ))}
        </ul>
      </Card>

      {data.events && (
        <Card aria-labelledby="events-title">
          <CardHeader id="events-title" title="Event columns" description={data.events.principle} />
          <dl className="grid gap-x-8 gap-y-4 px-5 py-5 text-sm sm:grid-cols-2">
            <div>
              <dt className="font-semibold text-ink-900">A cleaning column marks a cleaning with</dt>
              <dd className="mt-1 font-mono text-xs leading-relaxed text-ink-700">{data.events.cleaning_marks.join(" · ")}</dd>
            </div>
            <div>
              <dt className="font-semibold text-ink-900">In an alarm column, these cells mean that nothing happened</dt>
              {/* "null" and "nan" are accepted too: they are what an export writes for an empty cell, and are not listed. */}
              <dd className="mt-1 font-mono text-xs leading-relaxed text-ink-700">
                empty · {data.events.no_event_cells.filter((cell) => !["null", "nan"].includes(cell)).join(" · ")}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="font-semibold text-ink-900">How the text of an alarm is read (first match)</dt>
              <dd className="mt-1">
                <ul className="space-y-1">
                  {data.events.vocabulary.map((entry) => (
                    <li key={entry.evidence_type}>
                      <span className="font-medium">{humanize(entry.evidence_type)}</span>{" "}
                      <span className="font-mono text-xs text-ink-600">{entry.matches}</span>
                    </li>
                  ))}
                  <li><span className="font-medium">Anything else</span> <span className="text-ink-600">{data.events.unmatched}</span></li>
                </ul>
              </dd>
            </div>
          </dl>
        </Card>
      )}

      <Card aria-labelledby="vocab-title">
        <CardHeader id="vocab-title" title="Vocabularies" />
        <dl className="grid gap-x-8 gap-y-4 px-5 py-5 text-sm sm:grid-cols-2">
          {([
            ["Evidence types", data.evidence_types],
            ["Inspection findings", data.inspection_findings],
            ["Baseline methods", data.baseline_methods],
            ["Metering points", data.metering_boundaries],
            ["Irradiance planes", data.irradiance_planes],
            ["Mounting", data.tracking_types],
            ["What an energy value can represent", data.energy_value_bases],
            ["Classification of an economic input", data.value_classifications],
          ] as [string, string[]][]).map(([title, values]) => (
            <div key={title}>
              <dt className="font-semibold text-ink-900">{title}</dt>
              <dd className="mt-1 font-mono text-xs leading-relaxed text-ink-700">{values.join(" · ")}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}
