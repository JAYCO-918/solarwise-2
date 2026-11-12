// A signed-in account does the real work: registers a plant, declares and imports a file, runs an analysis,
// meets the duplicate check and manages accounts. Run with ADMIN=1.
const path = require("path");
const { ROOT, BASE, launch, expect, settle, clickText, inspect, fill, scriptError, finish } = require("./lib.cjs");

const CSV = path.join(ROOT, "data", "demo", "S02_confirmed_soiling.csv");

async function declare(page, metric, provenance, source, method) {
  const row = (await page.evaluateHandle((m) => document.getElementById(`channel-${m}-title`).closest("div.px-4"), metric)).asElement();
  const selects = await row.$$("select");
  const labels = await row.$$eval("label", (all) => all.map((l) => l.textContent.trim()));
  await selects[labels.findIndex((l) => l.startsWith("Provenance"))].select(provenance);
  await settle(page, 100);
  const sourceId = await row.$$eval("label", (all) => all.find((l) => l.textContent.trim().startsWith("Source")).htmlFor);
  await page.type(`[id="${sourceId}"]`, source);
  if (method) {
    const methodId = await row.$$eval("label", (all) => all.find((l) => l.textContent.trim().startsWith("How it was obtained")).htmlFor);
    await page.select(`[id="${methodId}"]`, method);
  }
}

async function declareAll(page) {
  await fill(page, "Name of the dataset", "Browser check - declared by form");
  await declare(page, "actual_energy", "MEASURED", "Revenue meter (browser check)");
  await declare(page, "expected_energy", "MODELLED", "Performance model (browser check)");
  await declare(page, "soiling_ratio", "MEASURED", "Soiling station (browser check)", "SOILING_STATION");
}

