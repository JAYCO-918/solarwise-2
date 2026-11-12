import { Play } from "lucide-react";
import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { endpoints } from "../api/endpoints";
import type { DatasetDetail, Plant } from "../api/types";
import { scenarioOf } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ValidationReportView } from "../components/ValidationReportView";
import { DecisionBadge, ProvenanceBadge, SimulatedTag } from "../components/badges";
import { Chart } from "../components/charts/Chart";
import { seriesOption } from "../components/charts/options";
import { AssumptionsForm } from "../components/forms/AssumptionsForm";
import { Badge, Button, Card, CardHeader, DefinitionList, ErrorNote, Field, Loading, Notice, PageHeader, Select, Table, Td, Th } from "../components/ui";
import { toApiError, useAsync } from "../hooks/useAsync";
import { assumptionsFrom, emptyAssumptions, hasErrors, parseAssumptions, toAnalysisOptions } from "../lib/assumptions";
import { focusFirstInvalid } from "../lib/forms";
import type { AssumptionErrors } from "../lib/assumptions";
import { fmtInstant, fmtInterval, fmtPct, fmtPeriod, humanize } from "../lib/format";
import { DECISION_LABEL, canEdit } from "../lib/labels";

function SeriesCard({ datasetId }: { datasetId: number }) {
  const series = useAsync((signal) => endpoints.series(datasetId, signal), [datasetId]);
  const option = useMemo(() => (series.data ? seriesOption(series.data) : null), [series.data]);
  const hasEnergy = series.data ? "actual_energy_kwh" in series.data.columns || "expected_energy_kwh" in series.data.columns : false;
  return (
    <Card aria-labelledby="series-title">
      <CardHeader id="series-title" title="Energy as imported" description="The stored values, in canonical units. Intervals without a value are left empty." />
      {series.loading && <Loading label="Loading the series" />}
      {series.error && <div className="p-5"><ErrorNote error={series.error} onRetry={series.reload} /></div>}
      {series.data && !hasEnergy && <p className="px-5 py-5 text-sm text-ink-600">This dataset holds no energy channel (it provides context for another dataset).</p>}
      {series.data && option && hasEnergy && (
        <div className="px-3 py-3">
          <Chart option={option} label="Actual and expected energy per interval, as imported" />
          {series.data.truncated && <p className="px-2 text-xs text-ink-500">Only the beginning of the series is drawn: the dataset is too long to display in full.</p>}
        </div>
      )}
    </Card>
  );
}

