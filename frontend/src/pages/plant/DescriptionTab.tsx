import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router";

import { endpoints } from "../../api/endpoints";
import type { Plant } from "../../api/types";
import { PlantSpecForm } from "../../components/forms/PlantSpecForm";
import { Button, Card, CardHeader, ErrorNote, Field, Table, Td, Textarea, Th } from "../../components/ui";
import { toApiError } from "../../hooks/useAsync";
import { fmtDay, fmtNumber, humanize } from "../../lib/format";
import { canEdit } from "../../lib/labels";
import { SPEC_NUMBERS, parseSpec, specValuesFrom } from "../../lib/plantSpec";

export function DescriptionTab({ plant, onChange }: { plant: Plant; onChange: (plant: Plant) => void }) {
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState(() => specValuesFrom(plant.spec));
  const [notes, setNotes] = useState<Record<string, string>>(() => ({ ...plant.spec.parameter_notes }));
  const [description, setDescription] = useState(plant.description);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const spec = plant.spec;
  const owner = plant.role === "OWNER";

  function startEditing() {
    setValues(specValuesFrom(plant.spec));
    setNotes({ ...plant.spec.parameter_notes });
    setDescription(plant.description);
    setErrors({});
    setError(null);
    setEditing(true);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    const parsed = parseSpec(values, notes);
    setErrors(parsed.errors);
    if (!parsed.spec) return;
    setBusy(true);
    setError(null);
    try {
      onChange(await endpoints.updatePlant(plant.id, parsed.spec, description));
      setEditing(false);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete “${plant.name}” with all its datasets, evidence and analyses? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await endpoints.deletePlant(plant.id);
      navigate("/plants");
    } catch (cause) {
      setError(toApiError(cause));
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <form onSubmit={save} noValidate>
        <Card className="px-5 py-5">
          <PlantSpecForm values={values} notes={notes} errors={errors} onChange={setValues} onNotesChange={setNotes} />
          <div className="mt-6">
            <Field label="Description" optional>
              {(props) => <Textarea {...props} maxLength={4000} value={description} onChange={(e) => setDescription(e.target.value)} />}
            </Field>
          </div>
        </Card>
        {error && <div className="mt-4"><ErrorNote error={error} /></div>}
        <div className="mt-6 flex gap-3">
          <Button type="submit" variant="primary" busy={busy}>Save the description</Button>
          <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
        </div>
      </form>
    );
  }

  const rows: [string, string, string][] = [
    ["Time zone", spec.timezone, spec.parameter_notes.timezone ?? ""],
    ["Mounting", humanize(spec.tracking), spec.parameter_notes.tracking ?? ""],
    ["Commissioning date", spec.commissioning_date ? fmtDay(spec.commissioning_date) : "not known", spec.parameter_notes.commissioning_date ?? ""],
    ...SPEC_NUMBERS.map((field): [string, string, string] => {
      const value = spec[field.name as keyof typeof spec] as number | null;
      const shown = value === null ? "not known" : fmtNumber(value * (field.percent ? 100 : 1), Number.isInteger(value * (field.percent ? 100 : 1)) ? 0 : 3);
      return [field.label, shown, spec.parameter_notes[field.name] ?? ""];
    }),
  ];

  return (
    <div className="space-y-6">
      <Card aria-labelledby="description-title">
        <CardHeader
          id="description-title"
          title="Engineering description"
          description="What the engine knows about the plant. A parameter that is not known is left out of the model; it is not replaced by a typical value."
          actions={canEdit(plant.role) ? <Button size="sm" onClick={startEditing}>Edit</Button> : undefined}
        />
        {plant.description && <p className="max-w-4xl px-5 pt-4 text-sm text-ink-700">{plant.description}</p>}
        <div className="pt-2">
          <Table>
            <thead><tr><Th>Parameter</Th><Th numeric>Value</Th><Th>Where the value comes from</Th></tr></thead>
            <tbody>
              {rows.map(([label, value, note]) => (
                <tr key={label}>
                  <Td className="font-medium">{label}</Td>
                  <Td numeric className={value === "not known" ? "text-ink-500" : undefined}>{value}</Td>
                  <Td className="max-w-xl text-ink-700">{note || <span className="text-ink-400">no note</span>}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      </Card>
      {error && <ErrorNote error={error} />}
      {owner && !plant.is_demonstration && (
        <Card className="border-rose-200 px-5 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-ink-700">Deleting the plant removes its datasets, evidence records and analyses.</p>
            <Button variant="danger" size="sm" busy={busy} onClick={remove}>Delete the plant</Button>
          </div>
        </Card>
      )}
    </div>
  );
}