(async () => {
  if (!process.env.E2E_ADMIN_PASSWORD || process.env.ADMIN !== "1") {
    console.error("run this check with ADMIN=1 ./run.sh tour_admin.cjs");
    process.exit(2);
  }
  const { browser, page, problems } = await launch();
  try {
    await page.goto(BASE + "/login", { waitUntil: "domcontentloaded" });
    await settle(page);
    await page.type('input[type="email"]', process.env.E2E_ADMIN_EMAIL);
    await page.type('input[type="password"]', process.env.E2E_ADMIN_PASSWORD);
    await clickText(page, "button", "Sign in");
    await page.waitForFunction(() => location.pathname === "/plants", { timeout: 15000 });
    await settle(page, 500);
    const start = await page.evaluate(() => ({
      banner: document.body.innerText.includes("Demonstration session"),
      menu: [...document.querySelectorAll("header a, nav a")].map((a) => a.innerText.trim()).filter(Boolean),
    }));
    expect(!start.banner && start.menu.includes("Accounts"), `a real account sees no demonstration banner and has the accounts page: ${JSON.stringify(start.menu)}`);
    await inspect(page, "admin / plants", "admin-plants");

    // ---- register a plant
    await page.goto(BASE + "/plants/new", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("Register a plant"), { timeout: 15000 });
    await clickText(page, "button", "Register the plant");
    await settle(page, 300);
    const refused = await page.evaluate(() => ({
      focus: (document.querySelector(`label[for="${document.activeElement.id}"]`) || {}).innerText,
      invalid: document.querySelectorAll('[aria-invalid="true"]').length,
    }));
    expect(refused.invalid >= 3 && /^Name/.test(refused.focus || ""), `an empty plant form is refused and the first field to correct gets the focus (${JSON.stringify(refused)})`);
    await fill(page, "Name", "Test plant (browser check)");
    await fill(page, "Installed DC capacity, kWp", "300000");
    await fill(page, "Latitude", "33.49");
    await fill(page, "Longitude", "6.80");
    await clickText(page, "button", "Register the plant");
    await page.waitForFunction(() => /^\/plants\/\d+$/.test(location.pathname), { timeout: 15000 });
    const plantPath = await page.evaluate(() => location.pathname);
    expect(true, `plant registered at ${plantPath}`);
    await settle(page, 500);
    const tabs = await page.$$eval('[role="tab"]', (all) => all.map((t) => t.innerText.trim()));
    expect(tabs.some((t) => t.startsWith("Access")), `the owner sees the access tab: ${JSON.stringify(tabs)}`);
    await inspect(page, "admin / new plant", "admin-plant");

    // ---- declare and import a file with the form
    await page.goto(BASE + plantPath + "/upload", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("1. The file"), { timeout: 15000 });
    await (await page.$('input[type="file"]')).uploadFile(CSV);
    await page.waitForFunction(() => /Quantities \(\d+ assigned\)/.test(document.body.innerText), { timeout: 15000 });
    const before = await page.evaluate(() => ({
      assigned: document.body.innerText.match(/Quantities \((\d+) assigned\)/)[1],
      provenances: [...document.querySelectorAll("label")].filter((l) => l.textContent.trim().startsWith("Provenance")).map((l) => document.getElementById(l.htmlFor).value),
      synthetic: [...document.querySelectorAll("option")].some((o) => o.value === "SYNTHETIC"),
    }));
    expect(Number(before.assigned) >= 5 && before.provenances.every((p) => p === "UNKNOWN"),
      `the columns are recognised (${before.assigned} assigned) and no provenance is pre-selected (${[...new Set(before.provenances)].join(",")})`);
    expect(!before.synthetic, "the form does not offer SYNTHETIC as a provenance");
    await declareAll(page);
    await inspect(page, "admin / upload form", "admin-upload-form", { fullPage: true });
    await clickText(page, "button", "Check the file");
    await page.waitForFunction(() => /can be imported|cannot be imported|is incomplete/i.test(document.body.innerText), { timeout: 30000 });
    await settle(page, 300);
    const check = await page.evaluate(() => ({
      ok: /can be imported/i.test(document.body.innerText) && !/cannot be imported/i.test(document.body.innerText),
      alerts: [...document.querySelectorAll('[role="alert"]')].map((e) => e.innerText.slice(0, 300)),
    }));
    expect(check.ok, `the check accepts the file${check.ok ? "" : ": " + JSON.stringify(check.alerts)}`);
    await clickText(page, "button", "Import the dataset");
    await page.waitForFunction(() => /^\/datasets\/\d+$/.test(location.pathname), { timeout: 30000 });
    await page.waitForFunction(() => document.body.innerText.includes("Run an analysis"), { timeout: 15000 });
    const name = await page.evaluate(() => document.querySelector("h1").innerText.split("\n")[0]);
    expect(name === "Browser check - declared by form", `the dataset is imported under the name typed in the form: ${JSON.stringify(name)}`);
    await inspect(page, "admin / dataset", "admin-dataset");

    // ---- run an analysis without economic inputs
    await clickText(page, "button", "Run the analysis");
    await page.waitForFunction(() => /^\/analyses\/\d+$/.test(location.pathname), { timeout: 60000 });
    await page.waitForFunction(() => document.body.innerText.includes("Gates:"), { timeout: 20000 });
    const result = await page.evaluate(() => document.body.innerText);
    const decision = (result.match(/\b(Clean now|Investigate|Monitor)\b/) || [])[1];
    const gates = (result.match(/Gates: (\d+ of \d+) passed/) || [])[1];
    expect(Boolean(decision) && !result.includes("SIMULATED"), `data declared measured: decision "${decision}", gates ${gates}, not marked simulated`);
    expect(decision !== "Clean now", "without economic inputs no cleaning is ordered");
    await inspect(page, "admin / analysis", "admin-analysis", { fullPage: true });

    // ---- the same file again is recognised
    await page.goto(BASE + plantPath + "/upload", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("1. The file"), { timeout: 15000 });
    await (await page.$('input[type="file"]')).uploadFile(CSV);
    await page.waitForFunction(() => /Quantities \(\d+ assigned\)/.test(document.body.innerText), { timeout: 15000 });
    await declareAll(page);
    await clickText(page, "button", "Check the file");
    await page.waitForFunction(() => document.body.innerText.includes("Already imported"), { timeout: 30000 }).catch(() => {});
    const duplicate = await page.evaluate(() => ({
      told: document.body.innerText.includes("Already imported"),
      importDisabled: [...document.querySelectorAll("button")].find((b) => b.textContent.includes("Import the dataset")).disabled,
    }));
    expect(duplicate.told && duplicate.importDisabled, `the same file with the same declaration is recognised and cannot be imported twice (${JSON.stringify(duplicate)})`);

    // ---- accounts
    await page.goto(BASE + "/users", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("Create an account"), { timeout: 15000 });
    await fill(page, "E-mail address", "engineer.check@example.org");
    await fill(page, "Name", "Engineer Check");
    await fill(page, "Initial password", "short");
    await clickText(page, "button", "Create");
    await settle(page, 500);
    const weak = await page.evaluate(() => [...document.querySelectorAll('[role="alert"]')].map((e) => e.innerText.split("\n")[0]));
    expect(weak.some((m) => /12 characters|password/i.test(m)), `a weak password is refused with the reason: ${JSON.stringify(weak)}`);
    await fill(page, "Initial password", "A-long-enough-passphrase-42");
    await clickText(page, "button", "Create");
    await page.waitForFunction(() => document.body.innerText.includes("engineer.check@example.org"), { timeout: 15000 });
    expect(true, "the account is created and listed");
    await inspect(page, "admin / accounts", "admin-accounts", { fullPage: true });

    await clickText(page, "button", "Sign out");
    await page.waitForFunction(() => location.pathname === "/login", { timeout: 15000 });
    await page.goto(BASE + "/users", { waitUntil: "domcontentloaded" });
    await settle(page, 400);
    expect(await page.evaluate(() => location.pathname === "/login"), "after signing out, a protected page leads back to sign-in");
  } catch (error) {
    await scriptError(page, error);
  }
  // Expected here: the refusals that the check provokes on purpose (empty form, weak password, duplicate file).
  await finish(browser, problems, (p) => /status of (409|422)|\[http (409|422)\]/.test(p));
})();
