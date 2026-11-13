// An operator's own export, from the first look to the analysis of the findings:
// plant -> upload -> preview -> mapping (read from the headers, corrected by hand, reviewed by the assistant)
// -> validation (events, rejected rows) -> import -> analysis -> AI analysis -> what is kept of the file.
//
//   ADMIN=1 ./run.sh upload_flow.cjs            no language model: the deterministic fallback is what is shown
//   ADMIN=1 AI=stub ./run.sh upload_flow.cjs    with the stand-in model (scripted answers; not a language model)
const fs = require("fs");
const os = require("os");
const path = require("path");

// Every step below waits for what it needs to see, so the wait for a silent network can be short.
process.env.E2E_IDLE_TIMEOUT = process.env.E2E_IDLE_TIMEOUT || "2000";
const { ROOT, BASE, launch, expect, settle, clickText, inspect, fill, tab, scriptError, finish } = require("./lib.cjs");

const MODEL = process.env.E2E_MODEL_URL || null;
const KEY = process.env.E2E_MODEL_KEY || null;
const HEADER = ["Date", "Energy (kWh)", "Expected production (kWh)", "Irradiance (W/m2)", "Temp", "T2", "Soiling loss (%)", "Cleaning", "Alarms"];
// The JSON example offered for download on the upload page: 14 invented days, one cleaning, two alarms.
const JSON_EXAMPLE = path.join(ROOT, "data", "samples", "solarwise-operational-data.example.json");

/** 30 daily rows as a plant's own system would export them, with three bad cells, one cleaning and one open alarm. */
function operatorFile() {
  const lines = [HEADER.join(",")];
  for (let day = 1; day <= 30; day += 1) {
    const date = `2026-05-${String(day).padStart(2, "0")}`;
    let energy = "46000.0";
    if (day === 3) energy = "abc";
    if (day === 7) energy = "";
    const soiling = day === 12 ? "250" : "8.00";
    const cleaning = day === 5 ? "1" : "";
    const alarm = day >= 29 ? "Inverter fault INV-02" : "";
    lines.push([date, energy, "50000.0", "270", "44.5", "27.4", soiling, cleaning, alarm].join(","));
  }
  return lines.join("\n") + "\n";
}

async function control(mode) {
  const response = await fetch(`${MODEL}/control`, { method: "POST", body: JSON.stringify({ mode }) });
  if (!response.ok) throw new Error(`the stand-in model refused the mode ${mode}`);
}

async function requestsToModel() {
  return (await (await fetch(`${MODEL}/requests`)).json()).requests;
}

function channelRow(page, metric) {
  return page.evaluateHandle((m) => document.getElementById(`channel-${m}-title`).closest("div.px-4"), metric);
}

async function channelState(page, metric) {
  const row = (await channelRow(page, metric)).asElement();
  return row.evaluate((el) => {
    const value = (start) => {
      const label = [...el.querySelectorAll("label")].find((l) => l.textContent.trim().startsWith(start));
      return label ? document.getElementById(label.htmlFor).value : null;
    };
    return {
      column: value("Column of the file"), unit: value("Unit in the file"), holds: value("What the column holds"),
      provenance: value("Provenance"), title: el.querySelector("p").innerText.replace(/\s+/g, " ").trim(),
    };
  });
}

async function setChannel(page, metric, label, value) {
  const row = (await channelRow(page, metric)).asElement();
  const id = await row.$$eval("label", (all, start) => all.find((l) => l.textContent.trim().startsWith(start)).htmlFor, label);
  const tag = await page.$eval(`[id="${id}"]`, (el) => el.tagName);
  if (tag === "SELECT") await page.select(`[id="${id}"]`, value);
  else await page.type(`[id="${id}"]`, value);
  await settle(page, 80);
}

async function declare(page, metric, provenance, source, method) {
  await setChannel(page, metric, "Provenance", provenance);
  await setChannel(page, metric, "Source", source);
  if (method) await setChannel(page, metric, "How it was obtained", method);
}

function previewHeaders(page) {
  return page.$$eval('table[aria-label="First rows of the file"] thead th', (all) =>
    Object.fromEntries(all.slice(1).map((th) => [th.querySelector("span").innerText.trim(), th.querySelectorAll("span")[1].innerText.trim()])));
}