function RunCard({ dataset, plant }: { dataset: DatasetDetail; plant: Plant | null }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const scenario = scenarioOf(dataset);
  // Demonstration datasets come with the assumptions of their scenario. They are shown, never applied silently.
  const [fields, setFields] = useState(() => (scenario ? assumptionsFrom(scenario.cleaning, scenario.economics) : emptyAssumptions()));
  const [errors, setErrors] = useState<AssumptionErrors>({});
  const [weatherId, setWeatherId] = useState("");
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const siblings = useAsync((signal) => endpoints.datasets(dataset.plant_id, signal), [dataset.plant_id]);
  const weather = (siblings.data ?? []).filter((d) => d.kind === "WEATHER" && d.interval_minutes === dataset.interval_minutes);

  if (user?.role === "VIEWER") {
    return <Notice tone="neutral">Your account is read-only: it can open analyses but not run new ones.</Notice>;
  }
  if (dataset.kind !== "PRODUCTION") {
    return <Notice tone="neutral">This is a context dataset. Attach it to the analysis of a production dataset with the same interval.</Notice>;
  }

  async function run(event: FormEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLElement;
    const parsed = parseAssumptions(fields);
    setErrors(parsed.errors);
    if (hasErrors(parsed.errors)) {
      focusFirstInvalid(form);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const analysis = await endpoints.runAnalysis(dataset.id, toAnalysisOptions(parsed), weatherId === "" ? null : Number(weatherId));
      navigate(`/analyses/${analysis.id}`);
    } catch (cause) {
      setError(toApiError(cause));
      setBusy(false);
    }
  }

  const demonstration = dataset.is_synthetic || plant?.is_demonstration || user?.is_demo;
  return (
    <Card aria-labelledby="run-title">
      <CardHeader
        id="run-title"
        title="Run an analysis"
        description="The engine evaluates the dataset with the evidence records of the plant. The assumptions below are needed only to estimate what a cleaning would recover and whether it pays; all of them are optional."
      />
      <form onSubmit={run} noValidate>
        {scenario && (
          <div className="px-5 pt-5">
            <Notice tone="simulated" title="Assumptions of the demonstration scenario">
              The form is filled with the illustrative assumptions that ship with this scenario. They are not market
              prices, tariffs or contractual values. Change or clear them to see how the decision responds.
              <span className="mt-2 flex flex-wrap gap-2">
                <Button size="sm" onClick={() => setFields(assumptionsFrom(scenario.cleaning, scenario.economics))}>Restore the scenario's assumptions</Button>
                <Button size="sm" onClick={() => setFields(emptyAssumptions())}>Clear every assumption</Button>
              </span>
            </Notice>
          </div>
        )}
        <AssumptionsForm fields={fields} errors={errors} onChange={setFields} disabled={busy} />
        {weather.length > 0 && (
          <div className="border-t border-ink-100 px-5 py-5">
            <Field label="Weather context" optional hint="Modelled weather for the plant's location. It adds context (rain, temperature); it never counts as a measurement." className="max-w-md">
              {(props) => (
                <Select {...props} value={weatherId} onChange={(e) => setWeatherId(e.target.value)}>
                  <option value="">none</option>
                  {weather.map((d) => <option key={d.id} value={d.id}>{d.name} ({fmtPeriod(d.period_start, d.period_end)})</option>)}
                </Select>
              )}
            </Field>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-4 border-t border-ink-100 px-5 py-4">
          <Button type="submit" variant="primary" size="lg" busy={busy}><Play className="size-4" aria-hidden /> Run the analysis</Button>
          {demonstration && (
            <p className="flex items-center gap-2 text-sm text-ink-600"><SimulatedTag /> The result will be marked simulated.</p>
          )}
          {hasErrors(errors) && <p role="alert" className="text-sm font-medium text-rose-700">Some assumptions need attention.</p>}
        </div>
        {error && <div className="px-5 pb-5"><ErrorNote error={error} /></div>}
      </form>
    </Card>
  );
}

export default function DatasetPage() {
  const datasetId = Number(useParams().datasetId);
  const navigate = useNavigate();
  const dataset = useAsync((signal) => endpoints.dataset(datasetId, signal), [datasetId]);
  const plantId = dataset.data?.plant_id ?? null;
  const plant = useAsync((signal) => (plantId === null ? Promise.resolve(null) : endpoints.plant(plantId, signal)), [plantId]);
  const analyses = useAsync((signal) => (plantId === null ? Promise.resolve([]) : endpoints.analyses(plantId, signal)), [plantId]);
  const [error, setError] = useState<Error | null>(null);

  if (dataset.loading && !dataset.data) return <Loading label="Loading the dataset" />;
  if (dataset.error) return <ErrorNote error={dataset.error} onRetry={dataset.reload} />;
  if (!dataset.data) return null;
  const data = dataset.data;
  const scenario = scenarioOf(data);
  const own = (analyses.data ?? []).filter((a) => a.dataset_id === data.id);
  const editable = plant.data ? canEdit(plant.data.role) : false;

  async function archive() {
    if (!window.confirm(`Archive “${data.name}”? Its analyses are kept; the dataset disappears from the lists.`)) return;
    setError(null);
    try {
      await endpoints.archiveDataset(data.id);
      navigate(`/plants/${data.plant_id}`);
    } catch (cause) {
      setError(toApiError(cause));
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <>
            <Link to="/plants" className="underline underline-offset-2">Plants</Link> /{" "}
            <Link to={`/plants/${data.plant_id}`} className="underline underline-offset-2">{plant.data?.name ?? "Plant"}</Link>
          </>
        }
        title={<span className="inline-flex flex-wrap items-center gap-3">{scenario ? scenario.title : data.name}{data.is_synthetic && <Badge className="border-violet-300 bg-violet-50 text-sm text-violet-900">Synthetic dataset</Badge>}</span>}
        description={`${fmtPeriod(data.period_start, data.period_end)} · ${fmtInterval(data.interval_minutes)} values · ${data.rows_plant} plant rows${data.rows_device ? ` · ${data.rows_device} device rows` : ""}`}
        actions={editable && !data.is_synthetic ? <Button variant="danger" size="sm" onClick={archive}>Archive</Button> : undefined}
      />
      {error && <ErrorNote error={error} />}
      {data.disclaimer && <Notice tone="simulated" title="Statement attached to this dataset">{data.disclaimer}</Notice>}

      {scenario && (
        <Card aria-labelledby="scenario-title">
          <CardHeader id="scenario-title" title={`Demonstration scenario ${scenario.number}`} description={scenario.story} />
          <div className="grid gap-6 px-5 py-5 md:grid-cols-[2fr_1fr]">
            <div>
              <h3 className="text-sm font-semibold text-ink-900">What the generator put in the data</h3>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-700">
                {scenario.injected.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
            <div className="text-sm">
              <h3 className="font-semibold text-ink-900">What the engine is expected to conclude</h3>
              <p className="mt-2 text-ink-700">
                {DECISION_LABEL[scenario.expected_decision]} (rule {scenario.expected_rule}), {humanize(scenario.expected_diagnostic_status).toLowerCase()}.
              </p>
              <p className="mt-2 text-xs text-ink-500">Generator seed {scenario.seed}. The same seed always produces the same file.</p>
            </div>
          </div>
        </Card>
      )}

      <Card aria-labelledby="analyses-title">
        <CardHeader id="analyses-title" title="Analyses of this dataset" />
        {analyses.loading && <Loading label="Loading the analyses" />}
        {!analyses.loading && own.length === 0 && <p className="px-5 py-5 text-sm text-ink-600">Not analysed yet.</p>}
        {own.length > 0 && (
          <Table>
            <thead><tr><Th>Issued</Th><Th>Decision</Th><Th>Why</Th><Th numeric>Gap, window</Th><Th /></tr></thead>
            <tbody>
              {own.map((analysis) => (
                <tr key={analysis.id}>
                  <Td className="whitespace-nowrap">{fmtInstant(analysis.created_at)}</Td>
                  <Td><DecisionBadge decision={analysis.decision} simulated={analysis.simulated} size="sm" /></Td>
                  <Td>{humanize(analysis.reason_code)} <span className="text-xs text-ink-500">· rule {analysis.rule}</span></Td>
                  <Td numeric>{fmtPct(analysis.window_gap_pct)}</Td>
                  <Td><Link to={`/analyses/${analysis.id}`} className="font-medium underline underline-offset-2">Open<span className="sr-only"> analysis {analysis.id}</span></Link></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <RunCard key={data.id} dataset={data} plant={plant.data} />

      <SeriesCard datasetId={data.id} />

      <Card aria-labelledby="channels-title">
        <CardHeader id="channels-title" title="What was declared about each column" description="Provenance, unit and uncertainty are declared at import and cannot be changed afterwards." />
        <Table>
          <thead><tr><Th>Quantity</Th><Th>Column</Th><Th>Unit</Th><Th>Provenance</Th><Th>Source</Th><Th numeric>Uncertainty</Th></tr></thead>
          <tbody>
            {data.channels.map((channel) => (
              <tr key={channel.metric}>
                <Td>
                  <span className="font-medium">{humanize(channel.metric)}</span>
                  <span className="block text-xs text-ink-500">{channel.description}</span>
                </Td>
                <Td className="font-mono text-xs">{channel.column}</Td>
                <Td className="font-mono text-xs">{channel.original_unit && channel.original_unit !== channel.unit ? `${channel.original_unit}, converted to ${channel.unit}` : channel.unit}</Td>
                <Td><ProvenanceBadge label={channel.provenance_label} /></Td>
                <Td className="max-w-sm text-ink-700">
                  {channel.source || "not declared"}
                  {channel.method && <span className="block text-xs text-ink-500">{channel.method}</span>}
                  {[channel.boundary, channel.soiling_method].filter(Boolean).map((extra) => (
                    <span key={extra} className="block text-xs text-ink-500">{humanize(extra)}</span>
                  ))}
                </Td>
                <Td numeric>{channel.uncertainty_pct !== null ? fmtPct(channel.uncertainty_pct, 1) : channel.uncertainty_abs !== null ? `± ${channel.uncertainty_abs} ${channel.unit}` : "not declared"}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <div className="px-5 py-5">
          <DefinitionList
            items={[
              ["File", data.file_name ?? "not from a file"],
              ["Imported", fmtInstant(data.created_at)],
              ["Time zone", data.timezone],
              ["SHA-256 of the content", <span key="sha" className="break-all font-mono text-xs">{data.content_sha256}</span>],
              ["Baseline declared", data.baseline ? `${humanize(data.baseline.method)}${data.baseline.description ? ` - ${data.baseline.description}` : ""}` : "none"],
            ]}
          />
        </div>
      </Card>

      <Card aria-labelledby="validation-title">
        <CardHeader id="validation-title" title="Validation report at import" />
        <div className="p-5"><ValidationReportView report={data.validation_report} /></div>
      </Card>
    </div>
  );
}
