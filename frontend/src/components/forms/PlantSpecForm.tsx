import { SPEC_NUMBERS } from "../../lib/plantSpec";
import type { SpecValues } from "../../lib/plantSpec";
import { Field, Select, TextInput } from "../ui";

interface Props {
  values: SpecValues;
  notes: Record<string, string>;
  errors: Record<string, string>;
  onChange: (values: SpecValues) => void;
  onNotesChange: (notes: Record<string, string>) => void;
}

/** Each parameter can carry a note saying where its value comes from; the note is shown wherever the value is used. */
export function PlantSpecForm({ values, notes, errors, onChange, onNotesChange }: Props) {
  const set = (name: string, value: string) => onChange({ ...values, [name]: value });
  const setNote = (name: string, value: string) => onNotesChange({ ...notes, [name]: value });

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" error={errors.name}>
          {(props) => <TextInput {...props} maxLength={200} value={values.name ?? ""} onChange={(e) => set("name", e.target.value)} />}
        </Field>
        <Field label="Time zone" error={errors.timezone} hint="IANA name. Daily values are attributed to local days.">
          {(props) => <TextInput {...props} maxLength={64} value={values.timezone ?? ""} onChange={(e) => set("timezone", e.target.value)} />}
        </Field>
        <Field label="Mounting">
          {(props) => (
            <Select {...props} value={values.tracking ?? "FIXED"} onChange={(e) => set("tracking", e.target.value)}>
              <option value="FIXED">Fixed tilt</option>
              <option value="SINGLE_AXIS">Single-axis tracking</option>
              <option value="DUAL_AXIS">Dual-axis tracking</option>
            </Select>
          )}
        </Field>
        <Field label="Commissioning date" optional error={errors.commissioning_date} hint="Needed, with the degradation rate, to account for ageing.">
          {(props) => <TextInput {...props} type="date" value={values.commissioning_date ?? ""} onChange={(e) => set("commissioning_date", e.target.value)} />}
        </Field>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-ink-900">Parameters</h3>
        <p className="mt-1 max-w-3xl text-sm text-ink-600">
          Leave a parameter empty when it is not known: the analysis then leaves out what depends on it instead of
          assuming a typical value. Use the note to record where each value comes from.
        </p>
        <div className="mt-4 divide-y divide-ink-100 rounded-md border border-ink-200">
          {SPEC_NUMBERS.map((field) => (
            <div key={field.name} className="grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
              <Field label={field.label} hint={field.hint} error={errors[field.name]} optional={!field.required}>
                {(props) => (
                  <TextInput
                    {...props}
                    inputMode="decimal"
                    autoComplete="off"
                    placeholder={field.required ? undefined : "not known"}
                    value={values[field.name] ?? ""}
                    onChange={(e) => set(field.name, e.target.value)}
                  />
                )}
              </Field>
              <Field label="Where the value comes from" optional>
                {(props) => (
                  <TextInput {...props} maxLength={500} value={notes[field.name] ?? ""} onChange={(e) => setNote(field.name, e.target.value)} />
                )}
              </Field>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
