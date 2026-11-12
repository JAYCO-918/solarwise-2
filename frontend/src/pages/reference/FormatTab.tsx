import { endpoints } from "../../api/endpoints";
import { ProvenanceBadge } from "../../components/badges";
import { Badge, Card, CardHeader, ErrorNote, Loading, Table, Td, Th } from "../../components/ui";
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
          {data.limits.max_columns} columns per file. Templates are in <span className="font-mono text-xs">data/samples</span>.
        </p>
      </Card>

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
        <CardHeader id="columns-title" title="Quantities" description="Canonical column names and units. A file may use other column names and any accepted unit: the declaration says which is which." />
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
                <Td className="font-mono text-xs">{(data.units[metric.dimension]?.accepted ?? []).join(", ")}</Td>
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
