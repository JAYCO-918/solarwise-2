// Builds the presentation files from deck.html.
//
//   node presentation/src/build.cjs            everything (pictures, PDF, single-file HTML, data for the PowerPoint file)
//   node presentation/src/build.cjs --preview  pictures of the slides only (quick, while editing)
//
// Needs a Chromium or Chrome (CHROMIUM_PATH) and puppeteer-core, taken from frontend/e2e/node_modules.
const fs = require("fs");
const path = require("path");

const SRC = __dirname;
const OUT = path.resolve(SRC, "..");
const WORK = path.join(OUT, ".work");
const E2E = path.resolve(OUT, "..", "frontend", "e2e");
const puppeteer = require(require.resolve("puppeteer-core", { paths: [E2E] }));
const NAME = "SolarWise-DZ-pitch";
const PREVIEW = process.argv.includes("--preview");

// Characters of the Latin subset of the font: anything else would be drawn with another font.
const ALLOWED = /^[\u0020-\u007e\u00a0-\u00ff\u0131\u0152\u0153\u02c6\u02da\u02dc\u2000-\u206f\u20ac\u2122\u2191\u2193\u2212\u2215]*$/;

function chromium() {
  const found = [process.env.CHROMIUM_PATH, "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].find((p) => p && fs.existsSync(p));
  if (!found) throw new Error("no browser found: set CHROMIUM_PATH to a Chromium or Chrome executable");
  return found;
}

function assemble() {
  const icons = fs.readFileSync(path.join(SRC, "icons.svg"), "utf8");
  const html = fs.readFileSync(path.join(SRC, "deck.html"), "utf8");
  if (!html.includes("<!--ICONS-->")) throw new Error("deck.html has no <!--ICONS--> marker");
  return html.replace("<!--ICONS-->", icons);
}

const dataUri = (file, mime) => `data:${mime};base64,${fs.readFileSync(file).toString("base64")}`;

function singleFile(html) {
  let css = fs.readFileSync(path.join(SRC, "deck.css"), "utf8");
  css = css.replace(/url\("(fonts\/[^"]+\.woff2)"\)/g, (_, file) => `url("${dataUri(path.join(SRC, file), "font/woff2")}")`);
  const js = fs.readFileSync(path.join(SRC, "deck.js"), "utf8");
  let out = html.replace('<link rel="stylesheet" href="deck.css">', () => `<style>\n${css}\n</style>`);
  out = out.replace(/src="(assets\/[^"]+\.png)"/g, (_, file) => `src="${dataUri(path.join(SRC, file), "image/png")}"`);
  out = out.replace('<script src="deck.js"></script>', () => `<script>\n${js}\n</script>`);
  if (/(src|href)="(assets|fonts)\//.test(out) || out.includes("deck.css") || out.includes('src="deck.js"')) throw new Error("the single-file deck still refers to other files");
  return out;
}

// Runs in the page: what each slide says, where its editable texts are, and what is wrong with them.
function extractInPage(allowedSource) {
  const allowed = new RegExp(allowedSource);
  const hex = (color) => {
    const m = /^rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)$/.exec(color);
    if (!m) throw new Error(`unexpected colour ${color}`);
    if (m[4] !== undefined && Number(m[4]) !== 1) throw new Error(`text colour with transparency: ${color}`);
    return [m[1], m[2], m[3]].map((v) => Number(v).toString(16).padStart(2, "0")).join("").toUpperCase();
  };
  const problems = [];
  const slides = [...document.querySelectorAll(".slide")].map((slide, index) => {
    const origin = slide.getBoundingClientRect();
    const label = `slide ${index + 1}`;
    const boxes = [];
    for (const el of slide.querySelectorAll("[data-tx]")) {
      const cs = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const runs = [];
      const walk = (node, style) => {
        for (const child of node.childNodes) {
          if (child.nodeType === Node.TEXT_NODE) {
            let text = child.textContent.replace(/\s+/g, " ");
            if (style.textTransform === "uppercase") text = text.toUpperCase();
            if (text === "") continue;
            runs.push({
              text, size: parseFloat(style.fontSize), bold: parseInt(style.fontWeight, 10) >= 600, italic: style.fontStyle === "italic",
              color: hex(style.color), spacing: style.letterSpacing === "normal" ? 0 : parseFloat(style.letterSpacing),
            });
          } else if (child.nodeType === Node.ELEMENT_NODE) {
            if (child.tagName === "BR") runs.push({ br: true });
            else walk(child, getComputedStyle(child));
          }
        }
      };
      walk(el, cs);
      // Spaces at the start, at the end and around a forced line break are layout, not text.
      const clean = [];
      for (let i = 0; i < runs.length; i += 1) {
        const run = { ...runs[i] };
        if (!run.br) {
          const previous = clean[clean.length - 1];
          if (!previous || previous.br) run.text = run.text.replace(/^ +/, "");
          const next = runs[i + 1];
          if (!next || next.br) run.text = run.text.replace(/ +$/, "");
          if (run.text === "") continue;
        }
        clean.push(run);
      }
      const text = clean.map((run) => (run.br ? "\n" : run.text)).join("");
      const padding = ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft"].some((side) => parseFloat(cs[side]) !== 0);
      if (padding) problems.push(`${label}: “${text.slice(0, 40)}” has padding; an editable text must not`);
      if (!allowed.test(text.replace(/\n/g, ""))) problems.push(`${label}: “${text.slice(0, 40)}” uses a character outside the font's Latin subset`);
      if (cs.lineHeight === "normal") problems.push(`${label}: “${text.slice(0, 40)}” has no explicit line-height`);
      if (rect.left < origin.left - 0.5 || rect.right > origin.right + 0.5 || rect.top < origin.top - 0.5 || rect.bottom > origin.bottom + 0.5) {
        problems.push(`${label}: “${text.slice(0, 40)}” leaves the slide`);
      }
      // Width the text really takes: wider than its element means it overflows.
      const range = document.createRange();
      range.selectNodeContents(el);
      const ink = range.getBoundingClientRect();
      if (ink.width > rect.width + 1 && cs.display !== "inline") problems.push(`${label}: “${text.slice(0, 40)}” is ${Math.round(ink.width - rect.width)} px wider than its box`);
      const lineHeight = parseFloat(cs.lineHeight);
      const fontSize = parseFloat(cs.fontSize);
      if (clean.some((run) => !run.br && run.size !== fontSize)) problems.push(`${label}: “${text.slice(0, 40)}” mixes font sizes`);

      // Where the browser put the first baseline: an empty inline block sits on it.
      const probe = document.createElement("span");
      probe.style.cssText = "display:inline-block;width:0;height:0";
      el.insertBefore(probe, el.firstChild);
      const baseline = probe.getBoundingClientRect().bottom - origin.top;
      probe.remove();

      // The words (a hyphen ends a word: a line may break after it), line by line as the browser laid them out.
      const tokens = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_ALL);
      const piece = document.createRange();
      let forced = false;
      let glued = false;
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (node.nodeType === Node.ELEMENT_NODE) {
          if (node.tagName === "BR") { forced = true; glued = false; }
          continue;
        }
        const content = node.textContent;
        const pattern = /[^\s-]*-|[^\s-]+/g;
        for (let m = pattern.exec(content); m; m = pattern.exec(content)) {
          piece.setStart(node, m.index);
          piece.setEnd(node, m.index + m[0].length);
          const r = piece.getBoundingClientRect();
          const follows = m.index === 0 ? glued : !/\s/.test(content[m.index - 1]);
          const previous = tokens[tokens.length - 1];
          const hyphen = m[0].endsWith("-");
          if (follows && previous && !previous.hyphen && !forced) {
            // Same word as the previous piece (another style inside a word): one unbreakable unit.
            previous.right = Math.max(previous.right, r.right);
            previous.hyphen = hyphen;
          } else {
            tokens.push({ left: r.left, right: r.right, top: r.top, hyphen, forced, spaceBefore: !follows });
          }
          forced = false;
        }
        glued = content.length > 0 && !/\s$/.test(content);
      }
      const rows = [];
      for (const token of tokens) {
        const row = rows[rows.length - 1];
        if (row && Math.abs(row[0].top - token.top) < lineHeight / 2) row.push(token);
        else rows.push([token]);
      }
      // Narrowest box that holds every line, and the width from which a line would take the next word as well.
      const space = fontSize * 569 / 2048;
      let least = 0;
      let most = Infinity;
      rows.forEach((row, i) => {
        const width = row[row.length - 1].right - row[0].left;
        least = Math.max(least, width);
        const next = rows[i + 1] && rows[i + 1][0];
        if (next && !next.forced) most = Math.min(most, width + (next.spaceBefore ? space : 0) + (next.right - next.left));
      });
      if (most <= least) problems.push(`${label}: “${text.slice(0, 40)}” has no width at which its lines break as in the browser`);

      boxes.push({
        x: rect.left - origin.left, y: rect.top - origin.top, w: rect.width, h: rect.height, baseline,
        inkW: ink.width, least, most: Number.isFinite(most) ? most : null,
        align: cs.textAlign === "start" ? "left" : cs.textAlign, lineHeight, fontSize, wrap: cs.whiteSpace !== "nowrap",
        lines: rows.length, runs: clean, text,
      });
    }
    for (let a = 0; a < boxes.length; a += 1) {
      for (let b = a + 1; b < boxes.length; b += 1) {
        const [p, q] = [boxes[a], boxes[b]];
        const w = Math.min(p.x + Math.min(p.w, p.inkW), q.x + Math.min(q.w, q.inkW)) - Math.max(p.x, q.x);
        const h = Math.min(p.y + p.h, q.y + q.h) - Math.max(p.y, q.y);
        if (w > 1 && h > 1) problems.push(`${label}: “${p.text.slice(0, 30)}” overlaps “${q.text.slice(0, 30)}” (${Math.round(w)} x ${Math.round(h)} px)`);
      }
    }
    // An editable text must not run into a block it does not belong to.
    for (const el of slide.querySelectorAll("[data-tx]")) {
      const r = el.getBoundingClientRect();
      for (const block of slide.querySelectorAll(".card, .band, .browser")) {
        if (block.contains(el)) continue;
        const b = block.getBoundingClientRect();
        const w = Math.min(r.right, b.right) - Math.max(r.left, b.left);
        const h = Math.min(r.bottom, b.bottom) - Math.max(r.top, b.top);
        if (w > 1 && h > 1) problems.push(`${label}: “${el.textContent.trim().slice(0, 30)}” runs into a block next to it (${Math.round(w)} x ${Math.round(h)} px)`);
      }
      // ... nor out of the block it belongs to.
      const own = el.closest(".card, .band");
      if (own) {
        const b = own.getBoundingClientRect();
        const range = document.createRange();
        range.selectNodeContents(el);
        const ink = range.getBoundingClientRect();
        if (ink.left < b.left - 0.5 || ink.right > b.right + 0.5 || ink.top < b.top - 0.5 || ink.bottom > b.bottom + 0.5) {
          problems.push(`${label}: “${el.textContent.trim().slice(0, 30)}” leaves its block`);
        }
      }
    }
    const notes = [...slide.querySelectorAll(".notes p")].map((p) => ({ cue: p.classList.contains("cue"), text: p.textContent.replace(/\s+/g, " ").trim() }));
    return {
      index, name: slide.getAttribute("data-name") || `Slide ${index + 1}`, seconds: Number(slide.getAttribute("data-seconds") || 0),
      backup: slide.hasAttribute("data-backup"), dark: slide.classList.contains("dark"), boxes, notes,
    };
  });
  return { slides, problems };
}

