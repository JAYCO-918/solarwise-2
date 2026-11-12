// The application embedded by a page of another origin, as a preview pane or a portal embeds it.
//   ./run.sh framing.cjs refused                  default settings: the browser must refuse to frame the application
//   FRAME=allowed ./run.sh framing.cjs allowed    SOLARWISE_FRAME_ANCESTORS names the parent: the application works in the frame
const http = require("http");
const { BASE, launch, expect, shot, scriptError, finish } = require("./lib.cjs");

const mode = process.argv[2] === "allowed" ? "allowed" : "refused";
const port = Number(process.env.E2E_PARENT_PORT || 18014);
const parent = http.createServer((request, response) => {
  response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  response.end(`<!doctype html><title>Embedding page</title><body style="margin:0"><iframe id="app" src="${BASE}/login" style="width:1280px;height:800px;border:0"></iframe></body>`);
});

(async () => {
  await new Promise((resolve) => parent.listen(port, "127.0.0.1", resolve));
  const { browser, page, problems } = await launch({ width: 1320, height: 860 });
  try {
    await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "load" });
    const frame = await (await page.waitForSelector("#app")).contentFrame();
    const shown = () => frame.waitForFunction(
      () => [...document.querySelectorAll("button")].some((b) => b.textContent.includes("Open the demonstration")), { timeout: mode === "allowed" ? 15000 : 4000 },
    ).then(() => true, () => false);

    if (mode === "refused") {
      expect(!(await shown()), "with the default settings the application is not drawn inside a page of another origin");
      const reason = problems.find((p) => /frame-ancestors|X-Frame-Options/i.test(p));
      expect(Boolean(reason), `the browser says why: ${reason ? reason.slice(0, 160) : "no message"}`);
    } else {
      expect(await shown(), "the sign-in page is drawn inside the frame of the allowed origin");
      const origins = [await page.evaluate(() => location.origin), await frame.evaluate(() => location.origin)];
      expect(origins[0] !== origins[1], `the two origins differ: ${origins.join(" embeds ")}`);
      await (await frame.evaluateHandle(() => [...document.querySelectorAll("button")].find((b) => b.textContent.includes("Open the demonstration")))).asElement().click();
      await frame.waitForFunction(
        () => location.pathname === "/plants" && document.querySelector('a[href="/plants/1"]') !== null &&
          [...document.querySelectorAll("button")].some((b) => b.textContent.includes("Sign out")), { timeout: 15000 },
      );
      expect(true, "the demonstration opens inside the frame");
      await (await frame.$('a[href="/plants/1"]')).click();
      await frame.waitForFunction(() => location.pathname === "/plants/1" && document.querySelectorAll("tbody tr").length >= 10, { timeout: 15000 });
      expect(true, "the plant page loads inside the frame");
    }
    await page.screenshot({ path: shot(`framing-${mode}`) });
  } catch (error) {
    await scriptError(page, error);
  }
  parent.close();
  // When framing is refused, the refusal itself is what the browser reports.
  await finish(browser, problems, (p) => mode === "refused" && /frame-ancestors|X-Frame-Options|\/login/i.test(p));
})();
