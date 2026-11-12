import { Trash2 } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";

import { endpoints } from "../../api/endpoints";
import type { EvidenceIn, Plant, Provenance } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ProvenanceBadge } from "../../components/badges";
import { Button, Card, CardHeader, Checkbox, EmptyState, ErrorNote, Field, Loading, Notice, Select, Table, Td, TextInput, Textarea, Th } from "../../components/ui";
import { toApiError, useAsync } from "../../hooks/useAsync";
import { fmtInstant, fmtNumber, humanize, parseOptionalNumber } from "../../lib/format";
import { PROVENANCE_MEANING, canEdit } from "../../lib/labels";
import { zonedIso } from "../../lib/timezone";

const TYPES = [
  "SOILING_MEASUREMENT", "VISUAL_INSPECTION", "INVERTER_FAULT", "SHADING_OBSERVATION", "CURTAILMENT_EVENT",
  "GRID_OUTAGE", "SENSOR_FAULT", "CLEANING_EVENT", "OTHER",
] as const;
const FINDINGS = ["SOILING_HEAVY", "SOILING_LIGHT", "CLEAN", "SHADING", "EQUIPMENT_DAMAGE", "NO_FINDING"] as const;
const SOILING_METHODS = [
  "SOILING_STATION", "CLEAN_REFERENCE_MODULE", "STRING_COMPARISON", "IV_CURVE", "OPTICAL_SENSOR", "VALIDATED_MODEL",
  "VISUAL_ESTIMATE", "UNSPECIFIED",
] as const;
const PROVENANCES: Provenance[] = ["UNKNOWN", "MEASURED", "MODELLED", "SYNTHETIC"];
const RESOLVABLE = new Set(["INVERTER_FAULT", "GRID_OUTAGE", "SENSOR_FAULT", "SHADING_OBSERVATION"]);

const TYPE_HINT: Record<string, string> = {
  SOILING_MEASUREMENT: "A soiling ratio (clean = 1.00) with its method. Only direct methods can make soiling credible.",
  VISUAL_INSPECTION: "What an inspection found. It can support or contradict a measurement; it does not quantify a loss.",
  INVERTER_FAULT: "An equipment fault. While it is open, cleaning is not recommended.",
  SHADING_OBSERVATION: "An observed shadow on the array.",
  CURTAILMENT_EVENT: "A power limit imposed by the grid operator.",
  GRID_OUTAGE: "A period during which the plant could not export.",
  SENSOR_FAULT: "A sensor known to be wrong during a period.",
  CLEANING_EVENT: "A cleaning that took place. It resets the soiling trend.",
  OTHER: "Anything else worth recording.",
};

interface FormState {
  reference: string;
  evidence_type: (typeof TYPES)[number];
  start: string;
  end: string;
  provenance: Provenance;
  source: string;
  method: string;
  description: string;
  value: string;
  std_uncertainty: string;
  soiling_method: string;
  finding: string;
  device_code: string;
  resolved: boolean;
  document_ref: string;
}

const EMPTY: FormState = {
  reference: "", evidence_type: "SOILING_MEASUREMENT", start: "", end: "", provenance: "UNKNOWN", source: "", method: "",
  description: "", value: "", std_uncertainty: "", soiling_method: "", finding: "", device_code: "", resolved: false, document_ref: "",
};

