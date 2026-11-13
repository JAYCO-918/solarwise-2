import { Upload } from "lucide-react";
import { Link } from "react-router";

import { endpoints } from "../../api/endpoints";
import type { Dataset, Plant } from "../../api/types";
import { scenarioOf } from "../../api/types";
import { DecisionBadge } from "../../components/badges";
import { Badge, Card, CardHeader, EmptyState, ErrorNote, LinkButton, Loading, Table, Td, Th } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { fmtInstant, fmtInterval, fmtPct, fmtPeriod, humanize } from "../../lib/format";
import { canEdit } from "../../lib/labels";

function DatasetRow({ dataset }: { dataset: Dataset }) {
  const scenario = scenarioOf(dataset);
  const latest = dataset.latest_analysis;
  return (
    <tr>
      <Td>
        <Link to={`/datasets/${dataset.id}`} className="font-medium text-ink-950 underline underline-offset-2">
          {scenario ? `${String(scenario.number).padStart(2, "0")} · ${scenario.title}` : dataset.name}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {dataset.is_synthetic && <Badge className="border-violet-300 bg-violet-50 text-violet-900">Synthetic</Badge>}
          {dataset.kind !== "PRODUCTION" && <Badge className="border-sky-300 bg-sky-50 text-sky-900">{humanize(dataset.kind)}</Badge>}
        </div>
        {scenario && <p className="mt-1 max-w-xl text-sm text-ink-600">{scenario.story}</p>}
      </Td>
      <Td className="whitespace-nowrap">
        {fmtPeriod(dataset.period_start, dataset.period_end)}
        <span className="block text-xs text-ink-500">{fmtInterval(dataset.interval_minutes)} · {dataset.rows_plant} rows</span>
      </Td>
      <Td>
        {latest ? (
          <Link to={`/analyses/${latest.id}`} className="inline-flex flex-col gap-1">
            <DecisionBadge decision={latest.decision} simulated={latest.simulated} size="sm" />
            <span className="text-xs text-ink-500">rule {latest.rule} · {humanize(latest.diagnostic_status).toLowerCase()}</span>
          </Link>
        ) : (
          <span className="text-ink-500">not analysed</span>
        )}
      </Td>
      <Td numeric>{latest ? fmtPct(latest.window_gap_pct) : "—"}</Td>
    </tr>
  );
}

export function DatasetsTab({ plant }: { plant: Plant }) {
  const datasets = useAsync((signal) => endpoints.datasets(plant.id, signal), [plant.id]);
  const analyses = useAsync((signal) => endpoints.analyses(plant.id, signal), [plant.id]);
  const editable = canEdit(plant.role);

  return (
    <div className="space-y-6">
      <Card aria-labelledby="datasets-title">
        <CardHeader
          id="datasets-title"
          title="Datasets"
          description="A dataset is a file of operational data as it was uploaded, with what was declared about it. It is never modified afterwards."
        />
        {datasets.loading && <Loading label="Loading the datasets" />}
        {datasets.error && <div className="p-5"><ErrorNote error={datasets.error} onRetry={datasets.reload} /></div>}
        {datasets.data && datasets.data.length === 0 && (
          <EmptyState
            title="No operational data yet"
            action={editable ? <LinkButton to={`/plants/${plant.id}/upload`} variant="primary"><Upload className="size-4" aria-hidden /> Upload a CSV or JSON file</LinkButton> : undefined}
          >
            {editable
              ? "The plant is described. Now upload what it measured: a CSV or JSON export of its production, with the weather, soiling and events it holds. The columns are recognised from their headers."
              : "You have read-only access to this plant; an owner or editor can add data."}
          </EmptyState>
        )}
        {datasets.data && datasets.data.length > 0 && (
          <Table>
            <thead><tr><Th>Dataset</Th><Th>Period</Th><Th>Latest decision</Th><Th numeric>Gap, window</Th></tr></thead>
            <tbody>{datasets.data.map((dataset) => <DatasetRow key={dataset.id} dataset={dataset} />)}</tbody>
          </Table>
        )}
      </Card>

      <Card aria-labelledby="history-title">
        <CardHeader id="history-title" title="Analyses" description="Every analysis is kept exactly as it was issued, with the assumptions it was run with." />
        {analyses.loading && <Loading label="Loading the analyses" />}
        {analyses.error && <div className="p-5"><ErrorNote error={analyses.error} onRetry={analyses.reload} /></div>}
        {analyses.data && analyses.data.length === 0 && <EmptyState title="No analysis yet">Open a dataset to run one.</EmptyState>}
        {analyses.data && analyses.data.length > 0 && (
          <Table>
            <thead><tr><Th>Issued</Th><Th>Decision</Th><Th>Why</Th><Th numeric>Gap, window</Th><Th>Period</Th><Th /></tr></thead>
            <tbody>
              {analyses.data.map((analysis) => (
                <tr key={analysis.id}>
                  <Td className="whitespace-nowrap">{fmtInstant(analysis.created_at)}</Td>
                  <Td><DecisionBadge decision={analysis.decision} simulated={analysis.simulated} size="sm" /></Td>
                  <Td className="max-w-md">
                    {humanize(analysis.reason_code)}
                    <span className="block text-xs text-ink-500">rule {analysis.rule} · {humanize(analysis.diagnostic_status).toLowerCase()}</span>
                  </Td>
                  <Td numeric>{fmtPct(analysis.window_gap_pct)}</Td>
                  <Td className="whitespace-nowrap">{fmtPeriod(analysis.period_start, analysis.period_end)}</Td>
                  <Td><Link to={`/analyses/${analysis.id}`} className="font-medium underline underline-offset-2">Open<span className="sr-only"> analysis {analysis.id}</span></Link></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
