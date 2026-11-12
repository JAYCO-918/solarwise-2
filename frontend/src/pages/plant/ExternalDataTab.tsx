import { CloudOff } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { endpoints } from "../../api/endpoints";
import type { Plant, PvgisMonth, UploadCheck } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ValidationReportView } from "../../components/ValidationReportView";
import { Button, Card, CardHeader, Checkbox, ErrorNote, Field, Notice, Table, Td, TextInput, Th } from "../../components/ui";
import { toApiError } from "../../hooks/useAsync";
import { fmtNumber, parseOptionalNumber } from "../../lib/format";
import { canEdit } from "../../lib/labels";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** An external service that does not answer is reported as such. No substitute figure is ever shown. */
function ExternalFailure({ error }: { error: Error }) {
  if (error instanceof ApiError && error.code.startsWith("EXTERNAL_")) {
    return (
      <div role="alert" className="flex items-start gap-3 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
        <CloudOff className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div>
          <p className="font-semibold">The external service did not provide data.</p>
          <p className="mt-0.5">{error.message}</p>
          <p className="mt-1">Nothing was stored and nothing was substituted. Try again later, or enter the values by hand.</p>
        </div>
      </div>
    );
  }
  return <ErrorNote error={error} />;
}

function PvgisCard({ plant, onChange }: { plant: Plant; onChange: (plant: Plant) => void }) {
  const { meta } = useAuth();
  const editable = canEdit(plant.role);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState(false);
  const [source, setSource] = useState("");
  const [energy, setEnergy] = useState<string[]>(() => MONTHS.map(() => ""));
  const [irradiation, setIrradiation] = useState<string[]>(() => MONTHS.map(() => ""));

  async function fetchFromService() {
    setBusy(true);
    setError(null);
    try {
      onChange(await endpoints.fetchPvgis(plant.id));
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  async function saveManual(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const months: PvgisMonth[] = [];
    for (let i = 0; i < 12; i += 1) {
      const e = parseOptionalNumber(energy[i] ?? "");
      const h = parseOptionalNumber(irradiation[i] ?? "");
      if (e === null || e === "invalid" || h === null || h === "invalid" || e < 0 || h < 0) {
        return setError(new Error(`${MONTHS[i]}: both values are required. A typical year has twelve complete months.`));
      }
      months.push({ month: i + 1, e_d_kwh_per_kwp: e, h_i_d_kwh_m2: h, e_m_kwh_per_kwp: null, sd_m_kwh_per_kwp: null });
    }
    if (source.trim().length < 3) return setError(new Error("Say where the values come from: PVGIS version, database, date of the query."));
    setBusy(true);
    try {
      onChange(await endpoints.setPvgis(plant.id, months, source.trim()));
      setManual(false);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card aria-labelledby="pvgis-title">
      <CardHeader
        id="pvgis-title"
        title="Typical year (PVGIS)"
        description="Long-term monthly averages for the plant's location, from the European Commission's PVGIS. They describe a typical year, not the weather of an analysed period: a baseline built from them carries a wide uncertainty."
        actions={
          editable ? (
            <>
              <Button size="sm" busy={busy} disabled={meta ? !meta.external_data_enabled : false} onClick={fetchFromService}>Fetch from PVGIS</Button>
              <Button size="sm" variant="ghost" onClick={() => setManual((v) => !v)}>{manual ? "Close" : "Enter by hand"}</Button>
            </>
          ) : undefined
        }
      />
      <div className="space-y-4 px-5 py-5">
        {meta && !meta.external_data_enabled && <Notice tone="neutral">Outbound requests are switched off on this server. Values can be entered by hand.</Notice>}
        {error && <ExternalFailure error={error} />}
        {!plant.pvgis.available && !manual && (
          <p className="text-sm text-ink-600">No typical year is stored for this plant. Analyses use the expected energy supplied with each dataset.</p>
        )}
      </div>
      {plant.pvgis.available && (
        <>
          <p className="px-5 pb-3 text-sm text-ink-700">Source: {plant.pvgis.source ?? "not recorded"}</p>
          <Table>
            <thead><tr><Th>Month</Th><Th numeric>Energy, kWh per kWp per day</Th><Th numeric>In-plane irradiation, kWh/m² per day</Th><Th numeric>Year-to-year spread, kWh per kWp</Th></tr></thead>
            <tbody>
              {plant.pvgis.months.map((month) => (
                <tr key={month.month}>
                  <Td className="font-medium">{MONTHS[month.month - 1]}</Td>
                  <Td numeric>{fmtNumber(month.e_d_kwh_per_kwp, 2)}</Td>
                  <Td numeric>{fmtNumber(month.h_i_d_kwh_m2, 2)}</Td>
                  <Td numeric>{month.sd_m_kwh_per_kwp === null ? "not available" : fmtNumber(month.sd_m_kwh_per_kwp, 1)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </>
      )}
      {manual && (
        <form onSubmit={saveManual} className="space-y-4 border-t border-ink-100 px-5 py-5" noValidate>
          <p className="text-sm text-ink-600">Copy the monthly values of a PVGIS “PVcalc” result for this location and configuration.</p>
          <div className="relative overflow-x-auto">
            <table className="w-full max-w-2xl text-left text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-ink-500">
                  <th className="pb-2 pr-4 font-semibold">Month</th>
                  <th className="pb-2 pr-4 font-semibold">E_d, kWh/kWp/day</th>
                  <th className="pb-2 font-semibold">H(i)_d, kWh/m²/day</th>
                </tr>
              </thead>
              <tbody>
                {MONTHS.map((name, i) => (
                  <tr key={name}>
                    <td className="py-1 pr-4">{name}</td>
                    <td className="py-1 pr-4">
                      <TextInput aria-label={`${name}: energy per kWp per day`} inputMode="decimal" value={energy[i] ?? ""} onChange={(e) => setEnergy((v) => v.map((x, k) => (k === i ? e.target.value : x)))} />
                    </td>
                    <td className="py-1">
                      <TextInput aria-label={`${name}: in-plane irradiation per day`} inputMode="decimal" value={irradiation[i] ?? ""} onChange={(e) => setIrradiation((v) => v.map((x, k) => (k === i ? e.target.value : x)))} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Field label="Source" hint="PVGIS version, radiation database and date of the query." className="max-w-2xl">
            {(props) => <TextInput {...props} maxLength={480} value={source} onChange={(e) => setSource(e.target.value)} />}
          </Field>
          <Button type="submit" variant="primary" busy={busy}>Store the typical year</Button>
        </form>
      )}
    </Card>
  );
}

function NasaPowerCard({ plant }: { plant: Plant }) {
  const { meta } = useAuth();
  const editable = canEdit(plant.role);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [store, setStore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [check, setCheck] = useState<UploadCheck | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!start || !end) return setError(new Error("Give the first and the last day."));
    setBusy(true);
    setError(null);
    setCheck(null);
    try {
      setCheck(await endpoints.nasaPower(plant.id, start, end, store));
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card aria-labelledby="nasa-title">
      <CardHeader
        id="nasa-title"
        title="Weather context (NASA POWER)"
        description="Daily irradiation, temperature, wind and rain for the grid cell that contains the plant. These are modelled values from satellite and reanalysis products: context for an analysis, never a measurement of the site and never evidence of soiling."
      />
      {!editable ? (
        <p className="px-5 py-5 text-sm text-ink-600">You have read-only access to this plant.</p>
      ) : (
        <form onSubmit={submit} className="space-y-4 px-5 py-5" noValidate>
          {meta && !meta.external_data_enabled && <Notice tone="neutral">Outbound requests are switched off on this server.</Notice>}
          <div className="grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <Field label="First day">
              {(props) => <TextInput {...props} type="date" value={start} onChange={(e) => setStart(e.target.value)} />}
            </Field>
            <Field label="Last day">
              {(props) => <TextInput {...props} type="date" value={end} onChange={(e) => setEnd(e.target.value)} />}
            </Field>
            <Button type="submit" variant="primary" busy={busy} disabled={meta ? !meta.external_data_enabled : false}>{store ? "Fetch and store" : "Preview"}</Button>
          </div>
          <Checkbox
            label="Store the result as a weather dataset of the plant"
            hint="A stored weather dataset can be attached to an analysis of daily production data. It is classified MODELLED."
            checked={store}
            onChange={(e) => setStore(e.target.checked)}
          />
          {error && <ExternalFailure error={error} />}
          {check && (
            <div className="space-y-3">
              {check.stored && check.dataset && (
                <Notice tone="info" title="Stored">
                  The weather dataset was stored. <Link to={`/datasets/${check.dataset.id}`} className="font-medium underline">Open it</Link>.
                </Notice>
              )}
              {!check.stored && check.duplicate_of !== null && (
                <Notice tone="neutral">
                  These data are already stored for this plant. <Link to={`/datasets/${check.duplicate_of}`} className="font-medium underline">Open the dataset</Link>.
                </Notice>
              )}
              <ValidationReportView report={check.report} />
            </div>
          )}
        </form>
      )}
    </Card>
  );
}

export function ExternalDataTab({ plant, onChange }: { plant: Plant; onChange: (plant: Plant) => void }) {
  return (
    <div className="space-y-6">
      <PvgisCard plant={plant} onChange={onChange} />
      <NasaPowerCard plant={plant} />
    </div>
  );
}
