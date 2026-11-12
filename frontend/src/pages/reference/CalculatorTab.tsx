import { useState } from "react";
import type { FormEvent } from "react";

import { endpoints } from "../../api/endpoints";
import type { EconomicsResponse } from "../../api/types";
import { EconomicsCard } from "../../components/analysis/EconomicsPanel";
import { AssumptionsForm } from "../../components/forms/AssumptionsForm";
import { Button, Card, CardHeader, ErrorNote, Field, Notice, TextInput } from "../../components/ui";
import { toApiError } from "../../hooks/useAsync";
import { emptyAssumptions, hasErrors, parseAssumptions } from "../../lib/assumptions";
import { focusFirstInvalid } from "../../lib/forms";
import type { AssumptionErrors } from "../../lib/assumptions";
import { parseOptionalNumber } from "../../lib/format";

const ENERGY_FIELDS = [
  ["low", "Low estimate, kWh"],
  ["base", "Central estimate, kWh"],
  ["high", "High estimate, kWh"],
] as const;

/** Cost-benefit arithmetic on figures typed here. It does not look at any data and recommends nothing. */
export function CalculatorTab() {
  const [energy, setEnergy] = useState({ low: "", base: "", high: "", horizon: "" });
  const [energyError, setEnergyError] = useState<string | null>(null);
  const [fields, setFields] = useState(emptyAssumptions);
  const [errors, setErrors] = useState<AssumptionErrors>({});
  const [response, setResponse] = useState<EconomicsResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLElement;
    const parsed = parseAssumptions(fields);
    setErrors(parsed.errors);
    const [low, base, high, horizon] = [energy.low, energy.base, energy.high, energy.horizon].map(parseOptionalNumber);
    const numbers = [low, base, high, horizon];
    if (numbers.some((n) => n === "invalid" || (typeof n === "number" && n < 0))) {
      setEnergyError("Enter non-negative numbers, or leave the fields empty.");
      focusFirstInvalid(form);
      return;
    }
    const ordered = [low, base, high].filter((n): n is number => typeof n === "number");
    if (ordered.some((n, i) => i > 0 && n < (ordered[i - 1] ?? n))) {
      setEnergyError("The low estimate cannot exceed the central one, and the central one cannot exceed the high one.");
      focusFirstInvalid(form);
      return;
    }
    if (typeof horizon === "number" && (horizon <= 0 || horizon > 366)) {
      setEnergyError("The horizon must be between 1 and 366 days.");
      focusFirstInvalid(form);
      return;
    }
    setEnergyError(null);
    if (hasErrors(parsed.errors)) {
      focusFirstInvalid(form);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResponse(await endpoints.calculateEconomics({
        recoverable_low_kwh: low as number | null,
        recoverable_base_kwh: base as number | null,
        recoverable_high_kwh: high as number | null,
        horizon_days: horizon as number | null,
        // An empty form still has a currency; every amount stays "not supplied".
        inputs: parsed.economics ?? {
          currency: fields.currency.trim().toUpperCase() || "DZD",
          energy_value_classification: "USER_ASSUMPTION",
          cost_classification: "USER_ASSUMPTION",
        },
      }));
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Notice tone="info" title="A calculator, not a recommendation">
        This compares the cost of one cleaning with the value of the energy it would recover, using only the figures
        typed below. The recoverable energy is taken as given: the calculation says nothing about whether soiling is
        present. To decide on a cleaning, run an analysis on a dataset.
      </Notice>
      <form onSubmit={submit} noValidate>
        <Card aria-labelledby="calc-title">
          <CardHeader id="calc-title" title="Inputs" description="Leave a field empty when the figure is not known. The result then says which inputs are missing; nothing is assumed in their place." />
          <fieldset className="px-5 py-5">
            <legend className="float-left mb-1 w-full text-sm font-semibold text-ink-900">Energy a cleaning would recover</legend>
            <p className="clear-both mb-4 max-w-3xl text-sm text-ink-600">Over the period during which the cleaning keeps its effect. An analysis estimates this from a measured soiling loss; here it is yours to supply.</p>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {ENERGY_FIELDS.map(([key, label]) => (
                <Field key={key} label={label} optional>
                  {(props) => <TextInput {...props} inputMode="decimal" placeholder="not supplied" value={energy[key]} onChange={(e) => setEnergy({ ...energy, [key]: e.target.value })} />}
                </Field>
              ))}
              <Field label="Benefit horizon, days" optional>
                {(props) => <TextInput {...props} inputMode="decimal" placeholder="not supplied" value={energy.horizon} onChange={(e) => setEnergy({ ...energy, horizon: e.target.value })} />}
              </Field>
            </div>
            {energyError && <p role="alert" className="mt-3 text-sm font-medium text-rose-700">{energyError}</p>}
          </fieldset>
          <AssumptionsForm fields={fields} errors={errors} onChange={setFields} sections={["economics"]} disabled={busy} />
          <div className="flex flex-wrap items-center gap-3 border-t border-ink-100 px-5 py-4">
            <Button type="submit" variant="primary" busy={busy}>Calculate</Button>
            {hasErrors(errors) && <p role="alert" className="text-sm font-medium text-rose-700">Some inputs need attention.</p>}
          </div>
        </Card>
      </form>
      {error && <ErrorNote error={error} />}
      {response && (
        <div className="space-y-4" aria-live="polite">
          <Notice tone="neutral" title="Advisory result">{response.notice}</Notice>
          <EconomicsCard economics={response.result} />
        </div>
      )}
    </div>
  );
}
