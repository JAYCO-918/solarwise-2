import { FileUp } from "lucide-react";
import { useMemo, useState } from "react";
import type { ChangeEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { endpoints } from "../api/endpoints";
import type { DatasetMetadataIn, MetricSpec, Provenance, ReferenceSchema, UploadCheck } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ValidationReportView } from "../components/ValidationReportView";
import { Button, Card, CardHeader, ErrorNote, Field, Loading, Notice, PageHeader, Select, TextInput, Textarea } from "../components/ui";
import { cx } from "../lib/cx";
import { toApiError, useAsync } from "../hooks/useAsync";
import { fmtNumber, humanize } from "../lib/format";
import { PROVENANCE_MEANING } from "../lib/labels";
import { buildMetadata, emptyMetadataForm, readCsvHeader, readJsonColumns } from "../lib/metadata";
import type { ChannelRow, MetadataForm } from "../lib/metadata";

type Mode = "form" | "file" | "embedded";
const PROVENANCES: Provenance[] = ["UNKNOWN", "MEASURED", "MODELLED"];

function readText(file: Blob): Promise<string> {
  return file.text();
}

function ChannelEditor({ row, spec, columns, schema, onChange }: {
  row: ChannelRow;
  spec: MetricSpec;
  columns: string[];
  schema: ReferenceSchema;
  onChange: (row: ChannelRow) => void;
}) {
  const set = <K extends keyof ChannelRow>(key: K, value: ChannelRow[K]) => onChange({ ...row, [key]: value });
  const units = schema.units[spec.dimension];
  const unitOptions = units ? Array.from(new Set([spec.unit, ...units.accepted])) : [spec.unit];
  const assigned = row.column !== "";
  const id = `channel-${row.metric}`;
  return (
    <div className={cx("px-4 py-4", assigned ? "bg-white" : "bg-ink-50/60")}>
      <div className="grid gap-4 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div>
          <p id={`${id}-title`} className="font-medium text-ink-950">{humanize(row.metric)}</p>
          <p className="mt-0.5 text-sm text-ink-600">{spec.description}</p>
        </div>
        <Field label="Column of the file">
          {(props) => (
            <Select {...props} aria-describedby={`${id}-title`} value={row.column} onChange={(e) => set("column", e.target.value)}>
              <option value="">not in the file</option>
              {columns.map((column) => <option key={column} value={column}>{column}</option>)}
            </Select>
          )}
        </Field>
      </div>
      {assigned && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Unit in the file">
            {(props) => (
              <Select {...props} value={row.unit} onChange={(e) => set("unit", e.target.value)}>
                {unitOptions.map((unit) => <option key={unit} value={unit}>{unit}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Provenance" hint={PROVENANCE_MEANING[row.provenance]}>
            {(props) => (
              <Select {...props} value={row.provenance} onChange={(e) => set("provenance", e.target.value as Provenance)}>
                {PROVENANCES.map((p) => <option key={p} value={p}>{p === "UNKNOWN" ? "Unknown - not documented" : humanize(p)}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Source" hint="Meter, sensor, model or product." optional={row.provenance === "UNKNOWN"}>
            {(props) => <TextInput {...props} maxLength={500} value={row.source} onChange={(e) => set("source", e.target.value)} />}
          </Field>
          <Field label="Uncertainty, % of value" optional hint="One sigma. Empty = not declared.">
            {(props) => <TextInput {...props} inputMode="decimal" placeholder="not declared" value={row.uncertainty_pct} onChange={(e) => set("uncertainty_pct", e.target.value)} />}
          </Field>
          {(row.metric === "actual_energy" || row.metric === "expected_energy") && (
            <Field label="Metering point" optional>
              {(props) => (
                <Select {...props} value={row.boundary} onChange={(e) => set("boundary", e.target.value)}>
                  <option value="">not declared</option>
                  {schema.metering_boundaries.map((b) => <option key={b} value={b}>{humanize(b)}</option>)}
                </Select>
              )}
            </Field>
          )}
          {row.metric === "soiling_ratio" && (
            <Field label="How it was obtained" hint="Only a direct method can make soiling credible.">
              {(props) => (
                <Select {...props} value={row.soiling_method} onChange={(e) => set("soiling_method", e.target.value)}>
                  <option value="">not declared</option>
                  {schema.soiling_methods.map((m) => <option key={m.value} value={m.value}>{humanize(m.value)}{m.direct ? "" : " (indirect)"}</option>)}
                </Select>
              )}
            </Field>
          )}
          <Field label="Method" optional className="sm:col-span-2">
            {(props) => <TextInput {...props} maxLength={500} value={row.method} onChange={(e) => set("method", e.target.value)} />}
          </Field>
        </div>
      )}
    </div>
  );
}

export default function UploadPage() {
  const plantId = Number(useParams().plantId);
  const navigate = useNavigate();
  const { meta, user } = useAuth();
  const plant = useAsync((signal) => endpoints.plant(plantId, signal), [plantId]);
  const schema = useAsync((signal) => endpoints.referenceSchema(signal), []);

  const [file, setFile] = useState<File | null>(null);
  const [columns, setColumns] = useState<string[]>([]);
  const [hasEmbedded, setHasEmbedded] = useState(false);
  const [mode, setMode] = useState<Mode>("form");
  const [form, setForm] = useState<MetadataForm | null>(null);
  const [declaration, setDeclaration] = useState<{ name: string; metadata: DatasetMetadataIn } | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [check, setCheck] = useState<UploadCheck | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState<"check" | "import" | null>(null);

  const limitMb = user?.is_demo && meta?.demo_limits ? meta.demo_limits.max_upload_mb : (meta?.max_upload_mb ?? null);
  const specs = useMemo(() => new Map((schema.data?.metrics ?? []).map((spec) => [spec.metric, spec])), [schema.data]);

  function invalidate() {
    setCheck(null);
    setError(null);
    setProblems([]);
  }

  async function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0] ?? null;
    invalidate();
    setFile(chosen);
    setDeclaration(null);
    if (!chosen || !schema.data) {
      setColumns([]);
      setForm(null);
      return;
    }
    if (limitMb !== null && chosen.size > limitMb * 1024 * 1024) {
      setError(new Error(`The file is larger than the ${limitMb} MB limit of this server.`));
    }
    const isJson = chosen.name.toLowerCase().endsWith(".json");
    let found: string[];
    let embedded = false;
    if (isJson) {
      const parsed = readJsonColumns(await readText(chosen));
      found = parsed?.columns ?? [];
      embedded = parsed?.embeddedMetadata ?? false;
    } else {
      // The header is enough to list the columns; the file itself is read by the server.
      found = readCsvHeader(await readText(chosen.slice(0, 64 * 1024)));
    }
    setColumns(found);
    setHasEmbedded(embedded);
    setMode(embedded ? "embedded" : "form");
    setForm(emptyMetadataForm(schema.data.metrics, found, chosen.name));
  }

  async function chooseDeclaration(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0] ?? null;
    invalidate();
    setDeclaration(null);
    if (!chosen) return;
    try {
      const parsed: unknown = JSON.parse(await readText(chosen));
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("not an object");
      setDeclaration({ name: chosen.name, metadata: parsed as DatasetMetadataIn });
    } catch {
      setProblems([`“${chosen.name}” is not a JSON object. A declaration file follows the template data/samples/daily_measured.template.metadata.json.`]);
    }
  }

  function currentMetadata(): { ok: true; metadata: DatasetMetadataIn | null } | { ok: false } {
    if (mode === "embedded") return { ok: true, metadata: null };
    if (mode === "file") {
      if (!declaration) {
        setProblems(["Choose the declaration file."]);
        return { ok: false };
      }
      return { ok: true, metadata: declaration.metadata };
    }
    if (!form) return { ok: false };
    const built = buildMetadata(form);
    setProblems(built.errors);
    return built.metadata ? { ok: true, metadata: built.metadata } : { ok: false };
  }

  async function run(kind: "check" | "import") {
    if (!file) return;
    const current = currentMetadata();
    if (!current.ok) return;
    setBusy(kind);
    setError(null);
    try {
      const result = kind === "check"
        ? await endpoints.validateUpload(plantId, file, current.metadata)
        : await endpoints.importUpload(plantId, file, current.metadata);
      if (kind === "import" && result.stored && result.dataset) {
        navigate(`/datasets/${result.dataset.id}`);
        return;
      }
      setCheck(result);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(null);
    }
  }

  if ((plant.loading && !plant.data) || (schema.loading && !schema.data)) return <Loading label="Preparing the import" />;
  if (plant.error) return <ErrorNote error={plant.error} onRetry={plant.reload} />;
  if (schema.error) return <ErrorNote error={schema.error} onRetry={schema.reload} />;
  if (!plant.data || !schema.data) return null;
  const reference = schema.data;
  const setFormField = <K extends keyof MetadataForm>(key: K, value: MetadataForm[K]) => {
    invalidate();
    setForm((current) => (current ? { ...current, [key]: value } : current));
  };
  const expectedAssigned = form?.channels.some((c) => c.metric === "expected_energy" && c.column !== "") ?? false;
  const assignedCount = form?.channels.filter((c) => c.column !== "").length ?? 0;
  const unassigned = form ? columns.filter((c) => c !== form.timestamp_column && c !== form.device_column && !form.channels.some((ch) => ch.column === c)) : [];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <>
            <Link to="/plants" className="underline underline-offset-2">Plants</Link> /{" "}
            <Link to={`/plants/${plantId}`} className="underline underline-offset-2">{plant.data.name}</Link>
          </>
        }
        title="Add a dataset"
        description="A dataset is a CSV or JSON file with one row per interval, and a declaration of what each column is and where it comes from. The file is checked before anything is stored."
      />

      <Card aria-labelledby="file-title">
        <CardHeader id="file-title" title="1. The file" description={reference.missing_values} />
        <div className="space-y-4 px-5 py-5">
          <Field label="CSV or JSON file" hint={`Comma, semicolon or tab separated; timestamps with a UTC offset, or local time of the plant.${limitMb !== null ? ` At most ${limitMb} MB and ${fmtNumber(reference.limits.max_rows)} rows.` : ""}`}>
            {(props) => (
              <input
                {...props}
                type="file"
                accept=".csv,.txt,.tsv,.json,text/csv,application/json"
                onChange={chooseFile}
                className="block w-full text-sm text-ink-800 file:mr-4 file:rounded-md file:border file:border-ink-300 file:bg-white file:px-3 file:py-2 file:text-sm file:font-medium file:text-ink-900 hover:file:bg-ink-50"
              />
            )}
          </Field>
          {file && (
            <p className="text-sm text-ink-700">
              <FileUp className="mr-1.5 inline size-4" aria-hidden />
              {file.name} · {fmtNumber(file.size / 1024, 0)} kB · {columns.length > 0 ? `${columns.length} columns found` : "no column could be read"}
            </p>
          )}
        </div>
      </Card>

      {file && form && (
        <Card aria-labelledby="declaration-title">
          <CardHeader
            id="declaration-title"
            title="2. The declaration"
            description="Nothing is assumed about the data. A column whose origin is not declared is treated as of unknown origin, and unknown-origin production data cannot support a cleaning decision."
          />
          <fieldset className="border-b border-ink-100 px-5 py-4">
            <legend className="sr-only">How to declare the data</legend>
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
              {([["form", "Fill in the declaration here"], ["file", "Use a declaration file (JSON)"], ...(hasEmbedded ? [["embedded", "Use the declaration inside the file"]] : [])] as [Mode, string][]).map(([value, label]) => (
                <label key={value} className="inline-flex items-center gap-2">
                  <input type="radio" name="declaration-mode" className="size-4 accent-ink-900" checked={mode === value} onChange={() => { invalidate(); setMode(value); }} />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>

          {mode === "embedded" && (
            <p className="px-5 py-5 text-sm text-ink-700">The file carries its own <code className="font-mono text-xs">metadata</code> block; it will be used as it stands.</p>
          )}

          {mode === "file" && (
            <div className="space-y-4 px-5 py-5">
              <Field label="Declaration file" hint="A JSON file following data/samples/daily_measured.template.metadata.json. It is sent exactly as it is.">
                {(props) => (
                  <input
                    {...props}
                    type="file"
                    accept=".json,application/json"
                    onChange={chooseDeclaration}
                    className="block w-full text-sm text-ink-800 file:mr-4 file:rounded-md file:border file:border-ink-300 file:bg-white file:px-3 file:py-2 file:text-sm file:font-medium file:text-ink-900 hover:file:bg-ink-50"
                  />
                )}
              </Field>
              {declaration && (
                <p className="text-sm text-ink-700">
                  {declaration.name}: {Object.keys(declaration.metadata.channels ?? {}).length} channels declared
                  {declaration.metadata.synthetic ? " · declared synthetic" : ""}.
                </p>
              )}
            </div>
          )}

          {mode === "form" && (
            <>
              <div className="grid gap-4 px-5 py-5 sm:grid-cols-2 lg:grid-cols-3">
                <Field label="Name of the dataset">
                  {(props) => <TextInput {...props} maxLength={200} value={form.name} onChange={(e) => setFormField("name", e.target.value)} />}
                </Field>
                <Field label="Column holding the start of each interval">
                  {(props) => (
                    <Select {...props} value={form.timestamp_column} onChange={(e) => setFormField("timestamp_column", e.target.value)}>
                      <option value="">choose a column</option>
                      {columns.map((column) => <option key={column} value={column}>{column}</option>)}
                    </Select>
                  )}
                </Field>
                <Field label="Interval" hint="Read from the timestamps when left to the server.">
                  {(props) => (
                    <Select {...props} value={form.interval} onChange={(e) => setFormField("interval", e.target.value as MetadataForm["interval"])}>
                      <option value="">determine from the timestamps</option>
                      <option value="1440">Daily</option>
                      <option value="60">Hourly</option>
                      <option value="30">30 minutes</option>
                      <option value="15">15 minutes</option>
                    </Select>
                  )}
                </Field>
                <Field label="Time zone of timestamps without an offset" optional hint={`Empty = the plant's time zone (${plant.data.spec.timezone}).`}>
                  {(props) => <TextInput {...props} maxLength={64} value={form.timezone} onChange={(e) => setFormField("timezone", e.target.value)} />}
                </Field>
                <Field label="Column holding the device code" optional hint="For files with one row per device and interval.">
                  {(props) => (
                    <Select {...props} value={form.device_column} onChange={(e) => setFormField("device_column", e.target.value)}>
                      <option value="">none</option>
                      {columns.map((column) => <option key={column} value={column}>{column}</option>)}
                    </Select>
                  )}
                </Field>
                <Field label="Description" optional className="sm:col-span-2 lg:col-span-3">
                  {(props) => <Textarea {...props} rows={2} maxLength={4000} value={form.description} onChange={(e) => setFormField("description", e.target.value)} />}
                </Field>
              </div>

              <div className="border-t border-ink-100">
                <div className="px-5 py-4">
                  <h3 className="text-sm font-semibold text-ink-900">Quantities ({assignedCount} assigned)</h3>
                  <p className="mt-1 max-w-3xl text-sm text-ink-600">
                    Columns named like the canonical columns are pre-selected. Provenance is never pre-selected: it is
                    yours to declare.
                  </p>
                  {unassigned.length > 0 && (
                    <p className="mt-2 text-sm text-ink-600">Columns not used: <span className="font-mono text-xs">{unassigned.join(", ")}</span>. They are ignored.</p>
                  )}
                </div>
                <div className="divide-y divide-ink-100 border-t border-ink-100">
                  {form.channels.map((row) => {
                    const spec = specs.get(row.metric);
                    if (!spec) return null;
                    return (
                      <ChannelEditor
                        key={row.metric}
                        row={row}
                        spec={spec}
                        columns={columns}
                        schema={reference}
                        onChange={(next) => setFormField("channels", form.channels.map((c) => (c.metric === next.metric ? next : c)))}
                      />
                    );
                  })}
                </div>
              </div>

              {expectedAssigned && (
                <div className="border-t border-ink-100 px-5 py-5">
                  <h3 className="text-sm font-semibold text-ink-900">What the expected energy accounts for</h3>
                  <p className="mt-1 max-w-3xl text-sm text-ink-600">
                    The engine removes from the gap only the effects the baseline does not already include. Left
                    undeclared, an effect is neither removed nor attributed: it stays in the unexplained part.
                  </p>
                  <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    <Field label="How the baseline was produced">
                      {(props) => (
                        <Select {...props} value={form.baseline.method} onChange={(e) => setFormField("baseline", { ...form.baseline, method: e.target.value })}>
                          <option value="">not declared</option>
                          {reference.baseline_methods.map((m) => <option key={m} value={m}>{humanize(m)}</option>)}
                        </Select>
                      )}
                    </Field>
                    {([
                      ["irradiance_adjusted", "Adjusted to the actual irradiation?"],
                      ["temperature_adjusted", "Adjusted to the actual temperature?"],
                      ["degradation_adjusted", "Includes module degradation?"],
                    ] as const).map(([key, label]) => (
                      <Field key={key} label={label}>
                        {(props) => (
                          <Select {...props} value={form.baseline[key]} onChange={(e) => setFormField("baseline", { ...form.baseline, [key]: e.target.value as "" | "true" | "false" })}>
                            <option value="">not declared</option>
                            <option value="true">Yes</option>
                            <option value="false">No</option>
                          </Select>
                        )}
                      </Field>
                    ))}
                    <Field label="Soiling already assumed by the baseline, %" optional hint="Empty = not declared.">
                      {(props) => <TextInput {...props} inputMode="decimal" placeholder="not declared" value={form.baseline.soiling_allowance_pct} onChange={(e) => setFormField("baseline", { ...form.baseline, soiling_allowance_pct: e.target.value })} />}
                    </Field>
                    <Field label="Description of the baseline" optional>
                      {(props) => <TextInput {...props} maxLength={1000} value={form.baseline.description} onChange={(e) => setFormField("baseline", { ...form.baseline, description: e.target.value })} />}
                    </Field>
                  </div>
                  {form.baseline.method === "" && (
                    <p className="mt-3 text-sm text-amber-800">Without a declared method the baseline counts as undocumented, and the analysis will ask for it before concluding.</p>
                  )}
                </div>
              )}
            </>
          )}
        </Card>
      )}

      {problems.length > 0 && (
        <Notice tone="danger" title="The declaration is incomplete">
          <ul className="list-disc space-y-0.5 pl-5">{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
        </Notice>
      )}
      {error && <ErrorNote error={error} />}

      {file && form && (
        <Card aria-labelledby="check-title">
          <CardHeader id="check-title" title="3. Check, then import" description="The check reads the whole file and stores nothing. Once imported, a dataset cannot be modified; a corrected file is imported as a new dataset." />
          <div className="space-y-4 px-5 py-5">
            <div className="flex flex-wrap gap-3">
              <Button variant={check?.accepted ? "secondary" : "primary"} busy={busy === "check"} disabled={busy !== null} onClick={() => void run("check")}>Check the file</Button>
              <Button variant={check?.accepted ? "primary" : "secondary"} busy={busy === "import"} disabled={busy !== null || !check?.accepted || check.duplicate_of !== null} onClick={() => void run("import")}>Import the dataset</Button>
            </div>
            {check && check.duplicate_of !== null && (
              <Notice tone="warning" title="Already imported">
                This file with this declaration is already stored for the plant.{" "}
                <Link to={`/datasets/${check.duplicate_of}`} className="font-medium underline">Open the existing dataset</Link>.
              </Notice>
            )}
            {check && <ValidationReportView report={check.report} />}
          </div>
        </Card>
      )}
    </div>
  );
}
