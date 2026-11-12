// Shared by the browser checks: starting the browser, finding things on a page, recording what holds and what does not.
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");

const ROOT = path.resolve(__dirname, "..", "..");
const BASE = process.env.BASE_URL;
const SHOTS = process.env.E2E_SHOTS || path.join(__dirname, "shots");
if (!BASE) {
  console.error("BASE_URL is not set: start the checks with ./run.sh <script>, which also starts the server.");
  process.exit(2);
}
fs.mkdirSync(SHOTS, { recursive: true });

function chromiumPath() {
  const candidates = [
    process.env.CHROMIUM_PATH,
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].filter(Boolean);
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) throw new Error("no browser found: set CHROMIUM_PATH to a Chromium or Chrome executable");
  return found;
}

async function launch(viewport = { width: 1360, height: 900 }) {
  const extra = (process.env.CHROMIUM_ARGS || "").split(/\s+/).filter(Boolean);
  const browser = await puppeteer.launch({
    executablePath: chromiumPath(),
    headless: "shell",
    args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--font-render-hinting=none", ...extra],
    defaultViewport: viewport,
  });
  const page = await browser.newPage();
  // Everything a visitor would not see but that means something is wrong.
  const problems = [];
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) problems.push(`[console.${m.type()}] ${m.text()}`); });
  page.on("pageerror", (e) => problems.push(`[pageerror] ${e.message}`));
  page.on("requestfailed", (r) => problems.push(`[requestfailed] ${r.url()} ${r.failure()?.errorText}`));
  page.on("response", (r) => { if (r.status() >= 400) problems.push(`[http ${r.status()}] ${r.request().method()} ${r.url()}`); });
  return { browser, page, problems };
}

const failures = [];
const notes = [];

function expect(ok, what) {
  console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
  if (!ok) failures.push(what);
  return ok;
}

function shot(name) {
  return path.join(SHOTS, `${name}.png`);
}

async function settle(page, ms = 350) {
  await page.waitForNetworkIdle({ idleTime: 250, timeout: 15000 }).catch(() => {});
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function clickText(page, selector, text) {
  const handle = await page.evaluateHandle(
    (sel, t) => [...document.querySelectorAll(sel)].find((el) => el.textContent.trim().includes(t)) || null, selector, text);
  const el = handle.asElement();
  if (!el) throw new Error(`no ${selector} with text "${text}"`);
  await el.click();
}

/** Things that are wrong on any page: a layout wider than the window, raw values leaking into the text. */
async function inspect(page, name, shotName, { fullPage = false } = {}) {
  await settle(page, 350);
  const info = await page.evaluate(() => {
    // "JSON null" is the one place where the word belongs: the sentence that explains how a missing value is written.
    const text = document.body.innerText.replace(/\bJSON null\b/g, "");
    const leaks = text.match(/\bNaN\b|\bundefined\b|\[object Object\]|Invalid Date|\bnull\b/g) || [];
    const wide = [...document.querySelectorAll("body *")]
      .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1 && !el.closest(".overflow-x-auto, table"))
      .slice(0, 3).map((el) => `${el.tagName}.${String(el.className).slice(0, 40)}`);
    return {
      overflow: document.documentElement.scrollWidth - window.innerWidth,
      leaks: [...new Set(leaks)],
      wide,
      alerts: [...document.querySelectorAll('[role="alert"]')].map((e) => e.innerText.slice(0, 120)),
    };
  });
  expect(info.overflow <= 1, `${name}: no horizontal overflow${info.overflow > 1 ? ` (${info.overflow}px; ${info.wide.join(", ")})` : ""}`);
  expect(info.leaks.length === 0, `${name}: no raw values in the text${info.leaks.length ? ` (${info.leaks.join(", ")})` : ""}`);
  if (info.alerts.length) notes.push(`${name}: alert shown: ${JSON.stringify(info.alerts)}`);
  if (shotName) await page.screenshot({ path: shot(shotName), fullPage });
  return info;
}

async function field(page, label) {
  const handle = await page.evaluateHandle((text) => {
    const found = [...document.querySelectorAll("label")].find((l) => l.textContent.trim().startsWith(text));
    return found ? document.getElementById(found.htmlFor) : null;
  }, label);
  const el = handle.asElement();
  if (!el) throw new Error(`no field labelled "${label}"`);
  return el;
}

async function fill(page, label, value) {
  const el = await field(page, label);
  await el.focus();
  await el.evaluate((input) => input.select());
  await page.keyboard.press("Backspace");
  await el.type(String(value));
}

async function choose(page, label, optionText) {
  const el = await field(page, label);
  const value = await el.evaluate(
    (select, t) => { const o = [...select.options].find((x) => x.textContent.trim().startsWith(t)); return o ? o.value : null; }, optionText);
  if (value === null) throw new Error(`no option "${optionText}" in "${label}"`);
  await el.select(value);
}

async function tab(page, text) {
  const handle = await page.evaluateHandle(
    (t) => [...document.querySelectorAll('[role="tab"]')].find((el) => el.textContent.trim().startsWith(t)) || null, text);
  const el = handle.asElement();
  if (!el) throw new Error(`no tab "${text}"`);
  await el.click();
  await settle(page, 300);
}

async function scriptError(page, error) {
  expect(false, `script error: ${String(error.message).split("\n")[0]}`);
  await page.screenshot({ path: shot("failed"), fullPage: true }).catch(() => {});
}

/** Close the browser and exit: 0 only if every expectation held and the browser reported nothing unexpected. */
async function finish(browser, problems, allowed = () => false) {
  // A request cancelled because its page was left is not a failure.
  const unexpected = problems.filter((p) => !allowed(p) && !p.includes("net::ERR_ABORTED"));
  expect(unexpected.length === 0, `no unexpected browser errors or failed requests${unexpected.length ? ":\n     " + unexpected.join("\n     ") : ""}`);
  for (const note of notes) console.log("note", note);
  console.log(failures.length ? `\n${failures.length} FAILED` : "\nall passed");
  await browser.close();
  process.exit(failures.length ? 1 : 0);
}

module.exports = { ROOT, BASE, launch, expect, shot, settle, clickText, inspect, field, fill, choose, tab, scriptError, finish };
