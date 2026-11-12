import { UserPlus } from "lucide-react";
import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AuthShell } from "../components/AuthShell";
import { Button, ErrorNote, Field, Notice, TextInput } from "../components/ui";
import { toApiError } from "../hooks/useAsync";
import { focusFirstInvalid } from "../lib/forms";

/** The server's rule, repeated here only to answer before the request is sent. The server remains the judge. */
const MIN_PASSWORD_LENGTH = 12;

type FieldName = "name" | "email" | "password" | "confirmation";
type Problems = Partial<Record<FieldName, string>>;

/** Which field a refusal of the server is about. Anything else is shown under the form. */
const FIELD_OF_CODE: Record<string, FieldName> = {
  EMAIL_TAKEN: "email",
  INVALID_EMAIL: "email",
  WEAK_PASSWORD: "password",
};

const LINK = "font-medium text-ink-900 underline underline-offset-2";

function sentence(text: string): string {
  const trimmed = text.trim();
  if (trimmed === "") return trimmed;
  const capitalised = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capitalised) ? capitalised : `${capitalised}.`;
}

export function RegisterPage() {
  const { status, meta, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const form = useRef<HTMLFormElement>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [problems, setProblems] = useState<Problems>({});
  const [failure, setFailure] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  const from = (location.state as { from?: string } | null)?.from;
  // Only ever return to a path of this application.
  const target = from && from.startsWith("/") && !from.startsWith("//") ? from : "/plants";
  if (status === "authenticated") return <Navigate to={target} replace />;

  function check(): Problems {
    const found: Problems = {};
    if (name.trim() === "") found.name = "Enter your name.";
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) found.email = "Enter an e-mail address, such as name@example.org.";
    if (password.length < MIN_PASSWORD_LENGTH) found.password = `The password must have at least ${MIN_PASSWORD_LENGTH} characters.`;
    if (confirmation !== password) found.confirmation = "The two passwords are not the same.";
    return found;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFailure(null);
    const found = check();
    setProblems(found);
    if (Object.keys(found).length > 0) {
      if (form.current) focusFirstInvalid(form.current);
      return;
    }
    setBusy(true);
    try {
      await register(name.trim(), email.trim(), password);
      navigate(target, { replace: true });
    } catch (cause) {
      const error = toApiError(cause);
      const field = error instanceof ApiError ? FIELD_OF_CODE[error.code] : undefined;
      if (field) {
        setProblems({ [field]: sentence(error.message) });
        if (form.current) focusFirstInvalid(form.current);
      } else {
        setFailure(error);
      }
    } finally {
      setBusy(false);
    }
  }

  // Until the server has answered, the form is shown: a server that allows sign-up is the usual case.
  const closed = meta !== null && meta.registration_open !== true;

  return (
    <AuthShell>
      <section aria-labelledby="signup-title">
        <h2 id="signup-title" className="text-xl font-semibold text-ink-950">Create an account</h2>
        {closed ? (
          <>
            <Notice tone="neutral" title="Sign-up is switched off on this server" className="mt-4">
              Accounts are created by an administrator. Ask the person who runs this server for one.
            </Notice>
            <p className="mt-4 text-sm text-ink-600">
              <Link to="/login" state={location.state} className={LINK}>Back to sign-in</Link>
            </p>
          </>
        ) : (
          <>
            <p className="mt-1 text-sm text-ink-600">
              With an account you register your own plants, import their data and run analyses. Nobody else sees them
              unless you share them.
            </p>
            <form ref={form} onSubmit={(event) => void submit(event)} className="mt-4 space-y-4" noValidate>
              <Field label="Name" error={problems.name}>
                {(props) => (
                  <TextInput {...props} autoComplete="name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
                )}
              </Field>
              <Field label="E-mail address" error={problems.email}>
                {(props) => (
                  <TextInput {...props} type="email" autoComplete="email" required maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} />
                )}
              </Field>
              <Field label="Password" hint={`At least ${MIN_PASSWORD_LENGTH} characters. A sentence of several words is a good choice.`} error={problems.password}>
                {(props) => (
                  <TextInput {...props} type="password" autoComplete="new-password" required maxLength={256} value={password} onChange={(e) => setPassword(e.target.value)} />
                )}
              </Field>
              <Field label="Password, once more" error={problems.confirmation}>
                {(props) => (
                  <TextInput {...props} type="password" autoComplete="new-password" required maxLength={256} value={confirmation} onChange={(e) => setConfirmation(e.target.value)} />
                )}
              </Field>
              {failure && <ErrorNote error={failure} />}
              <Button type="submit" variant="primary" size="lg" className="w-full" busy={busy} disabled={busy}>
                <UserPlus className="size-4" aria-hidden /> Create the account
              </Button>
            </form>
            <p className="mt-6 border-t border-ink-200 pt-4 text-sm text-ink-600">
              Already have an account? <Link to="/login" state={location.state} className={LINK}>Sign in</Link>.
            </p>
          </>
        )}
      </section>
    </AuthShell>
  );
}
