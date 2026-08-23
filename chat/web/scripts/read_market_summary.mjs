import { chromium } from "playwright";

const sourceUrl = "https://tunis-stockexchange.com/market-watch";
const labels = {
  market_capitalization_tnd: "Capitalisation boursière (TND)",
  traded_value_tnd: "Capitaux (TND)",
  traded_quantity: "Quantité",
  transactions: "Transactions",
  advances: "Hausses",
  declines: "Baisses",
  active_values: "Valeurs actives",
};

const browser = await chromium.launch({ headless: true, timeout: 15_000 });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(sourceUrl, { waitUntil: "domcontentloaded", timeout: 30_000 });
  let lines = [];
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const frame = page.frames().find((candidate) => candidate.url().includes("ro8hjxj/7cb05a1"));
    if (frame) {
      lines = (await frame.locator("body").innerText().catch(() => ""))
        .split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      if (Object.values(labels).every((label) => lines.includes(label))) break;
    }
    await page.waitForTimeout(2_000);
  }
  const metrics = Object.fromEntries(Object.entries(labels).map(([key, label]) => {
    const index = lines.indexOf(label);
    return [key, index >= 0 ? lines[index + 1] : null];
  }));
  if (Object.values(metrics).some((value) => value === null)) {
    throw new Error("The market summary panel is incomplete.");
  }
  const delayNotice = await page.locator("body").innerText().then((body) =>
    /Flux différés de 15 min/i.test(body) ? "15 minutes" : null,
  );
  process.stdout.write(JSON.stringify({
    ...metrics,
    source_url: sourceUrl,
    retrieved_at: new Date().toISOString(),
    delay_notice: delayNotice,
  }));
} finally {
  await browser.close();
}