const words = (text) => text.split(/\s+/).filter(Boolean).length;
const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

function speakerScript(slides) {
  const main = slides.filter((s) => !s.backup);
  const spoken = (s) => s.notes.filter((n) => !n.cue).map((n) => n.text).join(" ");
  const total = main.reduce((sum, s) => sum + words(spoken(s)), 0);
  const seconds = main.reduce((sum, s) => sum + s.seconds, 0);
  let md = "# SolarWise DZ - speaker script\n\n";
  md += `Written by \`presentation/src/build.cjs\` from the notes in \`presentation/src/deck.html\`. Edit the notes there, not this file.\n\n`;
  md += `**${main.length} slides, ${mmss(seconds)} planned, ${total} words to say** - that is ${Math.round(total / (seconds / 60))} words a minute, a calm pace. `;
  md += "The same text is in the notes pane of the PowerPoint file and behind the `N` key of the HTML version.\n\n";
  md += "| # | Slide | From | To | Seconds | Words |\n|---|---|---|---|---|---|\n";
  let at = 0;
  for (const s of main) {
    md += `| ${s.index + 1} | ${s.name} | ${mmss(at)} | ${mmss(at + s.seconds)} | ${s.seconds} | ${words(spoken(s))} |\n`;
    at += s.seconds;
  }
  md += "\n## What to say\n";
  at = 0;
  for (const s of main) {
    md += `\n### ${s.index + 1}. ${s.name} (${mmss(at)} to ${mmss(at + s.seconds)})\n\n`;
    for (const n of s.notes) md += n.cue ? `*${n.text}*\n\n` : `${n.text}\n\n`;
    at += s.seconds;
  }
  const backups = slides.filter((s) => s.backup);
  if (backups.length) {
    md += "\n## Backup slides (only if a question calls for them)\n";
    for (const s of backups) {
      md += `\n### ${s.index + 1}. ${s.name}\n\n`;
      for (const n of s.notes) md += n.cue ? `*${n.text}*\n\n` : `${n.text}\n\n`;
    }
  }
  const extras = path.join(SRC, "script-extras.md");
  if (fs.existsSync(extras)) md += `\n${fs.readFileSync(extras, "utf8").trim()}\n`;
  return { md, total, seconds };
}

