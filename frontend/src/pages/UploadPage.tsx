import { Download, FileUp, Play } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { saveBlob } from "../api/client";
import { endpoints } from "../api/endpoints";
import type {
  DataNote,
  DataSuggestion,
  DatasetMetadataIn,
  MetricSpec,
  Provenance,
  ReferenceSchema,
  UploadCheck,
  UploadPreviewOut,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ValidationReportView } from "../components/ValidationReportView";
import { SourceTag } from "../components/SourceTag";
import { Badge, Button, Card, CardHeader, ErrorNote, Field, Loading, Notice, PageHeader, Select, TextInput, Textarea } from "../components/ui";
import { AiReviewCard } from "../components/upload/AiReviewCard";
import { DataNotes } from "../components/upload/DataNotes";
import { PreviewTable } from "../components/upload/PreviewTable";
import { TemplateDownloads } from "../components/upload/TemplateDownloads";
import { cx } from "../lib/cx";
import { toApiError, useAsync } from "../hooks/useAsync";
import { fmtNumber, humanize } from "../lib/format";
import { PROVENANCE_MEANING, metricLabel, unitLabel } from "../lib/labels";
import { applySuggestion, buildMetadata, formFromPreview, unitOptions } from "../lib/metadata";
import type { ChannelRow, MetadataForm } from "../lib/metadata";

type Mode = "form" | "file" | "embedded";
type Busy = "check" | "import" | "analyse" | "rejected" | null;
const PROVENANCES: Provenance[] = ["UNKNOWN", "MEASURED", "MODELLED"];

