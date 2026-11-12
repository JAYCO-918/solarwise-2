import { FlaskConical, LogIn } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";

import { useAuth } from "../auth/AuthContext";
import { AuthShell } from "../components/AuthShell";
import { Button, ErrorNote, Field, Notice, TextInput } from "../components/ui";
import { toApiError } from "../hooks/useAsync";

export function LoginPage() {
  const { status, meta, expired, expiredReason, login, demoLogin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<"login" | "demo" | null>(null);
  const [failure, setFailure] = useState<{ kind: "login" | "demo"; error: Error } | null>(null);

  const from = (location.state as { from?: string } | null)?.from;
  // Only ever return to a path of this application.
  const target = from && from.startsWith("/") && !from.startsWith("//") ? from : "/plants";
  if (status === "authenticated") return <Navigate to={target} replace />;

  async function run(kind: "login" | "demo", action: () => Promise<void>) {
    setBusy(kind);
    setFailure(null);
    try {
      await action();
      navigate(target, { replace: true });
    } catch (cause) {
      setFailure({ kind, error: toApiError(cause) });
    } finally {
      setBusy(null);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void run("login", () => login(email.trim(), password));
  }

  const demo = meta?.demo_mode === true;
  const signUp = meta?.registration_open === true;

  return (
    <AuthShell>
      {expired && (
        <Notice tone="warning" title="The server closed the session" className="mb-6">
          {expiredReason ? `Its answer: ${expiredReason}. ` : ""}Open the session again to continue.
        </Notice>
      )}

      {demo && (
        <section aria-labelledby="demo-title" className="rounded-lg border border-violet-200 bg-violet-50 p-5">
          <h2 id="demo-title" className="flex items-center gap-2 text-xl font-semibold text-ink-950">
            <FlaskConical className="size-5 text-violet-700" aria-hidden /> Try the demonstration
          </h2>
          <p className="mt-2 text-sm text-ink-700">
            Ten synthetic scenarios on the El Foulia reference case: normal operation, confirmed soiling, an inverter
            fault, shading, curtailment, missing data, conflicting evidence and more.
          </p>
          <p className="mt-2 text-sm text-ink-700">
            No account is needed. All data are artificial and every decision is
            marked <strong className="font-semibold">simulated</strong>.
          </p>
          <Button variant="primary" size="lg" className="mt-4 w-full" busy={busy === "demo"} disabled={busy !== null} onClick={() => void run("demo", demoLogin)}>
            Open the demonstration
          </Button>
          {failure?.kind === "demo" && <div className="mt-3"><ErrorNote error={failure.error} /></div>}
        </section>
      )}

      <section aria-labelledby="signin-title" className={demo ? "mt-8 border-t border-ink-200 pt-6" : undefined}>
        <h2 id="signin-title" className="text-xl font-semibold text-ink-950">{demo ? "Sign in with an account" : "Sign in"}</h2>
        <p className="mt-1 text-sm text-ink-600">
          {signUp ? (
            <>No account yet? <Link to="/register" state={location.state} className="font-medium text-ink-900 underline underline-offset-2">Create an account</Link>.</>
          ) : (
            "Accounts are created by an administrator: sign-up is switched off on this server."
          )}
          {meta && !demo ? " The demonstration is switched off on this server." : ""}
        </p>
        <form onSubmit={submit} className="mt-4 space-y-4" noValidate>
          <Field label="E-mail address">
            {(props) => (
              <TextInput {...props} type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
            )}
          </Field>
          <Field label="Password">
            {(props) => (
              <TextInput {...props} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            )}
          </Field>
          {failure?.kind === "login" && <ErrorNote error={failure.error} />}
          <Button type="submit" variant={demo ? "secondary" : "primary"} size="lg" className="w-full" busy={busy === "login"} disabled={busy !== null || email.trim() === "" || password === ""}>
            <LogIn className="size-4" aria-hidden /> Sign in
          </Button>
        </form>
      </section>
    </AuthShell>
  );
}
