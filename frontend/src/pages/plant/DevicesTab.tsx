import { Trash2 } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";

import { endpoints } from "../../api/endpoints";
import type { Plant } from "../../api/types";
import { Button, Card, CardHeader, EmptyState, ErrorNote, Field, Loading, Table, Td, TextInput, Th } from "../../components/ui";
import { toApiError, useAsync } from "../../hooks/useAsync";
import { fmtPower, humanize, parseOptionalNumber } from "../../lib/format";
import { canEdit } from "../../lib/labels";

export function DevicesTab({ plant }: { plant: Plant }) {
  const devices = useAsync((signal) => endpoints.devices(plant.id, signal), [plant.id]);
  const editable = canEdit(plant.role);
  const [code, setCode] = useState("");
  const [capacity, setCapacity] = useState("");
  const [kind, setKind] = useState("INVERTER");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  async function add(event: FormEvent) {
    event.preventDefault();
    const parsed = parseOptionalNumber(capacity);
    if (code.trim() === "" || parsed === null || parsed === "invalid" || parsed <= 0) {
      setError(new Error("Give a code and a capacity greater than zero."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await endpoints.addDevice(plant.id, { code: code.trim(), capacity_kwp: parsed, kind: kind.trim() || "INVERTER", description: description.trim() });
      setCode("");
      setCapacity("");
      setDescription("");
      devices.reload();
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number, deviceCode: string) {
    if (!window.confirm(`Remove device ${deviceCode}?`)) return;
    setError(null);
    try {
      await endpoints.removeDevice(plant.id, id);
      devices.reload();
    } catch (cause) {
      setError(toApiError(cause));
    }
  }

  return (
    <div className="space-y-6">
      <Card aria-labelledby="devices-title">
        <CardHeader
          id="devices-title"
          title="Devices"
          description="Inverters or blocks whose energy appears in device-level rows of a dataset. Their capacities allow each device to be compared with the fleet."
        />
        {devices.loading && <Loading label="Loading the devices" />}
        {devices.error && <div className="p-5"><ErrorNote error={devices.error} onRetry={devices.reload} /></div>}
        {devices.data && devices.data.length === 0 && (
          <EmptyState title="No device registered">Without devices, equipment faults can only be established from evidence records.</EmptyState>
        )}
        {devices.data && devices.data.length > 0 && (
          <Table>
            <thead><tr><Th>Code</Th><Th>Kind</Th><Th numeric>Capacity</Th><Th>Description</Th>{editable && <Th />}</tr></thead>
            <tbody>
              {devices.data.map((device) => (
                <tr key={device.id}>
                  <Td className="font-mono font-medium">{device.code}</Td>
                  <Td>{humanize(device.kind)}</Td>
                  <Td numeric>{fmtPower(device.capacity_kwp, true)}</Td>
                  <Td className="text-ink-700">{device.description}</Td>
                  {editable && (
                    <Td className="text-right">
                      <Button size="sm" variant="ghost" onClick={() => remove(device.id, device.code)} aria-label={`Remove device ${device.code}`}>
                        <Trash2 className="size-4" aria-hidden />
                      </Button>
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {error && <ErrorNote error={error} />}

      {editable && (
        <Card aria-labelledby="add-device-title">
          <CardHeader id="add-device-title" title="Register a device" />
          <form onSubmit={add} className="grid gap-4 px-5 py-5 sm:grid-cols-[1fr_1fr_1fr_2fr_auto] sm:items-end" noValidate>
            <Field label="Code" hint="As written in the dataset.">
              {(props) => <TextInput {...props} maxLength={64} value={code} onChange={(e) => setCode(e.target.value)} />}
            </Field>
            <Field label="Capacity, kWp">
              {(props) => <TextInput {...props} inputMode="decimal" value={capacity} onChange={(e) => setCapacity(e.target.value)} />}
            </Field>
            <Field label="Kind">
              {(props) => <TextInput {...props} maxLength={30} value={kind} onChange={(e) => setKind(e.target.value)} />}
            </Field>
            <Field label="Description" optional>
              {(props) => <TextInput {...props} maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} />}
            </Field>
            <Button type="submit" variant="primary" busy={busy} className="sm:mb-[1.35rem]">Add</Button>
          </form>
        </Card>
      )}
    </div>
  );
}
