import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { setSession } from "./api/client";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { fixtures } from "./test/fixtures";
import { TOKEN, apiError, json, mockApi } from "./test/http";

const ADMIN = { ...TOKEN, user: { id: 1, email: "admin@example.org", full_name: "Administrator", role: "ADMIN", is_active: true, is_demo: false } };
const NEWCOMER = {
  ...TOKEN,
  access_token: "token-of-the-new-account",
  user: { id: 12, email: "amina@example.org", full_name: "Amina Benali", role: "ENGINEER", is_active: true, is_demo: false },
};
const PASSPHRASE = "a sentence of several words";

function open(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

const demoServer = () => ({ ...fixtures.meta(), demo_mode: true });
const closedServer = () => ({ ...fixtures.meta(), demo_mode: false });
const withoutSignUp = () => ({ ...fixtures.meta(), demo_mode: true, registration_open: false });
/** A server that predates sign-up does not mention it at all. */
const olderServer = () => {
  const meta: Partial<ReturnType<typeof fixtures.meta>> = { ...fixtures.meta(), demo_mode: true };
  delete meta.registration_open;
  return meta;
};

async function fillSignUp(values: { name?: string; email?: string; password?: string; confirmation?: string }) {
  if (values.name) await userEvent.type(await screen.findByLabelText("Name"), values.name);
  if (values.email) await userEvent.type(screen.getByLabelText("E-mail address"), values.email);
  if (values.password) await userEvent.type(screen.getByLabelText("Password"), values.password);
  if (values.confirmation) await userEvent.type(screen.getByLabelText("Password, once more"), values.confirmation);
}

describe("a visitor without a session", () => {
  it("is sent to the sign-in page, where the demonstration comes first", async () => {
    mockApi({ "GET /meta": json(demoServer()) });
    open("/plants");
    const demo = await screen.findByRole("button", { name: "Open the demonstration" });
    const signIn = screen.getByRole("button", { name: "Sign in" });
    expect(demo.compareDocumentPosition(signIn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/register");
    expect(signIn).toBeDisabled();
  });

  it.each([
    ["has switched it off", withoutSignUp],
    ["does not mention it", olderServer],
  ])("is not offered sign-up by a server that %s", async (_case, server) => {
    mockApi({ "GET /meta": json(server()) });
    open("/login");
    expect(await screen.findByText(/Accounts are created by an administrator: sign-up is switched off on this server\./)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create an account" })).not.toBeInTheDocument();
  });

  it("is not offered a demonstration the server does not run", async () => {
    mockApi({ "GET /meta": json(closedServer()) });
    open("/login");
    expect(await screen.findByText(/The demonstration is switched off on this server/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open the demonstration" })).not.toBeInTheDocument();
  });

  it("opens the demonstration without an account", async () => {
    const calls = mockApi({
      "GET /meta": json(demoServer()),
      "POST /auth/demo-login": json(TOKEN),
      "GET /plants": json([fixtures.plant()]),
    });
    open("/login");
    await userEvent.click(await screen.findByRole("button", { name: "Open the demonstration" }));

    expect(await screen.findByRole("link", { name: fixtures.plant().name })).toBeInTheDocument();
    expect(screen.getByText("Demonstration session")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Every dataset here is synthetic and every decision is simulated.");
    const plants = calls.find((call) => call.path === "/plants");
    expect(plants?.headers.authorization).toBe(`Bearer ${TOKEN.access_token}`);
    expect(plants?.headers["x-solarwise-token"]).toBe(TOKEN.access_token);
  });

  it("is told what the server answered when the session is closed right after it opened", async () => {
    mockApi({
      "GET /meta": json(demoServer()),
      "POST /auth/demo-login": json(TOKEN),
      "GET /plants": apiError(401, "NOT_AUTHENTICATED", "the access token is invalid or has expired"),
    });
    open("/login");
    await userEvent.click(await screen.findByRole("button", { name: "Open the demonstration" }));

    expect(await screen.findByText("The server closed the session")).toBeInTheDocument();
    expect(screen.getByText(/Its answer: the access token is invalid or has expired\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open the demonstration" })).toBeEnabled();
    expect(window.sessionStorage.getItem("solarwise.session")).toBeNull();
  });

  it("sees a refused sign-in next to the form, and nothing about a closed session", async () => {
    const calls = mockApi({
      "GET /meta": json(demoServer()),
      "POST /auth/login": apiError(401, "INVALID_CREDENTIALS", "e-mail address or password is incorrect"),
    });
    open("/login");
    await userEvent.type(await screen.findByLabelText("E-mail address"), " someone@example.org ");
    await userEvent.type(screen.getByLabelText("Password"), "not the password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText(/e-mail address or password is incorrect/)).toBeInTheDocument();
    expect(screen.queryByText("The server closed the session")).not.toBeInTheDocument();
    expect(calls.find((call) => call.path === "/auth/login")?.body).toEqual({ email: "someone@example.org", password: "not the password" });
  });

  it("returns to the page that was asked for once signed in", async () => {
    mockApi({
      "GET /meta": json(closedServer()),
      "POST /auth/login": json(ADMIN),
      "GET /users": json([ADMIN.user]),
    });
    open("/users");
    await userEvent.type(await screen.findByLabelText("E-mail address"), "admin@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "a long enough password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Create an account" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Accounts" })).toBeInTheDocument();
  });
});

describe("signing up", () => {
  it("creates the account, opens its session and says where the examples are", async () => {
    const calls = mockApi({
      "GET /meta": json(demoServer()),
      "POST /auth/register": json(NEWCOMER, 201),
      "GET /plants": json([]),
    });
    open("/login");
    await userEvent.click(await screen.findByRole("link", { name: "Create an account" }));
    await fillSignUp({ name: " Amina Benali ", email: " amina@example.org ", password: PASSPHRASE, confirmation: PASSPHRASE });
    await userEvent.click(screen.getByRole("button", { name: "Create the account" }));

    expect(await screen.findByText("No plant yet")).toBeInTheDocument();
    expect(screen.getByText(/The ten example scenarios are in the demonstration: sign out/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Register a plant" })).not.toHaveLength(0);
    expect(screen.getByText("Amina Benali")).toBeInTheDocument();
    expect(screen.queryByText("Demonstration session")).not.toBeInTheDocument();
    expect(calls.find((call) => call.path === "/auth/register")?.body).toEqual({
      full_name: "Amina Benali", email: "amina@example.org", password: PASSPHRASE,
    });
    const plants = calls.find((call) => call.path === "/plants");
    expect(plants?.headers.authorization).toBe("Bearer token-of-the-new-account");
    expect(plants?.headers["x-solarwise-token"]).toBe("token-of-the-new-account");
    expect(window.sessionStorage.getItem("solarwise.session")).toContain("token-of-the-new-account");
  });

  it("answers before anything is sent when the form cannot be accepted", async () => {
    const calls = mockApi({ "GET /meta": json(demoServer()) });
    open("/register");
    await userEvent.click(await screen.findByRole("button", { name: "Create the account" }));

    expect(screen.getByText("Enter your name.")).toBeInTheDocument();
    expect(screen.getByText(/Enter an e-mail address/)).toBeInTheDocument();
    expect(screen.getByText("The password must have at least 12 characters.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveFocus());

    await fillSignUp({ name: "Amina Benali", email: "amina@example.org", password: PASSPHRASE, confirmation: "another sentence of words" });
    await userEvent.click(screen.getByRole("button", { name: "Create the account" }));
    expect(screen.getByText("The two passwords are not the same.")).toBeInTheDocument();
    expect(screen.getByLabelText("Password, once more")).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText("Enter your name.")).not.toBeInTheDocument();
    expect(calls.some((call) => call.path === "/auth/register")).toBe(false);
  });

  it.each([
    ["E-mail address", 409, "EMAIL_TAKEN", "an account with this e-mail address already exists"],
    ["E-mail address", 422, "INVALID_EMAIL", "not a valid e-mail address"],
    ["Password", 422, "WEAK_PASSWORD", "the password is too repetitive"],
  ])("puts a refusal of the server next to the field it is about: %s, %i %s", async (label, status, code, message) => {
    mockApi({ "GET /meta": json(demoServer()), "POST /auth/register": apiError(status, code, message) });
    open("/register");
    await fillSignUp({ name: "Amina Benali", email: "amina@example.org", password: PASSPHRASE, confirmation: PASSPHRASE });
    await userEvent.click(screen.getByRole("button", { name: "Create the account" }));

    const field = await screen.findByLabelText(label);
    await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
    expect(field).toHaveAccessibleDescription(expect.stringContaining(`${message.charAt(0).toUpperCase()}${message.slice(1)}.`));
    expect(screen.getByRole("button", { name: "Create the account" })).toBeEnabled();
    expect(window.sessionStorage.getItem("solarwise.session")).toBeNull();
  });

  it("shows any other refusal under the form", async () => {
    mockApi({
      "GET /meta": json(demoServer()),
      "POST /auth/register": apiError(429, "TOO_MANY_REQUESTS", "too many accounts were requested from this address; try again later"),
    });
    open("/register");
    await fillSignUp({ name: "Amina Benali", email: "amina@example.org", password: PASSPHRASE, confirmation: PASSPHRASE });
    await userEvent.click(screen.getByRole("button", { name: "Create the account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("too many accounts were requested from this address");
  });

  it("says so, without a form, on a server that has switched sign-up off", async () => {
    mockApi({ "GET /meta": json(withoutSignUp()) });
    open("/register");
    expect(await screen.findByText("Sign-up is switched off on this server")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create the account" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Back to sign-in" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("leads back to the sign-in page", async () => {
    mockApi({ "GET /meta": json(demoServer()) });
    open("/register");
    await userEvent.click(await screen.findByRole("link", { name: "Sign in" }));
    expect(await screen.findByRole("button", { name: "Open the demonstration" })).toBeInTheDocument();
  });

  it("goes on to the page that was asked for before the account existed", async () => {
    mockApi({
      "GET /meta": json(demoServer()),
      "POST /auth/register": json(NEWCOMER, 201),
      "GET /reference/decision-rules": json(fixtures.decisionRules()),
    });
    open("/reference");
    await userEvent.click(await screen.findByRole("link", { name: "Create an account" }));
    await fillSignUp({ name: "Amina Benali", email: "amina@example.org", password: PASSPHRASE, confirmation: PASSPHRASE });
    await userEvent.click(screen.getByRole("button", { name: "Create the account" }));
    expect(await screen.findByRole("heading", { level: 1, name: "How SolarWise DZ decides" })).toBeInTheDocument();
  });
});

describe("a stored session", () => {
  it("is resumed when the server still accepts it", async () => {
    setSession(TOKEN.access_token, TOKEN.expires_at);
    mockApi({
      "GET /meta": json(demoServer()),
      "GET /auth/me": json(TOKEN.user),
      "GET /plants": json([fixtures.plant()]),
    });
    open("/plants");
    expect(await screen.findByRole("link", { name: fixtures.plant().name })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign in" })).not.toBeInTheDocument();
  });

  it("ends at the sign-in page when the server refuses it", async () => {
    setSession(TOKEN.access_token, TOKEN.expires_at);
    mockApi({
      "GET /meta": json(demoServer()),
      "GET /auth/me": apiError(401, "NOT_AUTHENTICATED", "the account is not active"),
    });
    open("/plants");
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByText(/Its answer: the account is not active\./)).toBeInTheDocument();
    await waitFor(() => expect(window.sessionStorage.getItem("solarwise.session")).toBeNull());
  });

  it("is forgotten on sign-out", async () => {
    setSession(TOKEN.access_token, TOKEN.expires_at);
    mockApi({
      "GET /meta": json(demoServer()),
      "GET /auth/me": json(TOKEN.user),
      "GET /plants": json([]),
    });
    open("/plants");
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Open the demonstration" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("solarwise.session")).toBeNull();
    expect(screen.queryByText("The server closed the session")).not.toBeInTheDocument();
  });
});

describe("a signed-in visitor", () => {
  it("does not see the accounts page in the menu unless administrator", async () => {
    setSession(TOKEN.access_token, TOKEN.expires_at);
    mockApi({ "GET /meta": json(demoServer()), "GET /auth/me": json(TOKEN.user), "GET /plants": json([]) });
    open("/plants");
    expect(await screen.findByRole("link", { name: "Rules and data" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Accounts" })).not.toBeInTheDocument();
  });

  it("gets a page that says so for an address that does not exist", async () => {
    setSession(TOKEN.access_token, TOKEN.expires_at);
    mockApi({ "GET /meta": json(demoServer()), "GET /auth/me": json(TOKEN.user) });
    open("/no/such/page");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(/not found|does not exist|no such page/i);
  });
});
