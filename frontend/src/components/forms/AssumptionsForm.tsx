import type { ReactNode } from "react";

import type { AssumptionErrors, AssumptionField, AssumptionFields } from "../../lib/assumptions";
import { humanize } from "../../lib/format";
import { Field, Select, TextInput } from "../ui";

const BASES = ["SELLING_PRICE", "AVOIDED_PURCHASE_COST", "INTERNAL_VALUATION", "CONSUMER_TARIFF_PROXY"];
const BASIS_HINT: Record<string, string> = {
  SELLING_PRICE: "What the plant is paid per kWh delivered.",
  AVOIDED_PURCHASE_COST: "What a kWh would cost if it had to be bought instead.",
  INTERNAL_VALUATION: "A value the organisation has adopted for its own decisions.",
  CONSUMER_TARIFF_PROXY: "A consumer tariff used as a stand-in. Illustrative only: never decision-grade.",
};
const CLASSIFICATIONS = ["OFFICIAL_REFERENCE", "TECHNICAL_REFERENCE", "USER_ASSUMPTION"];

interface Props {
  fields: AssumptionFields;
  errors: AssumptionErrors;
  onChange: (fields: AssumptionFields) => void;
  /** Which groups to show. The stand-alone calculator has no cleaning assumptions. */
  sections?: ("cleaning" | "economics")[];
  disabled?: boolean;
}

function Group({ title, description, children }: { title: string; description: ReactNode; children: ReactNode }) {
  return (
    <fieldset className="border-t border-ink-100 px-5 py-5 first:border-t-0">
      <legend className="float-left mb-1 w-full text-sm font-semibold text-ink-900">{title}</legend>
      <p className="clear-both mb-4 max-w-3xl text-sm text-ink-600">{description}</p>
      {children}
    </fieldset>
  );
}

export function AssumptionsForm({ fields, errors, onChange, sections = ["cleaning", "economics"], disabled = false }: Props) {
  const set = (name: AssumptionField, value: string) => onChange({ ...fields, [name]: value });

  const number = (name: AssumptionField, label: string, hint?: string) => (
    <Field label={label} hint={hint} error={errors[name]} optional>
      {(props) => (
        <TextInput
          {...props}
          inputMode="decimal"
          autoComplete="off"
          disabled={disabled}
          value={fields[name]}
          placeholder="not supplied"
          onChange={(event) => set(name, event.target.value)}
        />
      )}
    </Field>
  );

  const text = (name: AssumptionField, label: string, hint?: string) => (
    <Field label={label} hint={hint} error={errors[name]} optional>
      {(props) => (
        <TextInput {...props} disabled={disabled} maxLength={500} value={fields[name]} onChange={(event) => set(name, event.target.value)} />
      )}
    </Field>
  );

  const classification = (name: AssumptionField, label: string) => (
    <Field label={label} hint="Where the figure comes from. An unverified figure is a user assumption.">
      {(props) => (
        <Select {...props} disabled={disabled} value={fields[name]} onChange={(event) => set(name, event.target.value)}>
          {CLASSIFICATIONS.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
        </Select>
      )}
    </Field>
  );

  return (
    <div>
      {sections.includes("cleaning") && (
        <Group
          title="Effect of a cleaning"
          description="Your assumptions about the site and the cleaning method. None has a default: without them, no recoverable energy is estimated and the engine says so."
        >
          <div className="grid gap-4 sm:grid-cols-3">
            {number("cleaning_effectiveness_pct", "Cleaning effectiveness, %", "Share of the soiling loss a cleaning removes.")}
            {number("cleaning_effectiveness_low_pct", "Low, %")}
            {number("cleaning_effectiveness_high_pct", "High, %")}
            {number("benefit_horizon_days", "Benefit horizon, days", "How long the cleaning keeps its benefit.")}
            {number("benefit_horizon_days_low", "Low, days")}
            {number("benefit_horizon_days_high", "High, days")}
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_2fr]">
            {number("projected_daily_clean_energy_kwh", "Clean-array energy, kWh per day", "Empty: the mean of the assessment window is carried forward.")}
            {text("source_note", "Basis of these assumptions", "For example: cleaning trial of March, contractor's specification.")}
          </div>
        </Group>
      )}

      {sections.includes("economics") && (
        <>
          <Group
            title="Value of the energy"
            description="No price is built in. Enter the value that applies to this plant and say what it represents."
          >
            <div className="grid gap-4 sm:grid-cols-[8rem_1fr_1fr]">
              <Field label="Currency" error={errors.currency}>
                {(props) => (
                  <TextInput {...props} disabled={disabled} maxLength={3} value={fields.currency} className="uppercase" onChange={(event) => set("currency", event.target.value)} />
                )}
              </Field>
              {number("energy_value_per_kwh", "Energy value, per kWh")}
              <Field label="What the value represents" error={errors.energy_value_basis} hint={BASIS_HINT[fields.energy_value_basis]}>
                {(props) => (
                  <Select {...props} disabled={disabled} value={fields.energy_value_basis} onChange={(event) => set("energy_value_basis", event.target.value)}>
                    <option value="">not supplied</option>
                    {BASES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
                  </Select>
                )}
              </Field>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_2fr]">
              {classification("energy_value_classification", "Classification of the value")}
              {text("energy_value_source", "Source of the value", "Contract, decision, internal note - with its reference.")}
            </div>
          </Group>

          <Group
            title="Cost of one cleaning"
            description="Give each item as a total, or as a quantity and a unit price. An item left empty is reported as missing; it is not counted as zero. Enter 0 when an item really costs nothing."
          >
            <div className="grid gap-4 sm:grid-cols-3">
              {number("water_cost", "Water, total")}
              {number("water_volume_m3", "or volume, m³")}
              {number("water_price_per_m3", "× price per m³")}
              {number("labour_cost", "Labour, total")}
              {number("labour_hours", "or hours")}
              {number("labour_rate_per_hour", "× rate per hour")}
              {number("equipment_cost", "Equipment")}
              {number("operational_cost", "Other operating costs")}
              {number("cost_uncertainty_pct", "Cost uncertainty, %", "Spread applied in the conservative and optimistic cases.")}
              {number("downtime_cost", "Downtime, total")}
              {number("downtime_energy_kwh", "or energy not produced, kWh", "Valued at the energy value above.")}
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_2fr]">
              {classification("cost_classification", "Classification of the costs")}
              {text("cost_source", "Source of the costs")}
            </div>
          </Group>
        </>
      )}
    </div>
  );
}
