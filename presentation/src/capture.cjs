// Takes the screenshots of the application used in the slides, from a demonstration-mode server.
// Run through the browser-check runner, which starts a throw-away server:
//   frontend/e2e/run.sh "$PWD/presentation/src/capture.cjs"
const fs = require("fs");
const path = require("path");
const E2E = path.resolve(__dirname, "..", "..", "frontend", "e2e");
const puppeteer = require(require.resolve("puppeteer-core", { paths: [E2E] }));

const BASE = process.env.BASE_URL;
const OUT = process.env.CAPTURE_OUT || path.join(__dirname, "assets");
const CHROMIUM = [process.env.CHROMIUM_PATH, "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"].find((p) => p && fs.existsSync(p));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

(async () => {
  if (!BASE || !CHROMIUM) throw new Error("BASE_URL and a browser (CHROMIUM_PATH) are required");
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROMIUM, headless: "shell",
    args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--font-render-hinting=none", ...(process.env.CHROMIUM_ARGS || "").split(/\s+/).filter(Boolean)],
    defaultViewport: { width: 1200, height: 800, deviceScaleFactor: 2 },
  });
  const page = await browser.newPage();
  const settle = async (ms = 500) => { await page.waitForNetworkIdle({ idleTime: 300, timeout: 20000 }).catch(() => {}); await sleep(ms); };
  const go = async (route, text) => {
    await page.goto(BASE + route, { waitUntil: "domcontentloaded" });
    if (text) await page.waitForFunction((t) => document.body.innerText.includes(t), { timeout: 20000 }, text);
    await settle();
  };
  const tab = async (name) => {
    const handle = await page.evaluateHandle((t) => [...document.querySelectorAll('[role="tab"]')].find((el) => el.textContent.trim().startsWith(t)) || null, name);
    await handle.asElement().click();
    await settle(900);
  };
  const shot = async (name, selector) => {
    const file = path.join(OUT, `${name}.png`);
    if (selector) {
      const el = await page.$(selector);
      if (!el) throw new Error(`${name}: nothing matches ${selector}`);
      await el.screenshot({ path: file });
    } else {
      await page.screenshot({ path: file });
    }
    console.log("captured", name);
  };

  await go("/login", "Open the demonstration");
  await shot("login");
  await page.evaluate(() => [...document.querySelectorAll("button")].find((b) => b.textContent.includes("Open the demonstration")).click());
  await page.waitForFunction(() => location.pathname === "/plants" && document.querySelector('a[href="/plants/1"]'), { timeout: 20000 });
  await settle();
  await shot("plants");

  await go("/plants/1", "Datasets");
  await page.waitForFunction(() => document.querySelectorAll("tbody tr").length >= 10, { timeout: 20000 });
  await settle();
  await shot("plant");
  await page.screenshot({ path: path.join(OUT, "plant-full.png"), fullPage: true });

  // Analysis ids follow the scenario numbers on a fresh demonstration database.
  for (const [id, key, word] of [[2, "s02", "Clean now"], [4, "s04", "Investigate"], [10, "s10", "Monitor"], [5, "s05", "Investigate"]]) {
    await go(`/analyses/${id}`, word);
    await page.waitForFunction(() => document.body.innerText.includes("Gates:"), { timeout: 20000 });
    await settle();
    if (key === "s02") await shot("analysis-s02-top");
    await shot(`decision-${key}`, 'section[aria-labelledby="decision-title"]');
    await shot(`gates-${key}`, 'section[aria-labelledby="gates-title"]');
  }

  await go("/analyses/2", "Clean now");
  for (const [name, key] of [["Performance", "performance"], ["Attribution", "attribution"], ["Diagnosis", "diagnosis"], ["Economics", "economics"], ["Provenance", "provenance"], ["Explanation", "explanation"]]) {
    await tab(name);
    if (["performance", "attribution", "economics"].includes(key)) await page.waitForSelector('[role="tabpanel"] [role="img"] svg', { timeout: 20000 }).catch(() => {});
    await settle(1200);
    await page.screenshot({ path: path.join(OUT, `tab-${key}.png`), fullPage: true });
    console.log("captured", `tab-${key}`);
  }

  await go("/reference", "Rules, in order");
  await page.screenshot({ path: path.join(OUT, "reference-rules.png"), fullPage: true });
  console.log("captured reference-rules");

  await browser.close();
})().catch((error) => { console.error(error); process.exit(1); });
