// Creating an account from the sign-in page, as a visitor does it:
// the link is on the sign-in page; a form that cannot be accepted is answered before anything is sent; the account is
// created and its session opens at once; the account works (it registers a plant); its password opens the next
// session; an address that is taken is refused next to the field. Run behind PROXY=strip it also shows that the new
// session survives a gateway that removes the Authorization header.
const fs = require("fs");
const { BASE, launch, expect, settle, clickText, inspect, field, fill, scriptError, finish } = require("./lib.cjs");

const NAME = "Amina Benali";
const EMAIL = "amina.benali@example.org";
const PASSWORD = "a sentence of several words 42";

async function invalidFields(page) {
  return page.evaluate(() => [...document.querySelectorAll('[aria-invalid="true"]')].map((input) => ({
    label: (document.querySelector(`label[for="${input.id}"]`) || {}).innerText,
    message: (input.getAttribute("aria-describedby") || "").split(" ")
      .map((id) => (document.getElementById(id) || {}).innerText || "").filter((text) => text && !text.startsWith("At least")).join(" "),
  })));
}

(async () => {
  const { browser, page, problems } = await launch();
  const calls = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/")) {
      calls.push({ request: r, method: r.method(), path: new URL(r.url()).pathname, authorization: "authorization" in r.headers(), own: "x-solarwise-token" in r.headers() });
    }
  });
  page.on("response", (r) => { const call = calls.find((c) => c.request === r.request()); if (call) call.status = r.status(); });
  const registrations = () => calls.filter((c) => c.path === "/api/v1/auth/register");
  try {
    // ---- the way in is on the sign-in page
    await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
    await settle(page);
    const link = await page.$('main a[href="/register"]');
    expect(Boolean(link), "the sign-in page offers to create an account");
    await link.click();
    await page.waitForFunction(() => location.pathname === "/register", { timeout: 15000 });
    await settle(page, 300);
    const labels = await page.$$eval("main form label", (all) => all.map((l) => l.innerText.trim()));
    expect(JSON.stringify(labels) === JSON.stringify(["Name", "E-mail address", "Password", "Password, once more"]),
      `the form asks for a name, an address and the password twice - and no role: ${JSON.stringify(labels)}`);
    await inspect(page, "sign-up", "sign-up");

    // ---- a form that cannot be accepted is answered before anything is sent
    await clickText(page, "button", "Create the account");
    await settle(page, 300);
    const empty = await invalidFields(page);
    const focus = await page.evaluate(() => (document.querySelector(`label[for="${document.activeElement.id}"]`) || {}).innerText);
    expect(empty.length === 3 && focus === "Name" && registrations().length === 0,
      `an empty form is refused without a request, and the first field to correct gets the focus (${empty.map((f) => f.label).join(", ")}; focus on ${focus})`);
    await fill(page, "Name", NAME);
    await fill(page, "E-mail address", EMAIL);
    await fill(page, "Password", "too short");
    await (await field(page, "Password, once more")).type("something else");
    await clickText(page, "button", "Create the account");
    await settle(page, 300);
    const weak = await invalidFields(page);
    expect(weak.length === 2 && /12 characters/.test(weak[0].message) && /not the same/.test(weak[1].message) && registrations().length === 0,
      `a short password and a different confirmation are explained next to their fields: ${JSON.stringify(weak)}`);
    await inspect(page, "sign-up refused", "sign-up-refused");

    // ---- the account is created and its session opens at once
    await fill(page, "Password", PASSWORD);
    await fill(page, "Password, once more", PASSWORD);
    await clickText(page, "button", "Create the account");
    await page.waitForFunction(() => location.pathname === "/plants" && document.body.innerText.includes("No plant yet"), { timeout: 15000 });
    await settle(page, 300);
    const created = registrations().pop();
    expect(Boolean(created) && created.status === 201, `POST /auth/register -> ${created && created.status}`);
    const plants = calls.filter((c) => c.path === "/api/v1/plants" && c.method === "GET").pop();
    expect(Boolean(plants) && plants.status === 200 && plants.authorization && plants.own,
      `the new session is accepted at once: GET /plants -> ${plants && plants.status}; Authorization sent: ${plants && plants.authorization}; X-SolarWise-Token sent: ${plants && plants.own}`);
    const start = await page.evaluate(() => ({
      text: document.body.innerText,
      menu: [...document.querySelectorAll("header a, nav a")].map((a) => a.innerText.trim()).filter(Boolean),
    }));
    expect(start.text.includes(NAME) && start.text.includes("Engineer") && !start.text.includes("Demonstration session") && !start.menu.includes("Accounts"),
      `it is an engineer account, not a demonstration session and not an administrator: menu ${JSON.stringify(start.menu)}`);
    expect(start.text.includes("The ten example scenarios are in the demonstration"), "an empty list says where the examples are");
    await inspect(page, "sign-up / first page", "sign-up-plants");

    // ---- the account works
    await clickText(page, "a", "Register a plant");
    await page.waitForFunction(() => location.pathname === "/plants/new", { timeout: 15000 });
    await settle(page, 300);
    const formText = await page.evaluate(() => document.querySelector("main").innerText);
    expect(!/is a demonstration plant/.test(formText), "the plant it registers is not a demonstration plant");
    await fill(page, "Name", "Plant of a new account (browser check)");
    await fill(page, "Installed DC capacity, kWp", "12000");
    await fill(page, "Latitude", "33.49");
    await fill(page, "Longitude", "6.80");
    await clickText(page, "button", "Register the plant");
    await page.waitForFunction(() => /^\/plants\/\d+$/.test(location.pathname), { timeout: 15000 });
    await settle(page, 500);
    const tabs = await page.$$eval('[role="tab"]', (all) => all.map((t) => t.innerText.trim()));
    expect(tabs.some((t) => t.startsWith("Access")), `it registers a plant and owns it: ${JSON.stringify(tabs)}`);

    // ---- its password opens the next session
    await clickText(page, "button", "Sign out");
    await page.waitForFunction(() => location.pathname === "/login", { timeout: 15000 });
    await settle(page, 300);
    await page.type('input[type="email"]', EMAIL);
    await page.type('input[type="password"]', PASSWORD);
    await clickText(page, "button", "Sign in");
    // A sign-out leaves no page to return to: the session opens on the list of plants, which now has the plant.
    await page.waitForFunction(() => location.pathname === "/plants" && document.body.innerText.includes("Plant of a new account"), { timeout: 15000 });
    expect(true, "after signing out, the address and the password open the session again, on its list of plants with the plant it registered");

    // ---- an address that is taken is refused next to the field
    await clickText(page, "button", "Sign out");
    await page.waitForFunction(() => location.pathname === "/login", { timeout: 15000 });
    await page.goto(BASE + "/register", { waitUntil: "domcontentloaded" });
    await settle(page, 300);
    await fill(page, "Name", "Somebody else");
    await fill(page, "E-mail address", EMAIL.toUpperCase());
    await fill(page, "Password", "another sentence of words 77");
    await fill(page, "Password, once more", "another sentence of words 77");
    await clickText(page, "button", "Create the account");
    await page.waitForFunction(() => document.querySelector('[aria-invalid="true"]'), { timeout: 15000 });
    await settle(page, 300);
    const taken = await invalidFields(page);
    const refusal = registrations().pop();
    expect(taken.length === 1 && taken[0].label === "E-mail address" && /already exists/.test(taken[0].message) && refusal.status === 409
      && await page.evaluate(() => location.pathname === "/register"),
      `an address that is already registered is refused next to the field (${refusal.status}): ${JSON.stringify(taken)}`);
    await inspect(page, "sign-up / address taken", "sign-up-taken");
  } catch (error) {
    await scriptError(page, error);
  }

  const log = fs.readFileSync(process.env.SERVER_LOG, "utf8");
  expect(!log.includes(PASSWORD) && !log.includes("too short"), "no password appears in the server log");
  const warned = log.includes("because its Authorization header was");
  if (process.env.PROXY) expect(warned, "the server tells the operator that something removes or replaces the Authorization header");
  else expect(!warned, "no such warning on a direct connection");
  // Expected here: the refusal that the check provokes on purpose (the address that is taken).
  await finish(browser, problems, (p) => p.includes("/api/v1/auth/register") || p.includes("status of 409"));
})();
