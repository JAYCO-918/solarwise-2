// The ways into the application, as a visitor meets them:
// the demonstration is offered first, a wrong password is explained, the demonstration opens, and a session that
// the server refuses says what the server answered. Run behind PROXY=strip or PROXY=replace it also shows that a
// gateway rewriting the Authorization header does not close the session.
const fs = require("fs");
const { BASE, launch, expect, shot, settle, clickText, scriptError, finish } = require("./lib.cjs");

(async () => {
  const { browser, page, problems } = await launch();
  const calls = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/")) {
      calls.push({ request: r, path: new URL(r.url()).pathname, authorization: "authorization" in r.headers(), own: "x-solarwise-token" in r.headers() });
    }
  });
  page.on("response", (r) => { const call = calls.find((c) => c.request === r.request()); if (call) call.status = r.status(); });
  try {
    await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
    await settle(page);
    const order = await page.evaluate(() => [...document.querySelectorAll("main h2")].map((h) => h.innerText.trim()));
    expect(order[0] === "Try the demonstration" && order[1] === "Sign in with an account", `the demonstration is offered first: ${JSON.stringify(order)}`);
    await page.screenshot({ path: shot("sign-in") });

    await page.type('input[type="email"]', "someone@example.org");
    await page.type('input[type="password"]', "not-my-password-123");
    await clickText(page, "button", "Sign in");
    await settle(page, 500);
    const alert = await page.evaluate(() => (document.querySelector('[role="alert"]') || {}).innerText || "");
    expect(alert.includes("e-mail address or password is incorrect"), `a wrong password is explained: ${JSON.stringify(alert.split("\n")[0])}`);

    await clickText(page, "button", "Open the demonstration");
    await page.waitForFunction(() => location.pathname === "/plants" && document.querySelector('a[href="/plants/1"]'), { timeout: 15000 });
    expect(true, "the demonstration opens after a refused sign-in");
    const plants = calls.filter((c) => c.path === "/api/v1/plants").pop();
    expect(Boolean(plants) && plants.status === 200 && plants.authorization && plants.own,
      `GET /plants -> ${plants && plants.status}; Authorization sent: ${plants && plants.authorization}; X-SolarWise-Token sent: ${plants && plants.own}`);

    await (await page.$('a[href="/plants/1"]')).click();
    await page.waitForFunction(() => location.pathname === "/plants/1" && document.querySelectorAll("tbody tr").length >= 10, { timeout: 15000 });
    expect(true, "the plant page loads");

    // The server refuses the session: the visitor is told what the server answered.
    await page.setRequestInterception(true);
    const refuse = (request) => {
      if (request.url().endsWith("/api/v1/plants")) {
        request.respond({
          status: 401, contentType: "application/json", headers: { "WWW-Authenticate": "Bearer" },
          body: JSON.stringify({ error: { code: "NOT_AUTHENTICATED", message: "the access token is invalid or has expired", details: null } }),
        });
      } else {
        request.continue();
      }
    };
    page.on("request", refuse);
    await clickText(page, "a", "Plants");
    await page.waitForFunction(() => location.pathname === "/login", { timeout: 15000 });
    await settle(page, 300);
    const notice = await page.evaluate(() => document.querySelector("main").innerText);
    expect(notice.includes("The server closed the session") && notice.includes("the access token is invalid or has expired"), "a refused session says what the server answered");
    await page.screenshot({ path: shot("sign-in-refused") });
    page.off("request", refuse);
    await page.setRequestInterception(false);
  } catch (error) {
    await scriptError(page, error);
  }

  const log = fs.readFileSync(process.env.SERVER_LOG, "utf8");
  const warned = log.includes("because its Authorization header was");
  const lines = log.split("\n").filter((l) => l.includes("401 on") || l.includes("Authorization header was")).map((l) => l.replace(/^\S+ \S+ /, ""));
  console.log(`     server log: ${lines.join("\n                 ") || "(no refusal, no warning)"}`);
  if (process.env.PROXY) expect(warned, "the server tells the operator that something removes or replaces the Authorization header");
  else expect(!warned, "no such warning on a direct connection");
  // Expected here: the refused sign-in and the refusal that the check itself injects.
  await finish(browser, problems, (p) => p.includes("/api/v1/auth/login") || p.includes("status of 401") || p.includes("/api/v1/plants"));
})();
