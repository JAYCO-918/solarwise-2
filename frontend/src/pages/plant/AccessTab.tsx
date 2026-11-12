import { useState } from "react";
import type { FormEvent } from "react";

import { endpoints } from "../../api/endpoints";
import type { Plant } from "../../api/types";
import { Button, Card, CardHeader, ErrorNote, Field, Loading, Select, Table, Td, TextInput, Th } from "../../components/ui";
import { toApiError, useAsync } from "../../hooks/useAsync";
import { ROLE_LABEL } from "../../lib/labels";

const ROLES = ["VIEWER", "EDITOR", "OWNER"] as const;
const ROLE_HINT: Record<string, string> = {
  VIEWER: "Reads the data and the analyses.",
  EDITOR: "Also adds datasets, devices and evidence, and runs analyses.",
  OWNER: "Also changes the description, manages access and can delete the plant.",
};

export function AccessTab({ plant }: { plant: Plant }) {
  const permissions = useAsync((signal) => endpoints.permissions(plant.id, signal), [plant.id]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string>("VIEWER");
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  async function grant(event: FormEvent) {
    event.preventDefault();
    if (email.trim() === "") return;
    setBusy(true);
    setError(null);
    try {
      await endpoints.grant(plant.id, email.trim(), role);
      setEmail("");
      permissions.reload();
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  async function change(userEmail: string, newRole: string) {
    setError(null);
    try {
      await endpoints.grant(plant.id, userEmail, newRole);
      permissions.reload();
    } catch (cause) {
      setError(toApiError(cause));
    }
  }

  async function revoke(userId: number, userEmail: string) {
    if (!window.confirm(`Withdraw the access of ${userEmail}?`)) return;
    setError(null);
    try {
      await endpoints.revoke(plant.id, userId);
      permissions.reload();
    } catch (cause) {
      setError(toApiError(cause));
    }
  }

  return (
    <div className="space-y-6">
      <Card aria-labelledby="access-title">
        <CardHeader id="access-title" title="Who may access this plant" description="Access is given per plant. A plant always keeps at least one owner." />
        {permissions.loading && <Loading label="Loading the access list" />}
        {permissions.error && <div className="p-5"><ErrorNote error={permissions.error} onRetry={permissions.reload} /></div>}
        {permissions.data && (
          <Table>
            <thead><tr><Th>Account</Th><Th>Access</Th><Th /></tr></thead>
            <tbody>
              {permissions.data.map((permission) => (
                <tr key={permission.user_id}>
                  <Td>
                    <span className="font-medium">{permission.full_name || permission.email}</span>
                    {permission.full_name && <span className="block text-xs text-ink-500">{permission.email}</span>}
                  </Td>
                  <Td>
                    <Select
                      aria-label={`Access of ${permission.email}`}
                      className="max-w-[12rem]"
                      value={permission.role}
                      onChange={(e) => change(permission.email, e.target.value)}
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                    </Select>
                  </Td>
                  <Td className="text-right">
                    <Button size="sm" variant="ghost" onClick={() => revoke(permission.user_id, permission.email)}>Withdraw</Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {error && <ErrorNote error={error} />}
      <Card aria-labelledby="grant-title">
        <CardHeader id="grant-title" title="Give access" description={ROLE_HINT[role]} />
        <form onSubmit={grant} className="grid gap-4 px-5 py-5 sm:grid-cols-[2fr_1fr_auto] sm:items-end" noValidate>
          <Field label="E-mail address of an existing account">
            {(props) => <TextInput {...props} type="email" maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} />}
          </Field>
          <Field label="Access">
            {(props) => (
              <Select {...props} value={role} onChange={(e) => setRole(e.target.value)}>
                {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </Select>
            )}
          </Field>
          <Button type="submit" variant="primary" busy={busy}>Give access</Button>
        </form>
      </Card>
    </div>
  );
}
