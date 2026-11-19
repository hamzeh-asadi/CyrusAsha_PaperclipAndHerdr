/* Optional browser acceptance check and README screenshot generator. No Paperclip,
 * .env, CLI or real company: the fixture serves fixed assets and sample JSON only. */
const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs/promises");
const path = require("node:path");
const puppeteer = require("puppeteer-core");
const root = path.resolve(__dirname, "../..");
const capture = process.argv.includes("--screenshots");
const staticFiles = {
  "/": ["index.html", "text/html"],
  "/desk.css": ["desk.css", "text/css"],
  "/desk.js": ["desk.js", "text/javascript"],
  "/i18n.js": ["i18n.js", "text/javascript"],
  "/strings.json": ["strings.json", "application/json"],
  "/fonts/vazirmatn-arabic.woff2": ["fonts/vazirmatn-arabic.woff2", "font/woff2"],
  "/brand/desk-mark.png": ["brand/desk-mark.png", "image/png"],
};
const members = [
  { id: "linked", name: "Antigravity", status: "idle", connection: { mode: "agent", target: "agy-studio" } },
  { id: "manual", name: "Freebuff", status: "idle", connection: { mode: "manual" } },
  { id: "qa", name: "Studio QA", status: "pending_approval", connection: { mode: "manual" } },
];
const example = {
  en: [
    "Atlas Studio · Sample",
    "Customer directory search",
    "Implement the search filter",
    "Test the empty state",
    "Review keyboard navigation",
  ],
  fa: [
    "کارگاه اطلس · نمونه",
    "جست‌وجو در فهرست مشتریان",
    "ساخت فیلتر جست‌وجو",
    "آزمون فهرست خالی",
    "بازبینی پیمایش با صفحه‌کلید",
  ],
};
// The fixture dataset is chosen explicitly for each capture, never by UI language.
let dataset = "fa";
const submissions = [];
const writes = [];
async function fixture(req, res) {
  const route = new URL(req.url, "http://fixture.invalid").pathname;
  if (req.method === "GET" && Object.hasOwn(staticFiles, route)) {
    const [file, type] = staticFiles[route];
    res.writeHead(200, {
      "Content-Type": type,
      "Content-Security-Policy": "default-src 'self'; object-src 'none'",
      "Cache-Control": "no-store",
    });
    return res.end(await fs.readFile(path.join(root, "dashboard", file)));
  }
  const send = (code, value) => {
    res.writeHead(code, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    res.end(JSON.stringify(value));
  };
  if (req.method === "GET") {
    if (route === "/health") return send(200, { paperclip: true });
    if (route === "/api/agents")
      return send(200, {
        company: { id: "fixture", name: example[dataset][0], boardUrl: "/sample-board" },
        agents: members,
        localControl: true,
      });
    if (route === "/api/tickets")
      return send(200, {
        tickets: example[dataset].slice(1).map((title, i) => ({
          id: `sample-${i}`,
          identifier: `ATL-${21 + i}`,
          title,
          parentId: i ? "sample-0" : null,
          assigneeAgentId: [null, "linked", "manual", "manual"][i],
          status: ["backlog", "in_review", "in_progress", "backlog"][i],
        })),
      });
    if (route === "/api/herdr/targets")
      return send(200, { targets: [{ target: "agy-studio", kind: "agy", terminal: "", status: "idle" }] });
    if (route === "/api/agents/linked/output")
      return send(200, { success: true, output: "<sample terminal>\n✓ OK" });
  }
  if (req.method === "POST") {
    writes.push(route);
    if (route === "/api/plans") {
      let body = "";
      for await (const chunk of req) body += chunk;
      submissions.push(body);
      if (submissions.length === 1)
        return send(503, {
          error: "Test interruption",
          i18n: { key: "err.partial", vars: { id: "ATL-21", count: 1, total: 2, reason: "(fixture)" } },
        });
      const plan = JSON.parse(body);
      return send(200, { parent: { id: "sample-0", identifier: "ATL-21" }, children: plan.steps });
    }
  }
  return send(404, { error: "Fixture route only" });
}
async function run() {
  const server = http.createServer((req, res) =>
    fixture(req, res).catch((e) => {
      res.destroy(e);
    }),
  );
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: process.env.CHROME_BIN,
      headless: true,
      args: process.env.CHROME_NO_SANDBOX === "1" ? ["--no-sandbox"] : [],
    });
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const url = `http://127.0.0.1:${server.address().port}`;
    const clickText = async (selector, label) =>
      page.evaluate(
        (s, l) => {
          const b = [...document.querySelectorAll(s)].find((n) => n.textContent.trim() === l);
          if (!b) throw Error("Missing " + l);
          b.click();
        },
        selector,
        label,
      );
    const ready = () => page.waitForSelector("#health.online");
    const switchTo = async (lang) => {
      await page.click(`[data-lang="${lang}"]`);
      assert.deepEqual(
        await page.evaluate(() => [
          document.documentElement.lang,
          document.documentElement.dir,
          ...Array.from(document.querySelectorAll('[data-lang][aria-pressed="true"]'), (b) => b.dataset.lang),
        ]),
        [lang, lang === "fa" ? "rtl" : "ltr", lang],
      );
    };
    const fill = async (selector, value) =>
      page.$eval(
        selector,
        (n, v) => {
          n.value = v;
        },
        value,
      );
    const out = path.join(root, "docs/screenshots");
    if (capture) await fs.mkdir(out, { recursive: true });
    const shot = async (name) => {
      if (capture) {
        await page.evaluate(() => {
          document.activeElement?.blur();
          return document.fonts.ready;
        });
        await page.mouse.move(0, 0);
        await page.screenshot({ path: path.join(out, name + ".png"), fullPage: true });
      }
    };
    await page.setViewport({ width: 1240, height: 880, deviceScaleFactor: 1 });
    await page.goto(url);
    await ready();
    assert.equal(await page.$eval("html", (n) => n.lang), "fa");
    for (const lang of ["fa", "en"]) {
      dataset = lang;
      await page.reload();
      await ready();
      await switchTo(lang);
      await fill("#planTitle", example[lang][1]);
      await fill(".step-title", example[lang][2]);
      await page.select(".assignee", "linked");
      await page.click("#addStep");
      await fill(".step:last-child .step-title", example[lang][3]);
      await page.select(".step:last-child .assignee", "manual");
      await shot("planner-" + lang);
      await page.click('[data-tab="team"]');
      await page.select("#preset", "Antigravity");
      await page.waitForSelector('#target option[value="agy-studio"]');
      await page.select("#target", "agy-studio");
      await shot("team-" + lang);
      await page.click('[data-tab="tasks"]');
      await shot("work-" + lang);
    }
    await page.click('[data-tab="team"]');
    await switchTo("fa");
    assert.equal(await page.$eval("#preset", (n) => n.value), "Antigravity");
    assert.equal(await page.$eval("#target", (n) => n.value), "agy-studio");
    assert.equal(await page.$eval("#memberName", (n) => n.value), "Antigravity");
    await clickText(".member button", "خروجی Herdr");
    await page.waitForFunction(() =>
      document.querySelector("#detailText").value.includes("<sample terminal>"),
    );
    assert.equal(await page.$eval("#detailText", (n) => n.value), "<sample terminal>\n✓ OK");
    await page.click("#closeDetail");
    await switchTo("en");
    await page.click('[data-tab="tasks"]');
    await page.select("#filter", "manual");
    await clickText(".task button", "Work sheet");
    await page.waitForSelector("dialog[open]");
    assert((await page.$eval("#detailText", (n) => n.value)).includes("Owner: Freebuff"));
    // Native modal blocks header clicks; close normally, then switch languages.
    await page.click("#closeDetail");
    await switchTo("fa");
    assert.equal(await page.$eval("#filter", (n) => n.value), "manual");
    assert.equal(await page.$eval('[data-page="tasks"]', (n) => n.hidden), false);
    await page.click('[data-tab="plan"]');
    assert.equal(await page.$eval("#planTitle", (n) => n.value), example.en[1]);
    await page.click("#savePlan");
    await page.waitForSelector("#discard:not([hidden])");
    await switchTo("en");
    assert(await page.$eval("#planFields", (n) => n.disabled));
    assert.match(await page.$eval("#planFeedback", (n) => n.textContent), /1 of 2/);
    assert.equal(await page.$eval(".step:last-child .assignee", (n) => n.value), "manual");
    assert.equal(submissions.length, 1);
    await page.click("#savePlan");
    await page.waitForSelector("#planFeedback button");
    assert.equal(submissions[0], submissions[1]);
    await switchTo("fa");
    assert.match(await page.$eval("#planFeedback", (n) => n.textContent), /۲/);
    await page.click("#planFeedback button");
    await page.reload();
    await ready();
    assert.equal(await page.$eval("html", (n) => n.lang), "fa");
    await switchTo("en");
    await page.reload();
    await ready();
    assert.equal(await page.$eval("html", (n) => n.lang), "en");
    await page.setViewport({ width: 360, height: 800 });
    for (const lang of ["en", "fa"]) {
      await switchTo(lang);
      for (const tab of ["plan", "team", "tasks"]) {
        await page.click(`[data-tab="${tab}"]`);
        assert(
          await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
          lang + " mobile overflow: " + tab,
        );
      }
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(writes, ["/api/plans", "/api/plans"]);
    console.log(
      "OK · both directions, all three views, persistent language, preserved draft/owner/filter, localized retry with identical request; no agent actions." +
        (capture ? " Six screenshots saved." : ""),
    );
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}
run().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