(async () => {
  if (!process.env.E2E_ADMIN_PASSWORD || process.env.ADMIN !== "1") {
    console.error("run this check with ADMIN=1 [AI=stub] ./run.sh upload_flow.cjs");
    process.exit(2);
  }
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "solarwise-upload-"));
  const csv = path.join(work, "may-2026-export.csv");
  fs.writeFileSync(csv, operatorFile());
  const suffix = MODEL ? "model" : "engine";

  const { browser, page, problems } = await launch();
  const answers = [];   // what the server sent, to look for the key where it must never be
  const served = [];    // downloads and other answers worth checking by address
  page.on("response", async (response) => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith("/api/")) return;
    served.push({ method: response.request().method(), path: url.pathname, status: response.status(), type: response.headers()["content-type"] || "",
                  length: Number(response.headers()["content-length"] || 0), disposition: response.headers()["content-disposition"] || "" });
    if ((response.headers()["content-type"] || "").includes("json")) answers.push(await response.text().catch(() => ""));
  });
  const last = (suffixPath, method = "GET") => [...served].reverse().find((r) => r.method === method && r.path.endsWith(suffixPath));

  try {
    // ---- sign in, describe a plant: configuration and nothing else
    await page.goto(BASE + "/login", { waitUntil: "domcontentloaded" });
    await settle(page);
    await page.type('input[type="email"]', process.env.E2E_ADMIN_EMAIL);
    await page.type('input[type="password"]', process.env.E2E_ADMIN_PASSWORD);
    await clickText(page, "button", "Sign in");
    await page.waitForFunction(() => location.pathname === "/plants", { timeout: 15000 });
    await page.goto(BASE + "/plants/new", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("Register a plant"), { timeout: 15000 });
    const formText = await page.evaluate(() => document.querySelector("main").innerText);
    const labels = await page.$$eval("main label", (all) => all.map((l) => l.innerText.trim()));
    expect(/it is uploaded as a file once the plant is registered/.test(formText) && !labels.some((l) => /energy produced|production of the day|kWh$/i.test(l)),
      "the plant form describes the plant and asks for no operational measurement");
    await fill(page, "Name", "Plant with its own export (browser check)");
    await fill(page, "Installed DC capacity, kWp", "10000");
    await fill(page, "Latitude", "33.49");
    await fill(page, "Longitude", "6.80");
    await clickText(page, "button", "Register the plant");
    await page.waitForFunction(() => /^\/plants\/\d+$/.test(location.pathname), { timeout: 15000 });
    const plantPath = await page.evaluate(() => location.pathname);
    await settle(page, 500);

    // ---- the entry point on the plant's page
    const entry = await page.evaluate(() => ({
      header: [...document.querySelectorAll("header a")].map((a) => a.innerText.trim()),
      empty: document.querySelector("main").innerText.includes("No operational data yet"),
      inEmpty: [...document.querySelectorAll("main a")].filter((a) => a.innerText.includes("Upload a CSV or JSON file")).length,
    }));
    expect(entry.header.includes("Upload operational data") && entry.empty && entry.inEmpty === 1,
      `a new plant says what comes next: "Upload operational data" in its header and in its empty list (${JSON.stringify(entry.header)})`);
    await inspect(page, "upload / plant without data", "upload-plant-empty");
    await clickText(page, "header a", "Upload operational data");
    await page.waitForFunction(() => location.pathname.endsWith("/upload") && document.body.innerText.includes("1. The file"), { timeout: 15000 });
    await settle(page, 400);

    // ---- what to upload; templates
    const intro = await page.evaluate(() => ({
      title: document.querySelector("h1").innerText,
      needed: [...document.querySelectorAll("#what-title")].length,
      text: document.querySelector("main").innerText,
      templates: [...document.querySelectorAll('ul[aria-label="Templates and examples"] button')].map((b) => b.innerText.trim()),
    }));
    expect(intro.title === "Upload operational data" && /Energy produced\s*needed/.test(intro.text) && /Cleaning events\s*optional/.test(intro.text),
      "the page says which columns a file may have and which two are needed");
    expect(JSON.stringify(intro.templates) === JSON.stringify(["CSV template", "CSV example", "JSON template", "JSON example"]),
      `templates and examples are offered in CSV and JSON: ${JSON.stringify(intro.templates)}`);
    await clickText(page, 'ul[aria-label="Templates and examples"] button', "CSV example");
    await settle(page, 500);
    const template = last("/reference/templates/solarwise-operational-data.example.csv");
    expect(Boolean(template) && template.status === 200 && template.type.startsWith("text/csv") && template.disposition.includes("attachment"),
      `the CSV example is served as a file: ${JSON.stringify(template)}`);

    // ---- step 1 and 2: the file, as it is
    await (await page.$('input[type="file"]')).uploadFile(csv);
    await page.waitForFunction(() => document.body.innerText.includes("2. What the file contains"), { timeout: 15000 });
    await settle(page, 400);
    const table = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('table[aria-label="First rows of the file"] tbody tr')];
      return { rows: rows.length, first: [...rows[0].cells].map((c) => c.innerText.trim()), third: [...rows[2].cells].map((c) => c.innerText.trim()),
               seventh: [...rows[6].cells].map((c) => c.innerText.trim()), summary: document.querySelector("#file-title").closest("section").innerText };
    });
    expect(table.rows === 12 && table.first[0] === "2" && table.first[1] === "2026-05-01" && table.third[2] === "abc" && table.seventh[2] === "empty",
      `the first 12 rows are shown as they are in the file - a wrong cell as it is, an empty cell as empty (row 4: "${table.third[2]}", row 8: "${table.seventh[2]}")`);
    expect(/CSV · 30 rows · 9 columns/.test(table.summary), "the file is summarised: format, rows, columns");
    const headers = await previewHeaders(page);
    expect(headers.Date === "Date and time" && headers["Energy (kWh)"] === "Energy produced · kWh" && headers["Expected production (kWh)"] === "Expected production · kWh"
      && headers["Irradiance (W/m2)"] === "In-plane irradiation · W/m²" && headers["Soiling loss (%)"] === "Soiling loss · %"
      && headers.Cleaning === "Cleaning marks" && headers.Alarms === "Alarms and events" && headers.T2 === "Not used",
      `the columns are recognised from their headers, with their units: ${JSON.stringify(headers)}`);
    const notes = await page.evaluate(() => [...document.querySelectorAll("#preview-title")].map((h) => h.closest("section").innerText).join(" "));
    expect(/1 cell\(s\) of 'Energy \(kWh\)' are not numbers/.test(notes) && /stored as missing, not as zero/.test(notes) && /fixed rules, no language model/.test(notes),
      "what would be rejected is announced before anything is declared, and said to come from fixed rules");

    // ---- step 3: the mapping as proposed
    const energy = await channelState(page, "actual_energy");
    const soiling = await channelState(page, "soiling_ratio");
    const irradiance = await channelState(page, "poa_irradiation");
    const ambient = await channelState(page, "ambient_temp");
    expect(energy.column === "Energy (kWh)" && energy.unit === "kWh" && /Read from the header/.test(energy.title),
      `the energy column is pre-selected and said to be read from the header (${energy.title})`);
    expect(soiling.column === "Soiling loss (%)" && soiling.unit === "percent" && soiling.holds === "LOSS",
      `a soiling loss in percent is recognised as a loss, not as a ratio: ${JSON.stringify(soiling)}`);
    expect(irradiance.unit === "w/m2" && /Check/.test(irradiance.title),
      `irradiance in W/m2 is accepted, and a header that does not name the plane is flagged to check (${irradiance.title})`);
    expect(ambient.column === "Temp" && /Check/.test(ambient.title), `an ambiguous "Temp" is proposed with a flag to check (${ambient.title})`);
    const provenances = await page.$$eval("label", (all) => all.filter((l) => l.textContent.trim().startsWith("Provenance")).map((l) => document.getElementById(l.htmlFor).value));
    expect(provenances.length >= 5 && provenances.every((p) => p === "UNKNOWN"), `no provenance is pre-selected: ${JSON.stringify(provenances)}`);

    // ---- correcting the mapping by hand: "Temp" is the module temperature on this site
    await setChannel(page, "ambient_temp", "Column of the file", "");
    await setChannel(page, "module_temp", "Column of the file", "Temp");
    const corrected = await previewHeaders(page);
    const module = await channelState(page, "module_temp");
    expect(corrected.Temp === "Module temperature · °C" && !/Read from the header/.test(module.title),
      `a correction by hand moves the column, and it is no longer called a reading of the header: ${corrected.Temp}`);

    // ---- the assistant
    const assistant = await page.evaluate(() => {
      const section = document.querySelector('section[aria-labelledby="ai-review-title"]');
      const button = [...section.querySelectorAll("button")].find((b) => b.innerText.includes("Ask the AI assistant"));
      return { text: section.innerText, disabled: button.disabled };
    });
    if (!MODEL) {
      expect(assistant.disabled && /No language model is configured on this server/.test(assistant.text) && /it is complete/.test(assistant.text),
        "without a language model the assistant is switched off, and the page says the deterministic reading is complete");
      await setChannel(page, "ambient_temp", "Column of the file", "T2");
    } else {
      expect(!assistant.disabled && /never the file/.test(assistant.text), "with a language model the assistant can be asked, and the page says what it is sent");
      await clickText(page, 'section[aria-labelledby="ai-review-title"] button', "Ask the AI assistant");
      await page.waitForFunction(() => document.body.innerText.includes("Suggestions of a language model"), { timeout: 15000 });
      await settle(page, 300);
      const review = await page.evaluate(() => {
        const section = document.querySelector('section[aria-labelledby="ai-review-title"]');
        return { text: section.innerText, items: [...section.querySelectorAll('ul[aria-label="Suggestions of the AI assistant"] li')].map((li) => li.innerText.replace(/\s+/g, " ")) };
      });
      expect(review.items.length === 1 && /Use T2 as Ambient temperature, in °C \(now: not used\)/.test(review.items[0]),
        `the assistant suggests what the reader could not place: ${JSON.stringify(review.items)}`);
      expect(/stand-in-model/.test(review.text) && /1 proposal\(s\) of the assistant were discarded by the server's checks/.test(review.text),
        "the suggestion names the model that made it, and a proposal for a column that is not in the file was discarded");
      const before = await channelState(page, "ambient_temp");
      expect(before.column === "", "nothing is applied until the suggestion is accepted");
      await clickText(page, 'ul[aria-label="Suggestions of the AI assistant"] button', "Accept");
      await settle(page, 200);
      const after = await channelState(page, "ambient_temp");
      const marked = await previewHeaders(page);
      expect(after.column === "T2" && after.unit === "degC" && /Suggested by the AI assistant, accepted by you/.test(after.title) && marked.T2 === "Ambient temperature · °C"
        && after.provenance === "UNKNOWN",
        `once accepted the column is mapped, marked as the assistant's suggestion, and still of unknown provenance (${after.title})`);
    }

    // ---- what only the uploader knows: where each column comes from
    await fill(page, "Name of the dataset", "May 2026, operator export (browser check)");
    await declare(page, "actual_energy", "MEASURED", "Revenue meter (browser check)");
    await declare(page, "expected_energy", "MODELLED", "Performance model (browser check)");
    await declare(page, "soiling_ratio", "MEASURED", "Soiling station (browser check)", "SOILING_STATION");
    const baseline = await page.evaluateHandle(() => [...document.querySelectorAll("label")].find((l) => l.textContent.trim().startsWith("How the baseline was produced")).htmlFor);
    await page.select(`[id="${await baseline.jsonValue()}"]`, "TELEMETRY_MODEL");
    for (const label of ["Adjusted to the actual irradiation?", "Adjusted to the actual temperature?", "Includes module degradation?"]) {
      const id = await page.evaluate((start) => [...document.querySelectorAll("label")].find((l) => l.textContent.trim().startsWith(start)).htmlFor, label);
      await page.select(`[id="${id}"]`, "true");
    }
    const eventsProvenance = await page.evaluate(() => [...document.querySelectorAll("label")].find((l) => l.textContent.trim().startsWith("Provenance of the events")).htmlFor);
    await page.select(`[id="${eventsProvenance}"]`, "MEASURED");
    await fill(page, "Source of the events", "SCADA event log (browser check)");
    await inspect(page, "upload / preview and mapping", `upload-mapping-${suffix}`, { fullPage: true });

    // ---- step 4: the check
    await clickText(page, "button", "Check the file");
    await page.waitForFunction(() => document.body.innerText.includes("The file can be imported") || document.body.innerText.includes("The file cannot be imported"), { timeout: 20000 });
    await settle(page, 300);
    const check = await page.evaluate(() => {
      const card = document.querySelector("#check-title").closest("section");
      const buttons = Object.fromEntries([...card.querySelectorAll("button")].map((b) => [b.innerText.trim(), b.disabled]));
      return { text: card.innerText, buttons };
    });
    expect(/The file can be imported/.test(check.text) && /30 plant · 0 device/.test(check.text), "the check accepts the file and counts its rows");
    expect(/F-CLEAN-001\s+Cleaning event/.test(check.text) && /F-EVT-002\s+Inverter fault/.test(check.text) && /still marked on the last row: not closed/.test(check.text),
      "the events of the file are listed: one cleaning, and an inverter alarm that is still open at the end of the file");
    expect(/What to do: These cells hold text where a number is expected/.test(check.text) && /converted to irradiation/.test(check.text),
      "every rejection says what to do about it, and the conversion of irradiance is stated");
    const rejectedLabel = Object.keys(check.buttons).find((label) => label.startsWith("Rejected rows (CSV)"));
    expect(rejectedLabel === "Rejected rows (CSV) · 2" && check.buttons[rejectedLabel] === false && check.buttons["Import and run the analysis"] === false,
      `two rejected cells can be downloaded, and the import is offered: ${JSON.stringify(Object.keys(check.buttons))}`);
    await clickText(page, "button", "Rejected rows (CSV)");
    await settle(page, 600);
    const rejected = last("/datasets/rejected-rows", "POST");
    expect(Boolean(rejected) && rejected.status === 200 && rejected.type.startsWith("text/csv") && rejected.disposition.includes("rejected-rows-may-2026-export.csv"),
      `the rejected rows come back as a CSV file: ${JSON.stringify(rejected)}`);
    await clickText(page, "button", "Validation report (JSON)");
    await inspect(page, "upload / validation report", `upload-check-${suffix}`, { fullPage: true });

    // ---- import, and the pipeline runs on what was uploaded
    await clickText(page, "button", "Import and run the analysis");
    await page.waitForFunction(() => /^\/analyses\/\d+$/.test(location.pathname) && document.body.innerText.includes("Gates:"), { timeout: 30000 });
    await settle(page, 500);
    const analysisPath = await page.evaluate(() => location.pathname);
    const outcome = await page.evaluate(() => {
      const text = document.querySelector("main").innerText;
      return { decision: (text.match(/\b(Clean now|Investigate|Monitor)\b/) || [])[1], simulated: /SIMULATED/.test(text),
               technical: /technical issue/.test(text), operational: /operational evaluation/.test(text) };
    });
    expect(outcome.decision === "Investigate" && outcome.technical && !outcome.simulated && outcome.operational,
      `the analysis ran on the uploaded data: measured soiling, but an open alarm of the file -> ${outcome.decision}, a technical issue first (${JSON.stringify(outcome)})`);

    // ---- the AI analysis tab
    await tab(page, "AI analysis");
    await page.waitForFunction(() => document.body.innerText.includes("AI analysis of the findings"), { timeout: 15000 });
    await settle(page, 400);
    const read = () => page.evaluate(() => {
      const panel = document.querySelector('[role="tabpanel"]');
      const generate = [...panel.querySelectorAll("button")].find((b) => /Generate/.test(b.innerText));
      return {
        text: panel.innerText,
        decision: panel.querySelector("#ai-decision-title").closest("section").innerText.replace(/\s+/g, " "),
        tags: [...panel.querySelectorAll("section")].map((s) => { const h = s.querySelector("h3"); const t = s.querySelector("h3 + span"); return h && t ? `${h.innerText}: ${t.innerText}` : null; }).filter(Boolean),
        generate: generate ? { label: generate.innerText.trim(), disabled: generate.disabled } : null,
      };
    });
    const first = await read();
    expect(/Advisory result of the engine: Investigate\./.test(first.decision) && /Engine/.test(first.decision),
      `the decision on this page is the engine's, and is marked so: ${first.decision.slice(0, 120)}`);
    expect(/Narrative assembled by the engine/.test(first.text) && first.tags.includes("GATES BEHIND THE DECISION: Engine") && first.tags.includes("SUMMARY: Engine"),
      "before anything is generated, every section is the engine's and says so");
    expect(/Equipment or inverter/.test(first.text) && /Soiling/.test(first.text) && /Evidence held by the engine/.test(first.text),
      "the possible explanations are listed with the support the engine gave them and its evidence");
    if (!MODEL) {
      expect(first.generate && first.generate.disabled && /No language model is configured on this server/.test(first.text) && /deterministic fallback is active/.test(first.text),
        "without a language model the page says the deterministic fallback is active, and nothing can be generated");
    } else {
      expect(first.generate && !first.generate.disabled && first.generate.label === "Generate the AI analysis", "with a language model the AI analysis can be generated");
      const asked = await requestsToModel();
      await clickText(page, '[role="tabpanel"] button', "Generate the AI analysis");
      await page.waitForFunction(() => document.body.innerText.includes("Narrative written by a language model"), { timeout: 20000 });
      await settle(page, 300);
      const written = await read();
      expect(/stand-in-model/.test(written.text) && /checks passed/.test(written.text) && written.tags.includes("SUMMARY: AI interpretation")
        && written.tags.includes("GATES BEHIND THE DECISION: Engine") && written.tags.includes("WHAT WOULD CHANGE THE DECISION: Engine"),
        "the narrative is marked as the AI's, with the model and the time, while gates and conditions stay marked as the engine's");
      expect(written.decision === first.decision, "the decision box is word for word what it was before the model wrote");
      expect(/Checks applied to the model's text/.test(written.text) && /Soiling not asserted without measurement/.test(written.text),
        "the checks the model's text passed are listed");
      expect((await requestsToModel()) === asked + 1, "generating called the model once");
      await inspect(page, "upload / AI analysis written by the stand-in", "ai-analysis-model", { fullPage: true });

      // A model that overreaches: soiling as a fact, a decision of its own.
      await control("rogue");
      await clickText(page, '[role="tabpanel"] button', "Generate again");
      await page.waitForFunction(() => document.body.innerText.includes("its answer was not used"), { timeout: 20000 });
      await settle(page, 300);
      const refused = await read();
      expect(/soiling_not_asserted_without_measurement|consistent_with_decision/.test(refused.text) && !/the modules are dirty/.test(refused.text)
        && /Narrative assembled by the engine/.test(refused.text) && refused.decision === first.decision,
        "an answer that states soiling as a fact and names its own decision is discarded whole: the reason is shown, not one sentence of it, and the decision has not moved");
      await inspect(page, "upload / AI answer refused", "ai-analysis-refused", { fullPage: true });

      // A provider that is down.
      await control("fail");
      await clickText(page, '[role="tabpanel"] button', "Generate the AI analysis");
      await page.waitForFunction(() => document.body.innerText.includes("HTTP 503"), { timeout: 20000 });
      await settle(page, 300);
      const down = await read();
      expect(/its answer was not used/.test(down.text) && /Narrative assembled by the engine/.test(down.text) && down.decision === first.decision,
        "when the provider is unavailable the page says so and shows the engine's text");
      await control("ok");
    }
    if (!MODEL) await inspect(page, "upload / analysis of the findings without a model", "ai-analysis-engine", { fullPage: true });

    // ---- the operational report
    await clickText(page, 'div[aria-label="Download the operational report"] button', "PDF");
    await page.waitForResponse((r) => r.url().includes("/operational-report.pdf"), { timeout: 20000 });
    await settle(page, 400);
    const report = last("/operational-report.pdf");
    expect(report.status === 200 && report.type === "application/pdf" && report.length > 20000 && report.disposition.includes("operational-report"),
      `the operational report is exported as a PDF of ${Math.round(report.length / 1024)} kB`);

    // ---- the rest of the analysis is what it was
    await tab(page, "Decision");
    const still = await page.evaluate(() => document.querySelector("main").innerText);
    expect(/Investigate/.test(still) && /Gates:/.test(still), "the Decision tab still shows the engine's result");
    if (MODEL) {
      // The rewording of the engine's explanation goes through the same provider.
      await tab(page, "Explanation");
      await clickText(page, '[role="tabpanel"] button', "Request");
      await page.waitForFunction(() => document.body.innerText.includes("Reworded by a language model"), { timeout: 20000 });
      const reworded = await page.evaluate(() => document.querySelector('[role="tabpanel"]').innerText);
      expect(/stand-in-model/.test(reworded) && /Checks applied to the model's text/.test(reworded),
        "the plain-language version of the explanation is reworded by the configured model and checked");
    }

    // ---- what is kept of the upload
    await clickText(page, "main a", "May 2026, operator export (browser check)");
    await page.waitForFunction(() => /^\/datasets\/\d+$/.test(location.pathname) && document.body.innerText.includes("What was declared about each column"), { timeout: 15000 });
    await settle(page, 500);
    const dataset = await page.evaluate(() => document.querySelector("main").innerText);
    expect(/Events that came with this dataset/.test(dataset) && /F-EVT-002/.test(dataset) && /Kept as uploaded/.test(dataset) && /byte for byte/.test(dataset),
      "the dataset keeps the events of the file and says the file is kept byte for byte");
    expect(/W\/m², converted to kWh\/m²/.test(dataset) && /Irradiance \(W\/m2\)/.test(dataset) && /MEASURED/.test(dataset) && /MODELLED/.test(dataset) && /UNKNOWN/.test(dataset),
      "each column shows the provenance that was declared for it - measured, modelled, or unknown where nothing was said");
    await clickText(page, 'div[aria-label="Download what was imported"] button', "The file as uploaded");
    await page.waitForResponse((r) => /\/datasets\/\d+\/file$/.test(new URL(r.url()).pathname), { timeout: 15000 });
    await settle(page, 300);
    const original = last("/file");
    expect(original.status === 200 && original.length === fs.statSync(csv).size && original.type === "application/octet-stream",
      `the uploaded file comes back with its exact size (${original.length} bytes)`);
    await inspect(page, "upload / dataset as kept", "upload-dataset", { fullPage: true });

    // ---- the same file again
    await page.goto(BASE + plantPath + "/upload", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("1. The file"), { timeout: 15000 });
    await (await page.$('input[type="file"]')).uploadFile(csv);
    await page.waitForFunction(() => document.body.innerText.includes("2. What the file contains"), { timeout: 15000 });
    await settle(page, 300);
    const again = await page.evaluate(() => document.querySelector("#file-title").closest("section").innerText);
    expect(/This very file was already imported for this plant/.test(again), "choosing the same file again is noticed at the first look");

    // ---- a JSON file goes the same way
    await page.goto(BASE + plantPath + "/upload", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("1. The file"), { timeout: 15000 });
    await (await page.$('input[type="file"]')).uploadFile(JSON_EXAMPLE);
    await page.waitForFunction(() => document.body.innerText.includes("2. What the file contains"), { timeout: 15000 });
    await settle(page, 300);
    const jsonLook = await page.evaluate(() => document.querySelector("#file-title").closest("section").innerText);
    const jsonHeaders = await previewHeaders(page);
    expect(/JSON · 14 rows · 12 columns/.test(jsonLook) && jsonHeaders.energy_kwh === "Energy produced · kWh"
      && jsonHeaders.poa_irradiance_w_m2 === "In-plane irradiation · W/m²" && jsonHeaders.cleaning_event === "Cleaning marks" && jsonHeaders.alarm === "Alarms and events"
      && !Object.values(jsonHeaders).includes("Not used"),
      `a JSON file of records is read like a CSV file, and every column of the example is recognised: ${JSON.stringify(Object.values(jsonHeaders))}`);
    await clickText(page, "button", "Check the file");
    await page.waitForFunction(() => document.body.innerText.includes("The file can be imported"), { timeout: 20000 });
    const jsonCheck = await page.evaluate(() => document.querySelector("#check-title").closest("section").innerText);
    expect(/14 plant · 0 device/.test(jsonCheck) && /F-CLEAN-001/.test(jsonCheck) && /F-EVT-002\s+Inverter fault/.test(jsonCheck) && /F-EVT-003\s+Grid outage/.test(jsonCheck)
      && /UNKNOWN/.test(jsonCheck) && !/MEASURED/.test(jsonCheck),
      "its check lists 14 rows and three events, and - nothing having been declared - every column is of unknown provenance");
    await clickText(page, "button", "Import the dataset");
    await page.waitForFunction(() => /^\/datasets\/\d+$/.test(location.pathname) && document.body.innerText.includes("What was declared about each column"), { timeout: 20000 });
    const jsonDataset = await page.evaluate(() => document.querySelector("main").innerText);
    expect(/solarwise-operational-data\.example\.json/.test(jsonDataset) && /Run an analysis/.test(jsonDataset) && /Events that came with this dataset/.test(jsonDataset),
      "the JSON file is imported, kept under its name, with its events, and can be analysed");

    // ---- the key of the model
    if (KEY) {
      const html = await page.content();
      expect(!html.includes(KEY) && answers.every((text) => !text.includes(KEY)) && answers.length > 20,
        `the key of the model appears in none of the ${answers.length} answers the browser received, nor in the page`);
    }
    expect(analysisPath.length > 0, `analysis kept at ${analysisPath}`);
  } catch (error) {
    await scriptError(page, error);
  }
  fs.rmSync(work, { recursive: true, force: true });
  await finish(browser, problems);
})();