/** What a file may hold. Only the first two are needed; everything else sharpens the diagnosis. */
const FIELDS: [string, string][] = [
  ["Date, or date and time", "needed"],
  ["Energy produced", "needed"],
  ["Expected or reference production", "optional"],
  ["Irradiance", "optional"],
  ["Module and ambient temperature", "optional"],
  ["Relative humidity, wind speed, rainfall", "optional"],
  ["Soiling ratio, or measured soiling loss", "optional"],
  ["Cleaning events", "optional"],
  ["Equipment alarms and operational events", "optional"],
];

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
  const options = unitOptions(spec, schema.units);
  const assigned = row.column !== "";
  const id = `channel-${row.metric}`;
  const irradiance = spec.dimension === "irradiation" && ["w/m2", "kw/m2"].includes(row.unit.toLowerCase());
  const toCheck = assigned && (row.certainty === "AMBIGUOUS" || row.unit_assumed);
  return (
    <div className={cx("px-4 py-4", assigned ? "bg-white" : "bg-ink-50/60")}>
      <div className="grid gap-4 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div>
          <p id={`${id}-title`} className="flex flex-wrap items-center gap-2 font-medium text-ink-950">
            {metricLabel(row.metric)}
            {assigned && row.origin === "DETECTED" && <Badge className="border-teal-300 bg-teal-50 text-teal-900">Read from the header</Badge>}
            {assigned && row.origin === "AI" && <SourceTag source="ai">Suggested by the AI assistant, accepted by you</SourceTag>}
            {toCheck && <Badge className="border-amber-300 bg-amber-50 text-amber-900">Check</Badge>}
          </p>
          <p className="mt-0.5 text-sm text-ink-600">{spec.description}</p>
          {assigned && row.reason && row.origin !== "" && (
            <p className="mt-1 text-xs text-ink-500">
              {row.origin === "AI" ? "The assistant's reason: " : "Why: "}{row.reason.replace(/[\s.]+$/, "")}
              {row.unit_assumed ? `; the header states no unit, ${unitLabel(row.unit)} is assumed` : ""}.
            </p>
          )}
        </div>
        <Field label="Column of the file">
          {(props) => (
            <Select
              {...props}
              aria-describedby={`${id}-title`}
              value={row.column}
              // A column chosen by hand is nobody's proposal any more.
              onChange={(e) => onChange({ ...row, column: e.target.value, origin: "", certainty: "", unit_assumed: false, reason: "" })}
            >
              <option value="">not in the file</option>
              {columns.map((column) => <option key={column} value={column}>{column}</option>)}
            </Select>
          )}
        </Field>
      </div>
      {assigned && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field
            label="Unit in the file"
            hint={irradiance ? "Read as the mean over each interval and converted to irradiation with the length of the interval." : undefined}
          >
            {(props) => (
              <Select {...props} value={row.unit} onChange={(e) => onChange({ ...row, unit: e.target.value, unit_assumed: false })}>
                {options.map((unit) => <option key={unit} value={unit}>{unitLabel(unit)}</option>)}
              </Select>
            )}
          </Field>
          {row.metric === "soiling_ratio" && (
            <Field label="What the column holds" hint="A loss is stored as the ratio the engine uses: ratio = 1 - loss.">
              {(props) => (
                <Select {...props} value={row.reported_as} onChange={(e) => set("reported_as", e.target.value as ChannelRow["reported_as"])}>
                  <option value="RATIO">Soiling ratio (1 = clean)</option>
                  <option value="LOSS">Soiling loss (0 = clean)</option>
                </Select>
              )}
            </Field>
          )}
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
  const [preview, setPreview] = useState<UploadPreviewOut | null>(null);
  const [reading, setReading] = useState(false);
  const [mode, setMode] = useState<Mode>("form");
  const [form, setForm] = useState<MetadataForm | null>(null);
  const [declaration, setDeclaration] = useState<{ name: string; metadata: DatasetMetadataIn } | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [check, setCheck] = useState<UploadCheck | null>(null);
  const [checkedWith, setCheckedWith] = useState<DatasetMetadataIn | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [accepted, setAccepted] = useState<string[]>([]);
  // Answers to a file that is no longer the chosen one are dropped.
  const chosen = useRef(0);

  const limitMb = user?.is_demo && meta?.demo_limits ? meta.demo_limits.max_upload_mb : (meta?.max_upload_mb ?? null);
  const specs = useMemo(() => new Map((schema.data?.metrics ?? []).map((spec) => [spec.metric, spec])), [schema.data]);
  const columns = useMemo(() => preview?.preview.columns.map((column) => column.name) ?? [], [preview]);

  function invalidate() {
    setCheck(null);
    setCheckedWith(null);
    setError(null);
    setProblems([]);
  }

  async function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0] ?? null;
    const turn = ++chosen.current;
    invalidate();
    setFile(picked);
    setDeclaration(null);
    setPreview(null);
    setForm(null);
    setAccepted([]);
    if (!picked || !schema.data) return;
    if (limitMb !== null && picked.size > limitMb * 1024 * 1024) {
      setError(new Error(`The file is larger than the ${limitMb} MB limit of this server.`));
      return;
    }
    setReading(true);
    try {
      // The server reads the file: the first rows, and what each column probably is. Nothing is stored.
      const read = await endpoints.previewUpload(plantId, picked);
      if (turn !== chosen.current) return;
      setPreview(read);
      setMode(read.preview.embedded_metadata ? "embedded" : "form");
      setForm(formFromPreview(schema.data.metrics, read.preview, picked.name));
    } catch (cause) {
      if (turn === chosen.current) setError(toApiError(cause));
    } finally {
      if (turn === chosen.current) setReading(false);
    }
  }

  async function chooseDeclaration(event: ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0] ?? null;
    invalidate();
    setDeclaration(null);
    if (!picked) return;
    try {
      const parsed: unknown = JSON.parse(await readText(picked));
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("not an object");
      setDeclaration({ name: picked.name, metadata: parsed as DatasetMetadataIn });
    } catch {
      setProblems([`“${picked.name}” is not a JSON object. A declaration file follows the template data/samples/daily_measured.template.metadata.json.`]);
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

  async function run(kind: "check" | "import" | "analyse") {
    if (!file) return;
    const current = currentMetadata();
    if (!current.ok) return;
    setBusy(kind);
    setError(null);
    try {
      if (kind === "check") {
        setCheck(await endpoints.validateUpload(plantId, file, current.metadata));
        setCheckedWith(current.metadata);
        return;
      }
      const result = await endpoints.importUpload(plantId, file, current.metadata);
      if (!result.stored || !result.dataset) {
        setCheck(result);
        return;
      }
      const datasetId = result.dataset.id;
      if (kind === "import" || result.dataset.kind !== "PRODUCTION") {
        navigate(`/datasets/${datasetId}`);
        return;
      }
      // The pipeline runs on what was just imported. Assumptions for the economics can be added afterwards.
      try {
        const analysis = await endpoints.runAnalysis(datasetId, {}, null);
        navigate(`/analyses/${analysis.id}`);
      } catch (cause) {
        // The dataset is stored whatever happens to the analysis: say why it did not run, on the dataset's page.
        navigate(`/datasets/${datasetId}`, { state: { analysisError: toApiError(cause).message } });
      }
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function saveRejectedRows() {
    if (!file) return;
    setBusy("rejected");
    setError(null);
    try {
      await endpoints.downloadRejectedRows(plantId, file, checkedWith);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(null);
    }
  }

  function saveValidationReport() {
    if (!check || !file) return;
    const document = { file_name: file.name, checked_at: new Date().toISOString(), ...check };
    const stem = file.name.replace(/\.[^.]+$/, "");
    saveBlob(new Blob([JSON.stringify(document, null, 2)], { type: "application/json" }), `validation-report-${stem}.json`);
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
  const setEvents = (change: Partial<MetadataForm["events"]>) => {
    if (form) setFormField("events", { ...form.events, ...change });
  };
  const expectedAssigned = form?.channels.some((c) => c.metric === "expected_energy" && c.column !== "") ?? false;
  const assignedCount = form?.channels.filter((c) => c.column !== "").length ?? 0;
  const eventsAssigned = form ? form.events.cleaning_column !== "" || form.events.event_column !== "" : false;
  const unassigned = form
    ? columns.filter((c) => c !== form.timestamp_column && c !== form.device_column && c !== form.events.cleaning_column
        && c !== form.events.event_column && !form.channels.some((ch) => ch.column === c))
    : [];

  const noteChannel = (note: DataNote) => form?.channels.find((row) => row.column !== "" && row.column === note.column);
  const canUseUnit = (note: DataNote) => {
    const row = noteChannel(note);
    return mode === "form" && row !== undefined && note.suggested_unit !== null && row.unit.toLowerCase() !== note.suggested_unit.toLowerCase();
  };
  const applyUnit = (note: DataNote) => {
    const row = noteChannel(note);
    if (!form || !row || note.suggested_unit === null) return;
    const spec = specs.get(row.metric);
    const unit = (spec ? unitOptions(spec, reference.units) : []).find((u) => u.toLowerCase() === note.suggested_unit?.toLowerCase()) ?? note.suggested_unit;
    setFormField("channels", form.channels.map((c) => (c.metric === row.metric ? { ...c, unit, unit_assumed: false } : c)));
  };
  const acceptSuggestion = (suggestion: DataSuggestion) => {
    if (!form) return;
    invalidate();
    setForm(applySuggestion(form, suggestion));
    setAccepted((current) => [...current, suggestion.column]);
  };

  const importable = check?.accepted === true && check.duplicate_of === null;
  const rejections = check?.report.rejections_total ?? 0;
  const production = form === null || mode !== "form" || form.channels.some((c) => c.metric === "actual_energy" && c.column !== "");

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <>
            <Link to="/plants" className="underline underline-offset-2">Plants</Link> /{" "}
            <Link to={`/plants/${plantId}`} className="underline underline-offset-2">{plant.data.name}</Link>
          </>
        }
        title="Upload operational data"
        description="A CSV or JSON file exported from the plant's monitoring system, with one row per day or per interval. The file is read and checked before anything is stored, and it is kept exactly as you send it."
      />

      <Card aria-labelledby="what-title">
        <CardHeader
          id="what-title"
          title="What to upload"
          description="The description of the plant (capacity, location, modules) is entered once on the plant's page. This page is for what the plant measured: its production, the weather, soiling, and what happened on site."
        />
        <div className="grid gap-6 px-5 py-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div>
            <h3 className="text-sm font-semibold text-ink-900">Columns the file may have</h3>
            <ul className="mt-2 space-y-1 text-sm text-ink-700">
              {FIELDS.map(([name, need]) => (
                <li key={name} className="flex items-baseline justify-between gap-3">
                  <span>{name}</span>
                  <span className={cx("shrink-0 text-xs", need === "needed" ? "font-semibold text-ink-900" : "text-ink-500")}>{need}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-ink-600">
              Your own column names and units are fine: the columns are recognised from their headers and you correct
              what was not. A missing column limits what can be concluded; it never stops the import.
            </p>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-ink-900">Templates and examples</h3>
            <p className="mb-2 mt-1 text-xs text-ink-600">
              The templates hold column names and no data. The examples hold invented values for a hypothetical plant:
              they show the format and describe no real installation.
            </p>
            <TemplateDownloads templates={reference.templates ?? []} />
          </div>
        </div>
      </Card>

      <Card aria-labelledby="file-title">
        <CardHeader id="file-title" title="1. The file" description={reference.missing_values} />
        <div className="space-y-4 px-5 py-5">
          <Field label="CSV or JSON file" hint={`Comma, semicolon or tab separated; timestamps with a UTC offset, or local time of the plant.${limitMb !== null ? ` At most ${limitMb} MB and ${fmtNumber(reference.limits.max_rows)} rows.` : ""}`}>
            {(props) => (
              <input
                {...props}
                type="file"
                accept=".csv,.txt,.tsv,.json,text/csv,application/json"
                onChange={(event) => void chooseFile(event)}
                className="block w-full text-sm text-ink-800 file:mr-4 file:rounded-md file:border file:border-ink-300 file:bg-white file:px-3 file:py-2 file:text-sm file:font-medium file:text-ink-900 hover:file:bg-ink-50"
              />
            )}
          </Field>
          {reading && <Loading label="Reading the file" />}
          {file && preview && (
            <p className="text-sm text-ink-700">
              <FileUp className="mr-1.5 inline size-4" aria-hidden />
              {file.name} · {fmtNumber(file.size / 1024, 0)} kB · {preview.preview.file_format} · {fmtNumber(preview.preview.rows_total)} rows · {columns.length} columns
            </p>
          )}
          {preview && preview.same_file_as.length > 0 && (
            <Notice tone="warning" title="This very file was already imported for this plant">
              {preview.same_file_as.map((id, index) => (
                <span key={id}>
                  {index > 0 && ", "}
                  <Link to={`/datasets/${id}`} className="font-medium underline">dataset {id}</Link>
                </span>
              ))}
              . Importing it again is possible with another declaration - for instance to correct what a column was
              said to be. With the same declaration it is refused.
            </Notice>
          )}
          {error && !preview && <ErrorNote error={error} />}
        </div>
      </Card>

      {file && preview && form && (
        <Card aria-labelledby="preview-title">
          <CardHeader
            id="preview-title"
            title="2. What the file contains"
            description="The first rows as they are in the file. Under each header: what the column is used for, as the mapping of step 3 stands."
          />
          <PreviewTable preview={preview.preview} form={mode === "form" ? form : null} />
          <DataNotes notes={preview.preview.notes} canUseUnit={canUseUnit} onUseUnit={applyUnit} />
        </Card>
      )}

      {file && preview && form && (
        <Card aria-labelledby="declaration-title">
          <CardHeader
            id="declaration-title"
            title="3. What each column is"
            description="Which column is which quantity, in which unit - and where it comes from. The columns were recognised from their headers; where a value comes from is yours to declare. Until you do, it counts as unknown and cannot support a decision."
          />
          <fieldset className="border-b border-ink-100 px-5 py-4">
            <legend className="sr-only">How the declaration is given</legend>
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
              {preview.preview.embedded_metadata && (
                <label className="flex items-center gap-2">
                  <input type="radio" name="declaration-mode" checked={mode === "embedded"} onChange={() => { invalidate(); setMode("embedded"); }} />
                  Use the declaration inside the file
                </label>
              )}
              <label className="flex items-center gap-2">
                <input type="radio" name="declaration-mode" checked={mode === "form"} onChange={() => { invalidate(); setMode("form"); }} />
                Map the columns here
              </label>
              <label className="flex items-center gap-2">
                <input type="radio" name="declaration-mode" checked={mode === "file"} onChange={() => { invalidate(); setMode("file"); }} />
                Use a declaration file (JSON)
              </label>
            </div>
          </fieldset>

          {mode === "embedded" && (
            <p className="px-5 py-5 text-sm text-ink-700">
              The file carries its own declaration (<span className="font-mono text-xs">metadata</span>). It is used as it is; the check below shows what it declares.
            </p>
          )}

          {mode === "file" && (
            <div className="space-y-4 px-5 py-5">
              <Field label="Declaration file" hint="A JSON file following data/samples/daily_measured.template.metadata.json. It is sent exactly as it is.">
                {(props) => (
                  <input
                    {...props}
                    type="file"
                    accept=".json,application/json"
                    onChange={(event) => void chooseDeclaration(event)}
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
                <Field label="Column holding the start of each interval" hint="The date, or the date and time, of each row.">
                  {(props) => (
                    <Select {...props} value={form.timestamp_column} onChange={(e) => setFormField("timestamp_column", e.target.value)}>
                      <option value="">choose a column</option>
                      {columns.map((column) => <option key={column} value={column}>{column}</option>)}
                    </Select>
                  )}
                </Field>
                <Field
                  label="Interval"
                  hint={preview.preview.proposal.interval_minutes !== null
                    ? `The rows of the file are ${preview.preview.proposal.interval_minutes === 1440 ? "one day" : `${preview.preview.proposal.interval_minutes} minutes`} apart.`
                    : "Read from the timestamps when left to the server."}
                >
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

              <AiReviewCard key={preview.file_sha256} plantId={plantId} file={file} enabled={meta?.ai.enabled ?? false} applied={accepted} onApply={acceptSuggestion} />

              <div className="border-t border-ink-100">
                <div className="px-5 py-4">
                  <h3 className="text-sm font-semibold text-ink-900">Quantities ({assignedCount} assigned)</h3>
                  <p className="mt-1 max-w-3xl text-sm text-ink-600">
                    Columns are pre-selected from their headers; change any that is wrong. Provenance is never
                    pre-selected: it is yours to declare.
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

              <div className="border-t border-ink-100 px-5 py-5">
                <h3 className="text-sm font-semibold text-ink-900">Events</h3>
                <p className="mt-1 max-w-3xl text-sm text-ink-600">
                  Columns that hold what happened rather than a quantity. Each cleaning mark and each alarm becomes an
                  evidence record of the dataset. An alarm is a reason to investigate, never a reason to clean.
                </p>
                <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <Field label="Column with cleaning marks" optional hint="A cell with 1, yes or x marks a cleaning in that interval.">
                    {(props) => (
                      <Select {...props} value={form.events.cleaning_column} onChange={(e) => setEvents({ cleaning_column: e.target.value })}>
                        <option value="">none</option>
                        {columns.map((column) => <option key={column} value={column}>{column}</option>)}
                      </Select>
                    )}
                  </Field>
                  <Field label="Column with alarms or events" optional hint="Text or codes; empty when nothing happened.">
                    {(props) => (
                      <Select {...props} value={form.events.event_column} onChange={(e) => setEvents({ event_column: e.target.value })}>
                        <option value="">none</option>
                        {columns.map((column) => <option key={column} value={column}>{column}</option>)}
                      </Select>
                    )}
                  </Field>
                  {eventsAssigned && (
                    <>
                      <Field label="Provenance of the events" hint={PROVENANCE_MEANING[form.events.provenance]}>
                        {(props) => (
                          <Select {...props} value={form.events.provenance} onChange={(e) => setEvents({ provenance: e.target.value as Provenance })}>
                            {PROVENANCES.map((p) => <option key={p} value={p}>{p === "UNKNOWN" ? "Unknown - not documented" : humanize(p)}</option>)}
                          </Select>
                        )}
                      </Field>
                      <Field label="Source of the events" hint="Event log, system or person." optional={form.events.provenance === "UNKNOWN"}>
                        {(props) => <TextInput {...props} maxLength={500} value={form.events.source} onChange={(e) => setEvents({ source: e.target.value })} />}
                      </Field>
                    </>
                  )}
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
      {error && preview && <ErrorNote error={error} />}

      {file && preview && form && (
        <Card aria-labelledby="check-title">
          <CardHeader id="check-title" title="4. Check, then import" description="The check reads the whole file and stores nothing. Once imported, a dataset cannot be modified; a corrected file is imported as a new dataset." />
          <div className="space-y-4 px-5 py-5">
            <div className="flex flex-wrap gap-3">
              <Button variant={importable ? "secondary" : "primary"} busy={busy === "check"} disabled={busy !== null} onClick={() => void run("check")}>Check the file</Button>
            </div>
            {check && check.duplicate_of !== null && (
              <Notice tone="warning" title="Already imported">
                This file with this declaration is already stored for the plant.{" "}
                <Link to={`/datasets/${check.duplicate_of}`} className="font-medium underline">Open the existing dataset</Link>.
              </Notice>
            )}
            {check && check.duplicate_of === null && check.overlapping.length > 0 && (
              <Notice tone="warning" title="Another dataset of this plant covers some of the same days">
                {check.overlapping.map((other, index) => (
                  <span key={other.dataset_id}>
                    {index > 0 && "; "}
                    <Link to={`/datasets/${other.dataset_id}`} className="font-medium underline">{other.name}</Link> ({other.period_start} to {other.period_end})
                  </span>
                ))}
                . Each dataset is analysed on its own, so nothing is counted twice - but check that a second dataset for
                these days is what you want.
              </Notice>
            )}
            {check && (
              <ValidationReportView
                report={check.report}
                actions={
                  <>
                    <Button size="sm" onClick={saveValidationReport}><Download className="size-4" aria-hidden /> Validation report (JSON)</Button>
                    <Button size="sm" busy={busy === "rejected"} disabled={busy !== null || rejections === 0} onClick={() => void saveRejectedRows()}>
                      <Download className="size-4" aria-hidden /> Rejected rows (CSV){rejections > 0 ? ` · ${fmtNumber(rejections)}` : ""}
                    </Button>
                  </>
                }
              />
            )}
            {check && (
              <div className="flex flex-wrap items-center gap-3 border-t border-ink-100 pt-4">
                {production && (
                  <Button variant={importable ? "primary" : "secondary"} size="lg" busy={busy === "analyse"} disabled={busy !== null || !importable} onClick={() => void run("analyse")}>
                    <Play className="size-4" aria-hidden /> Import and run the analysis
                  </Button>
                )}
                <Button variant={importable && !production ? "primary" : "secondary"} busy={busy === "import"} disabled={busy !== null || !importable} onClick={() => void run("import")}>Import the dataset</Button>
                <p className="min-w-0 max-w-xl text-sm text-ink-600">
                  {importable
                    ? "The analysis runs on the imported data with the plant's evidence. Cleaning costs and the value of energy can be added afterwards, by running it again."
                    : "The file has to pass the check before it can be imported."}
                </p>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
