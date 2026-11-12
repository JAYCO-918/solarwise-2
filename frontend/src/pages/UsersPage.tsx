import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate } from "react-router";

import { endpoints } from "../api/endpoints";
import type { User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, CardHeader, ErrorNote, Field, Loading, PageHeader, Select, Table, Td, TextInput, Th } from "../components/ui";
import { toApiError, useAsync } from "../hooks/useAsync";
import { ROLE_LABEL } from "../lib/labels";

const ROLES = ["VIEWER", "ENGINEER", "ADMIN"] as const;
const ROLE_HINT: Record<string, string> = {
  VIEWER: "Reads the plants shared with the account.",
  ENGINEER: "Registers plants, imports data and runs analyses.",
  ADMIN: "Also manages accounts.",
};

export default function UsersPage() {
  const { user, meta } = useAuth();
  const users = useAsync((signal) => endpoints.users(signal), []);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<(typeof ROLES)[number]>("ENGINEER");
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  if (user && user.role !== "ADMIN") return <Navigate to="/plants" replace />;

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await endpoints.createUser({ email: email.trim(), full_name: fullName.trim(), password, role });
      setEmail("");
      setFullName("");
      setPassword("");
      users.reload();
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  async function update(target: User, change: { is_active?: boolean; role?: string }) {
    setError(null);
    try {
      await endpoints.updateUser(target.id, change);
      users.reload();
    } catch (cause) {
      setError(toApiError(cause));
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Accounts"
        description={
          meta?.registration_open === true
            ? "People create their own account on the sign-in page; it gets the Engineer role. Here you change a role, disable an account, or create one with the role you choose. Access to each plant is given by its owners."
            : "Accounts are created here: sign-up is switched off on this server. Access to each plant is given by its owners."
        }
      />
      <Card aria-labelledby="users-title">
        <CardHeader id="users-title" title="Accounts" />
        {users.loading && <Loading label="Loading the accounts" />}
        {users.error && <div className="p-5"><ErrorNote error={users.error} onRetry={users.reload} /></div>}
        {users.data && (
          <Table>
            <thead><tr><Th>Account</Th><Th>Role</Th><Th>State</Th><Th /></tr></thead>
            <tbody>
              {users.data.map((row) => (
                <tr key={row.id}>
                  <Td>
                    <span className="font-medium">{row.full_name || row.email}</span>
                    {row.full_name && <span className="block text-xs text-ink-500">{row.email}</span>}
                  </Td>
                  <Td>
                    {row.is_demo ? (
                      <Badge className="border-violet-300 bg-violet-50 text-violet-900">Demonstration visitor</Badge>
                    ) : (
                      <Select aria-label={`Role of ${row.email}`} className="max-w-[11rem]" value={row.role} disabled={row.id === user?.id} onChange={(e) => update(row, { role: e.target.value })}>
                        {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}
                      </Select>
                    )}
                  </Td>
                  <Td>{row.is_active ? "Active" : <span className="font-medium text-rose-700">Disabled</span>}</Td>
                  <Td className="text-right">
                    {row.id !== user?.id && (
                      <Button size="sm" variant="ghost" onClick={() => update(row, { is_active: !row.is_active })}>{row.is_active ? "Disable" : "Enable"}</Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {error && <ErrorNote error={error} />}
      <Card aria-labelledby="create-user-title">
        <CardHeader id="create-user-title" title="Create an account" description={ROLE_HINT[role]} />
        <form onSubmit={create} className="grid gap-4 px-5 py-5 sm:grid-cols-2 lg:grid-cols-[1.4fr_1.2fr_1.2fr_1fr_auto] lg:items-end" noValidate>
          <Field label="E-mail address">
            {(props) => <TextInput {...props} type="email" autoComplete="off" maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} />}
          </Field>
          <Field label="Name" optional>
            {(props) => <TextInput {...props} autoComplete="off" maxLength={200} value={fullName} onChange={(e) => setFullName(e.target.value)} />}
          </Field>
          <Field label="Initial password" hint="At least 12 characters.">
            {(props) => <TextInput {...props} type="password" autoComplete="new-password" maxLength={256} value={password} onChange={(e) => setPassword(e.target.value)} />}
          </Field>
          <Field label="Role">
            {(props) => (
              <Select {...props} value={role} onChange={(e) => setRole(e.target.value as (typeof ROLES)[number])}>
                {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}
              </Select>
            )}
          </Field>
          <Button type="submit" variant="primary" busy={busy} disabled={email.trim() === "" || password === ""}>Create</Button>
        </form>
      </Card>
    </div>
  );
}