export function EvidenceTab({ plant }: { plant: Plant }) {
  const { user } = useAuth();
  const evidence = useAsync((signal) => endpoints.evidence(plant.id, signal), [plant.id]);
  const editable = canEdit(plant.role);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((current) => ({ ...current, [key]: value }));
  const isSoiling = form.evidence_type === "SOILING_MEASUREMENT";
  const isInspection = form.evidence_type === "VISUAL_INSPECTION";

  async function add(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const start = zonedIso(form.start, plant.spec.timezone);
    const end = form.end === "" ? null : zonedIso(form.end, plant.spec.timezone);
    const value = parseOptionalNumber(form.value);
    const uncertainty = parseOptionalNumber(form.std_uncertainty);
    if (form.reference.trim() === "" || start === null) return setError(new Error("Give a reference and the date and time of the observation."));
    if (form.end !== "" && end === null) return setError(new Error("The end of the observation is not a valid date and time."));
    if (value === "invalid" || uncertainty === "invalid") return setError(new Error("The value and its uncertainty must be numbers, or empty."));
    if (form.provenance !== "UNKNOWN" && form.source.trim() === "") return setError(new Error("Name the source behind the declared provenance."));

    const body: EvidenceIn = {
      reference: form.reference.trim(),
      evidence_type: form.evidence_type,
      observed_start: start,
      observed_end: end,
      provenance: form.provenance,
      source: form.source.trim(),
      method: form.method.trim() || null,
      description: form.description.trim(),
      value: isSoiling ? value : null,
      unit: isSoiling && value !== null ? "fraction" : null,
      std_uncertainty: isSoiling ? uncertainty : null,
      soiling_method: isSoiling && form.soiling_method ? (form.soiling_method as EvidenceIn["soiling_method"]) : null,
      finding: isInspection && form.finding ? (form.finding as EvidenceIn["finding"]) : null,
      device_code: form.device_code.trim() || null,
      resolved: RESOLVABLE.has(form.evidence_type) ? form.resolved : null,
      document_ref: form.document_ref.trim() || null,
    };
    setBusy(true);
    try {
      await endpoints.addEvidence(plant.id, body);
      setForm(EMPTY);
      evidence.reload();
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number, reference: string) {
    if (!window.confirm(`Delete evidence record ${reference}?`)) return;
    setError(null);
    try {
      await endpoints.deleteEvidence(plant.id, id);
      evidence.reload();
    } catch (cause) {
      setError(toApiError(cause));
    }
  }

  return (
    <div className="space-y-6">
      <Card aria-labelledby="evidence-title">
        <CardHeader
          id="evidence-title"
          title="Evidence records"
          description="Dated observations that are not in the time series: soiling measurements, inspections, faults, curtailment, cleanings. Each one carries its provenance; records that fall in the analysed period are used by the analysis."
        />
        {evidence.loading && <Loading label="Loading the evidence" />}
        {evidence.error && <div className="p-5"><ErrorNote error={evidence.error} onRetry={evidence.reload} /></div>}
        {evidence.data && evidence.data.length === 0 && (
          <EmptyState title="No evidence recorded">Without a direct soiling measurement, a production gap cannot be attributed to soiling.</EmptyState>
        )}
        {evidence.data && evidence.data.length > 0 && (
          <Table>
            <thead><tr><Th>Reference</Th><Th>Type</Th><Th>Observed</Th><Th>Provenance</Th><Th>Content</Th><Th /></tr></thead>
            <tbody>
              {evidence.data.map((row) => {
                const record = row.record;
                return (
                  <tr key={row.id}>
                    <Td className="font-mono text-xs font-medium">{record.reference}</Td>
                    <Td>
                      {humanize(record.evidence_type)}
                      {record.resolved !== null && <span className="block text-xs text-ink-500">{record.resolved ? "resolved" : "open"}</span>}
                    </Td>
                    <Td className="whitespace-nowrap">
                      {fmtInstant(record.observed_start)}
                      {record.observed_end && <span className="block text-xs text-ink-500">to {fmtInstant(record.observed_end)}</span>}
                    </Td>
                    <Td>
                      <ProvenanceBadge label={row.provenance_label} />
                      <span className="mt-1 block max-w-[16rem] text-xs text-ink-500">{record.tag.source}</span>
                    </Td>
                    <Td className="max-w-md text-ink-700">
                      {record.description}
                      {record.value !== null && (
                        <span className="tabular block text-xs text-ink-600">
                          value {fmtNumber(record.value, 3)} {record.unit ?? ""}{record.std_uncertainty !== null && ` ± ${fmtNumber(record.std_uncertainty, 3)}`}
                          {record.soiling_method && ` · ${humanize(record.soiling_method).toLowerCase()}`}
                        </span>
                      )}
                      {record.finding && <span className="block text-xs text-ink-600">finding: {humanize(record.finding).toLowerCase()}</span>}
                      {record.device_code && <span className="block font-mono text-xs text-ink-600">{record.device_code}</span>}
                    </Td>
                    <Td className="text-right">
                      {editable && row.dataset_id === null && (
                        <Button size="sm" variant="ghost" onClick={() => remove(row.id, record.reference)} aria-label={`Delete evidence ${record.reference}`}>
                          <Trash2 className="size-4" aria-hidden />
                        </Button>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>

      {editable && (
        <Card aria-labelledby="add-evidence-title">
          <CardHeader id="add-evidence-title" title="Record evidence" description={TYPE_HINT[form.evidence_type]} />
          <form onSubmit={add} className="space-y-5 px-5 py-5" noValidate>
            {user?.is_demo && (
              <Notice tone="simulated">
                Evidence entered in a demonstration session is stored as synthetic, whatever is declared: nothing
                entered here is an observation of a real plant.
              </Notice>
            )}
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Type">
                {(props) => (
                  <Select {...props} value={form.evidence_type} onChange={(e) => set("evidence_type", e.target.value as FormState["evidence_type"])}>
                    {TYPES.map((type) => <option key={type} value={type}>{humanize(type)}</option>)}
                  </Select>
                )}
              </Field>
              <Field label="Reference" hint="Your identifier: work order, report number.">
                {(props) => <TextInput {...props} maxLength={64} value={form.reference} onChange={(e) => set("reference", e.target.value)} />}
              </Field>
              <Field label="Supporting document" optional>
                {(props) => <TextInput {...props} maxLength={500} value={form.document_ref} onChange={(e) => set("document_ref", e.target.value)} />}
              </Field>
              <Field label="Observed from" hint={`Local time of the plant (${plant.spec.timezone}).`}>
                {(props) => <TextInput {...props} type="datetime-local" value={form.start} onChange={(e) => set("start", e.target.value)} />}
              </Field>
              <Field label="Observed until" optional>
                {(props) => <TextInput {...props} type="datetime-local" value={form.end} onChange={(e) => set("end", e.target.value)} />}
              </Field>
              <Field label="Device" optional hint="Code of the device concerned.">
                {(props) => <TextInput {...props} maxLength={64} value={form.device_code} onChange={(e) => set("device_code", e.target.value)} />}
              </Field>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Provenance" hint={PROVENANCE_MEANING[form.provenance]}>
                {(props) => (
                  <Select {...props} value={form.provenance} onChange={(e) => set("provenance", e.target.value as Provenance)}>
                    {PROVENANCES.map((p) => <option key={p} value={p}>{p === "UNKNOWN" ? "Unknown - not documented" : humanize(p)}</option>)}
                  </Select>
                )}
              </Field>
              <Field label="Source" hint="Instrument, person or system that produced the observation.">
                {(props) => <TextInput {...props} maxLength={500} value={form.source} onChange={(e) => set("source", e.target.value)} />}
              </Field>
              <Field label="Method" optional>
                {(props) => <TextInput {...props} maxLength={500} value={form.method} onChange={(e) => set("method", e.target.value)} />}
              </Field>
            </div>

            {isSoiling && (
              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="Soiling ratio" hint="Soiled output divided by clean output. 0.95 means a 5 % loss.">
                  {(props) => <TextInput {...props} inputMode="decimal" placeholder="not measured" value={form.value} onChange={(e) => set("value", e.target.value)} />}
                </Field>
                <Field label="Standard uncertainty" optional hint="In the same unit, one sigma.">
                  {(props) => <TextInput {...props} inputMode="decimal" placeholder="not declared" value={form.std_uncertainty} onChange={(e) => set("std_uncertainty", e.target.value)} />}
                </Field>
                <Field label="How it was obtained">
                  {(props) => (
                    <Select {...props} value={form.soiling_method} onChange={(e) => set("soiling_method", e.target.value)}>
                      <option value="">not specified</option>
                      {SOILING_METHODS.map((method) => <option key={method} value={method}>{humanize(method)}</option>)}
                    </Select>
                  )}
                </Field>
              </div>
            )}
            {isInspection && (
              <Field label="Finding" className="sm:max-w-xs">
                {(props) => (
                  <Select {...props} value={form.finding} onChange={(e) => set("finding", e.target.value)}>
                    <option value="">not specified</option>
                    {FINDINGS.map((finding) => <option key={finding} value={finding}>{humanize(finding)}</option>)}
                  </Select>
                )}
              </Field>
            )}
            {RESOLVABLE.has(form.evidence_type) && (
              <Checkbox label="The issue has been resolved" hint="An open issue blocks a cleaning recommendation." checked={form.resolved} onChange={(e) => set("resolved", e.target.checked)} />
            )}
            <Field label="Description" optional>
              {(props) => <Textarea {...props} maxLength={2000} value={form.description} onChange={(e) => set("description", e.target.value)} />}
            </Field>
            {error && <ErrorNote error={error} />}
            <Button type="submit" variant="primary" busy={busy}>Record the evidence</Button>
          </form>
        </Card>
      )}
      {!editable && error && <ErrorNote error={error} />}
    </div>
  );
}
