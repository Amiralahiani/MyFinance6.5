// Narrow Node bridge: Python supplies one safe question; Playwright returns observations as JSON.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const consoleErrors = [];
const networkErrors = [];
const browser = await chromium.launch({ headless: true });

try {
  const page = await browser.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("requestfailed", (request) => networkErrors.push(`${request.method()} ${request.url()} · ${request.failure()?.errorText ?? "failed"}`));
  page.setDefaultTimeout(input.timeout_ms ?? 20_000);

  await page.goto(input.base_url, { waitUntil: "networkidle" });
  await page.getByRole("textbox", { name: "Votre question" }).fill(input.question);
  await page.getByRole("button", { name: /envoyer/i }).click();
  const answers = page.locator(".message.assistant:not(.pending)");
  await answers.last().waitFor({ state: "visible" });
  await page.waitForFunction(() => !document.querySelector(".message.assistant.pending"));
  const answer = answers.last();
  const className = await answer.getAttribute("class");
  const type = className?.split(" ").find((name) => ["numeric", "document", "clarification", "courtesy"].includes(name)) ?? "text";
  const response = { type };
  if (type === "numeric") {
    const value = answer.locator(".value strong");
    const yearAndUnit = answer.locator(".value p");
    const page = answer.locator("article > div b");
    const excerpt = answer.locator("article blockquote");
    const footer = answer.locator("article footer");
    response.metric_label = await answer.locator(".value small").innerText();
    response.value = await value.innerText();
    response.reporting_year = Number((await yearAndUnit.innerText()).match(/exercice\s+(\d{4})/i)?.[1]) || null;
    response.page_number = Number((await page.innerText()).match(/(\d+)/)?.[1]) || null;
    response.source_excerpt = await excerpt.innerText();
    response.source_document = (await footer.innerText()).match(/[^\s]+\.pdf/i)?.[0] ?? null;
  }
  const screenshotPaths = [];
  if (input.screenshot_path) {
    mkdirSync(dirname(input.screenshot_path), { recursive: true });
    await page.screenshot({ path: input.screenshot_path, fullPage: true });
    screenshotPaths.push(input.screenshot_path);
  }
  process.stdout.write(JSON.stringify({
    ok: true,
    response,
    visible_text: await answer.innerText(),
    dom_snapshot: await answer.evaluate((element) => element.outerHTML),
    screenshot_paths: screenshotPaths,
    console_errors: consoleErrors,
    network_errors: networkErrors,
  }));
} finally {
  await browser.close();
}
