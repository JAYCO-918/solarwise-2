// A first visit from beginning to end, as it is shown to an audience:
// the demonstration answers "Clean now" for scenario 02; the visitor signs out and creates an account, which starts
// on its own empty list of plants and not on the page of the demonstration that was left; the account registers a
// plant, adds the file of scenario 02 with its declaration file, and runs the analysis. On an ordinary plant the same
// numbers give "Investigate": data declared synthetic cannot support a cleaning decision. The report downloads.
const path = require("path");
const { ROOT, BASE, launch, expect, settle, clickText, inspect, fill, scriptError, finish } = require("./lib.cjs");

const CSV = path.join(ROOT, "data", "demo", "S02_confirmed_soiling.csv");
const DECLARATION = path.join(ROOT, "data", "demo", "S02_confirmed_soiling.metadata.json");
const PASSWORD = "a sentence of several words 42";

function summary(text) {
  return {
    decision: (text.match(/\b(Clean now|Investigate|Monitor)\b/) || [])[1],
    gates: (text.match(/Gates: (\d+ of \d+) passed/) || [])[1],
    simulated: text.includes("SIMULATED"),
  };
}

(async () => {
  const { browser, page, problems } = await launch();
  const requested = [];
  page.on("request", (r) => { if (r.url().includes("/api/")) requested.push(`${r.method()} ${new URL(r.url()).pathname}`); });
  try {
    // ---- the demonstration: scenario 02
    await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
    await settle(page);
    await clickText(page, "button", "Open the demonstration");
    await page.waitForFunction(() => location.pathname === "/plants" && document.querySelector('a[href="/plants/1"]'), { timeout: 15000 });
    await page.click('a[href="/plants/1"]');
    await page.waitForFunction(() => document.querySelectorAll("tbody tr").length >= 10, { timeout: 15000 });
    await settle(page, 300);
    const link = (await page.evaluateHandle(() => {
      const row = [...document.querySelectorAll("tbody tr")].find((tr) => tr.innerText.includes("02 · Confirmed soiling"));
      return row ? [...row.querySelectorAll("a")].find((a) => /^\/analyses\/\d+$/.test(a.getAttribute("href"))) || null : null;
    })).asElement();
    expect(Boolean(link), "the plant of the demonstration lists scenario 02 with a link to its analysis");
    await link.click();
    await page.waitForFunction(() => /^\/analyses\/\d+$/.test(location.pathname) && document.body.innerText.includes("Gates:"), { timeout: 15000 });
    await settle(page, 300);
    const left = await page.evaluate(() => location.pathname);
    const demo = summary(await page.evaluate(() => document.querySelector("main").innerText));
    expect(demo.decision === "Clean now" && demo.gates === "10 of 10" && demo.simulated,
      `in the demonstration, scenario 02 answers "${demo.decision}" with ${demo.gates} gates, marked simulated: ${demo.simulated}`);

    // ---- sign out, create an account
    await clickText(page, "button", "Sign out");
    await page.waitForFunction(() => location.pathname === "/login", { timeout: 15000 });
    await settle(page, 300);
    await page.click('main a[href="/register"]');
    await page.waitForFunction(() => location.pathname === "/register", { timeout: 15000 });
    await settle(page, 300);
    await fill(page, "Name", "Nadia Cherif");
    await fill(page, "E-mail address", "nadia.cherif@example.org");
    await fill(page, "Password", PASSWORD);
    await fill(page, "Password, once more", PASSWORD);
    const before = requested.length;
    await clickText(page, "button", "Create the account");
    await page.waitForFunction(() => location.pathname !== "/register", { timeout: 15000 });
    await settle(page, 500);
    const start = await page.evaluate(() => ({ path: location.pathname, text: document.querySelector("main").innerText }));
    expect(start.path === "/plants" && start.text.includes("No plant yet"),
      `after a sign-out on ${left}, the new account starts on its own plants: ${start.path}`);
    const again = requested.slice(before).filter((r) => r.endsWith(left));
    expect(again.length === 0, `the page that was left is not asked for with the new account${again.length ? ": " + again.join(", ") : ""}`);

    // ---- a plant of its own
    await clickText(page, "a", "Register a plant");
    await page.waitForFunction(() => location.pathname === "/plants/new", { timeout: 15000 });
    await settle(page, 300);
    await fill(page, "Name", "Plant of a first visit (browser check)");
    await fill(page, "Installed DC capacity, kWp", "300000");
    await fill(page, "Latitude", "33.49");
    await fill(page, "Longitude", "6.80");
    await clickText(page, "button", "Register the plant");
    await page.waitForFunction(() => /^\/plants\/\d+$/.test(location.pathname), { timeout: 15000 });
    await settle(page, 500);
    const tabs = await page.$$eval('[role="tab"]', (all) => all.map((t) => t.innerText.trim()));
    expect(tabs.some((t) => t.startsWith("Access")), `it registers a plant and owns it: ${JSON.stringify(tabs)}`);

    // ---- the file of scenario 02, declared by its declaration file
    await clickText(page, "a", "Upload operational data");
    await page.waitForFunction(() => document.body.innerText.includes("1. The file"), { timeout: 15000 });
    await (await page.$('input[type="file"]')).uploadFile(CSV);
    await page.waitForFunction(() => document.body.innerText.includes("3. What each column is"), { timeout: 15000 });
    await settle(page, 300);
    const hasField = () => page.evaluate(() => [...document.querySelectorAll("label")].some((l) => l.textContent.trim().startsWith("Declaration file")));
    const offered = await page.$$eval('input[name="declaration-mode"]', (all) => all.map((i) => i.closest("label").innerText.trim()));
    const fieldBefore = await hasField();
    await clickText(page, "label", "Use a declaration file (JSON)");
    await page.waitForFunction(() => [...document.querySelectorAll("label")].some((l) => l.textContent.trim().startsWith("Declaration file")), { timeout: 5000 });
    expect(offered.includes("Use a declaration file (JSON)") && !fieldBefore,
      `the declaration can be given as a file, once that way is chosen: ${JSON.stringify(offered)}`);
    await (await page.$$('input[type="file"]'))[1].uploadFile(DECLARATION);
    await page.waitForFunction(() => /channels declared/.test(document.body.innerText), { timeout: 10000 });
    const declared = await page.evaluate(() => (document.body.innerText.match(/[^\n]*channels declared[^\n]*/) || [""])[0].trim());
    expect(/10 channels declared · declared synthetic/.test(declared), `the declaration file is read: ${declared}`);
    await inspect(page, "first visit / declaration file", "first-use-upload", { fullPage: true });
    await clickText(page, "button", "Check the file");
    await page.waitForFunction(() => /can be imported|cannot be imported|is incomplete/i.test(document.body.innerText), { timeout: 30000 });
    await settle(page, 300);
    const check = await page.evaluate(() => ({
      ok: document.body.innerText.includes("The file can be imported"),
      alerts: [...document.querySelectorAll('[role="alert"]')].map((e) => e.innerText.slice(0, 300)),
    }));
    expect(check.ok, `the check accepts the file${check.ok ? "" : ": " + JSON.stringify(check.alerts)}`);
    await clickText(page, "button", "Import the dataset");
    await page.waitForFunction(() => /^\/datasets\/\d+$/.test(location.pathname), { timeout: 30000 });
    await page.waitForFunction(() => document.body.innerText.includes("Run an analysis"), { timeout: 15000 });
    await settle(page, 500);
    const dataset = await page.evaluate(() => ({ name: document.querySelector("h1").innerText.split("\n")[0], synthetic: document.querySelector("main").innerText.includes("Synthetic dataset") }));
    expect(dataset.name === "Demo scenario - Confirmed soiling" && dataset.synthetic,
      `the dataset is imported under the name of its declaration and shown as synthetic: ${JSON.stringify(dataset)}`);

    // ---- the analysis: the same numbers, on an ordinary plant
    await clickText(page, "button", "Run the analysis");
    await page.waitForFunction(() => /^\/analyses\/\d+$/.test(location.pathname), { timeout: 60000 });
    await page.waitForFunction(() => document.body.innerText.includes("Gates:"), { timeout: 20000 });
    await settle(page, 500);
    const text = await page.evaluate(() => document.querySelector("main").innerText);
    const own = summary(text);
    expect(own.decision === "Investigate" && own.gates === "4 of 10" && !own.simulated,
      `on a plant of the account the same file answers "${own.decision}" with ${own.gates} gates, as an operational evaluation (simulated: ${own.simulated})`);
    expect(text.includes("Investigate: the production data are not measured data and cannot support a cleaning decision.")
      && text.includes("No operational authorisation."), "the page says why, and that no cleaning is authorised");
    await inspect(page, "first visit / analysis", "first-use-analysis", { fullPage: true });

    // ---- the report
    const report = page.waitForResponse((r) => r.url().includes("/report.pdf"), { timeout: 20000 });
    await clickText(page, "button", "PDF");
    const pdf = await report;
    const size = Number(pdf.headers()["content-length"] || 0);
    expect(pdf.status() === 200 && (pdf.headers()["content-type"] || "").includes("application/pdf") && size > 10000,
      `report.pdf -> ${pdf.status()} ${pdf.headers()["content-type"]}, ${Math.round(size / 1024)} kB`);
    await settle(page, 300);
  } catch (error) {
    await scriptError(page, error);
  }
  await finish(browser, problems);
})();
