// A demonstration visitor walks through every page and tab, on a desktop screen and on a phone-sized one.
const { BASE, launch, expect, shot, settle, clickText, inspect, field, fill, tab, scriptError, finish } = require("./lib.cjs");

(async () => {
  const { browser, page, problems } = await launch();
  try {
    await page.goto(BASE + "/login", { waitUntil: "domcontentloaded" });
    await settle(page);
    await clickText(page, "button", "Open the demonstration");
    await page.waitForFunction(() => location.pathname === "/plants" && document.querySelector('a[href="/plants/1"]'), { timeout: 15000 });
    await inspect(page, "plants", "demo-plants");

    await page.goto(BASE + "/plants/1", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.querySelectorAll("tbody tr").length >= 10, { timeout: 15000 });
    expect(true, "the session survives a full page load (restored from the tab's storage)");
    for (const name of ["Description", "Devices", "Evidence", "Typical year"]) {
      await tab(page, name);
      await inspect(page, `plant / ${name}`, `demo-plant-${name.toLowerCase().replace(/\s+/g, "-")}`, { fullPage: true });
    }

    await page.goto(BASE + "/datasets/2", { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[role="img"] svg', { timeout: 20000 });
    await settle(page, 1200);
    const chart = await page.evaluate(() => {
      const svg = document.querySelector('[role="img"] svg');
      const r = svg.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height), marks: svg.querySelectorAll("path, rect").length };
    });
    expect(chart.w > 300 && chart.h > 150 && chart.marks > 20, `dataset: the chart is drawn (${chart.w} x ${chart.h}, ${chart.marks} marks)`);
    await inspect(page, "dataset 2", null);

    await page.goto(BASE + "/analyses/2", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("Clean now"), { timeout: 15000 });
    await inspect(page, "analysis 2 / Decision", "demo-analysis-decision", { fullPage: true });
    for (const name of ["Performance", "Attribution", "Diagnosis", "Economics", "Provenance", "Explanation"]) {
      await tab(page, name);
      await settle(page, 900);
      await inspect(page, `analysis 2 / ${name}`, `demo-analysis-${name.toLowerCase()}`, { fullPage: true });
    }
    // The report really downloads, with the session's token.
    const report = page.waitForResponse((r) => r.url().includes("/report.pdf"), { timeout: 20000 });
    await clickText(page, "button", "PDF");
    const pdf = await report;
    expect(pdf.status() === 200 && (pdf.headers()["content-type"] || "").includes("application/pdf"), `report.pdf -> ${pdf.status()} ${pdf.headers()["content-type"]}`);

    for (const id of [4, 7, 10]) {
      await page.goto(BASE + `/analyses/${id}`, { waitUntil: "domcontentloaded" });
      await page.waitForFunction(() => document.body.innerText.includes("SIMULATED DECISION"), { timeout: 15000 });
      await inspect(page, `analysis ${id} / Decision`, `demo-analysis-${id}`);
    }

    await page.goto(BASE + "/reference", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("Rules, in order"), { timeout: 15000 });
    await inspect(page, "reference / rules", "demo-reference-rules", { fullPage: true });
    await tab(page, "Data format");
    await page.waitForFunction(() => document.body.innerText.includes("Quantities"), { timeout: 15000 });
    await inspect(page, "reference / format", "demo-reference-format", { fullPage: true });
    await tab(page, "Economic references");
    await page.waitForFunction(() => document.body.innerText.includes("No price is built into"), { timeout: 15000 });
    await inspect(page, "reference / economic", "demo-reference-economic", { fullPage: true });

    await tab(page, "Cleaning cost calculator");
    await fill(page, "Low estimate, kWh", "200000");
    await fill(page, "Central estimate, kWh", "400000");
    await fill(page, "High estimate, kWh", "600000");
    await fill(page, "Benefit horizon, days", "30");
    await fill(page, "Energy value, per kWh", "5");
    await clickText(page, "button", "Calculate");
    await settle(page, 400);
    const refusal = await page.evaluate(() => ({
      invalid: document.activeElement && document.activeElement.getAttribute("aria-invalid"),
      label: (document.querySelector(`label[for="${document.activeElement.id}"]`) || {}).innerText,
    }));
    expect(refusal.invalid === "true" && /What the value represents/.test(refusal.label || ""),
      `calculator: an incomplete input is refused and the field to correct gets the focus (${JSON.stringify(refusal.label)})`);
    const basis = await field(page, "What the value represents");
    await basis.select(await basis.evaluate((select) => select.options[1].value));
    await clickText(page, "button", "Calculate");
    await page.waitForFunction(() => document.body.innerText.includes("Advisory result"), { timeout: 15000 });
    await inspect(page, "reference / calculator", "demo-reference-calculator", { fullPage: true });

    await page.goto(BASE + "/no/such/page", { waitUntil: "domcontentloaded" });
    await settle(page);
    expect(await page.evaluate(() => /not found|does not exist/i.test(document.body.innerText)), "an unknown address shows the not-found page");

    // A phone-sized screen.
    await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1 });
    for (const [route, name, wait] of [
      ["/plants", "phone / plants", "El Foulia"], ["/plants/1", "phone / plant", "Datasets"], ["/analyses/2", "phone / analysis", "Clean now"],
      ["/datasets/2", "phone / dataset", "Run an analysis"], ["/reference", "phone / reference", "Rules, in order"],
    ]) {
      await page.goto(BASE + route, { waitUntil: "domcontentloaded" });
      await page.waitForFunction((t) => document.body.innerText.includes(t), { timeout: 15000 }, wait);
      await inspect(page, name, name.replace(/\W+/g, "-"));
    }
    await clickText(page, "button", "Sign out");
    await page.waitForFunction(() => location.pathname === "/login", { timeout: 15000 });
    await inspect(page, "phone / sign-in", "phone-sign-in");
  } catch (error) {
    await scriptError(page, error);
  }
  await finish(browser, problems);
})();