(async () => {
  fs.mkdirSync(WORK, { recursive: true });
  const html = assemble();
  const flat = path.join(SRC, ".build.html");
  fs.writeFileSync(flat, html);
  const browser = await puppeteer.launch({
    executablePath: chromium(), headless: "shell",
    args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--font-render-hinting=none", "--allow-file-access-from-files",
      ...(process.env.CHROMIUM_ARGS || "").split(/\s+/).filter(Boolean)],
    defaultViewport: { width: 1280, height: 720, deviceScaleFactor: 2 },
  });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(`page error: ${e.message}`));
    page.on("requestfailed", (r) => errors.push(`not loaded: ${r.url()}`));
    await page.goto(`file://${flat}?flat`, { waitUntil: "load" });
    await page.evaluate(async () => {
      await document.fonts.ready;
      await Promise.all([...document.images].map((img) => (img.complete ? null : new Promise((done) => { img.onload = img.onerror = done; }))));
    });
    const fonts = await page.evaluate(() => [...document.fonts].filter((f) => f.status === "loaded").length);
    if (fonts < 2) errors.push(`only ${fonts} font file(s) loaded`);
    const broken = await page.evaluate(() => [...document.images].filter((img) => img.naturalWidth === 0).map((img) => img.getAttribute("src")));
    for (const src of broken) errors.push(`picture not loaded: ${src}`);

    const { slides, problems } = await page.evaluate(extractInPage, ALLOWED.source);
    const handles = await page.$$(".slide");
    for (let i = 0; i < handles.length; i += 1) {
      await handles[i].screenshot({ path: path.join(WORK, `slide-${String(i + 1).padStart(2, "0")}.png`) });
    }
    console.log(`${handles.length} slides drawn in ${path.relative(process.cwd(), WORK)}/`);

    if (!PREVIEW) {
      await page.evaluate(() => document.documentElement.classList.add("plate"));
      for (let i = 0; i < handles.length; i += 1) {
        await handles[i].screenshot({ path: path.join(WORK, `plate-${String(i + 1).padStart(2, "0")}.png`) });
      }
      await page.evaluate(() => document.documentElement.classList.remove("plate"));
      await page.pdf({ path: path.join(OUT, `${NAME}.pdf`), width: "1280px", height: "720px", printBackground: true, preferCSSPageSize: true });
      console.log(`written: ${NAME}.pdf`);

      fs.writeFileSync(path.join(WORK, "deck.json"), JSON.stringify({ name: NAME, slides }, null, 1));
      fs.writeFileSync(path.join(OUT, `${NAME}.html`), singleFile(html));
      console.log(`written: ${NAME}.html (${Math.round(fs.statSync(path.join(OUT, `${NAME}.html`)).size / 1024)} kB, single file)`);
      const script = speakerScript(slides);
      fs.writeFileSync(path.join(OUT, "SPEAKER-SCRIPT.md"), script.md);
      console.log(`written: SPEAKER-SCRIPT.md (${script.total} words for ${mmss(script.seconds)})`);
    }
    for (const line of [...errors, ...problems]) console.log(`PROBLEM ${line}`);
    if (errors.length || problems.length) process.exitCode = 1;
    else console.log("no layout problem found");
  } finally {
    await browser.close();
    fs.rmSync(flat, { force: true });
  }
})().catch((error) => { console.error(error); process.exit(1); });
