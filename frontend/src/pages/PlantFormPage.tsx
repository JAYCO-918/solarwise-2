import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { endpoints } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { PlantSpecForm } from "../components/forms/PlantSpecForm";
import { Button, Card, ErrorNote, Field, LinkButton, Notice, PageHeader, Textarea } from "../components/ui";
import { toApiError } from "../hooks/useAsync";
import { focusFirstInvalid } from "../lib/forms";
import { emptySpecValues, parseSpec } from "../lib/plantSpec";

export default function PlantFormPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [values, setValues] = useState(emptySpecValues);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLElement;
    const parsed = parseSpec(values, notes);
    setErrors(parsed.errors);
    if (!parsed.spec) {
      focusFirstInvalid(form);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const plant = await endpoints.createPlant(parsed.spec, description.trim());
      navigate(`/plants/${plant.id}`);
    } catch (cause) {
      setError(toApiError(cause));
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow={<Link to="/plants" className="underline underline-offset-2">Plants</Link>}
        title="Register a plant"
        description="What the plant is: where it stands, how large it is, how it is built. The engine uses it to model what the plant should produce. Only the name, the capacity and the coordinates are required. What the plant measured - production, weather, soiling, events - is not typed in here: it is uploaded as a file once the plant is registered."
      />
      {user?.is_demo && (
        <Notice tone="simulated" className="mb-6" title="Demonstration session">
          A plant registered here is a demonstration plant: its results are always marked simulated and it can never
          receive an operational authorisation.
        </Notice>
      )}
      <form onSubmit={submit} noValidate>
        <Card className="px-5 py-5">
          <PlantSpecForm values={values} notes={notes} errors={errors} onChange={setValues} onNotesChange={setNotes} />
          <div className="mt-6">
            <Field label="Description" optional>
              {(props) => <Textarea {...props} maxLength={4000} value={description} onChange={(e) => setDescription(e.target.value)} />}
            </Field>
          </div>
        </Card>
        {Object.keys(errors).length > 0 && (
          <p role="alert" className="mt-4 text-sm font-medium text-rose-700">Some fields need attention before the plant can be registered.</p>
        )}
        {error && <div className="mt-4"><ErrorNote error={error} /></div>}
        <div className="mt-6 flex gap-3">
          <Button type="submit" variant="primary" busy={busy}>Register the plant</Button>
          <LinkButton to="/plants" variant="ghost">Cancel</LinkButton>
        </div>
      </form>
    </div>
  );
}
