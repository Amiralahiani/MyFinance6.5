import { chromium } from "playwright";

const mnemonics = [...new Set(process.argv.slice(2).map((value) => value.trim().toUpperCase()))];
if (mnemonics.length === 0 || mnemonics.some((mnemonic) => !/^[A-Z0-9]{1,12}$/.test(mnemonic))) {
  throw new Error("At least one valid market mnemonic is required.");
}

const sourceUrl = "https://tunis-stockexchange.com/market-watch";
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(sourceUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
  let lines = [];
  let quotes = [];
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const frame = page.frames().find((candidate) => candidate.url().includes("ticker-db-reader"));
    if (frame) {
      const text = await frame.locator("body").innerText().catch(() => "");
      lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      quotes = mnemonics.map((mnemonic) => {
        const index = lines.findIndex((line) => line === mnemonic);
        return index >= 0 && lines[index + 1] && lines[index + 2]
          ? { mnemonic, displayed_price: lines[index + 1], displayed_change: lines[index + 2] }
          : null;
      }).filter(Boolean);
      if (quotes.length === mnemonics.length) break;
    }
    await page.waitForTimeout(2_000);
  }
  if (quotes.length !== mnemonics.length) {
    const found = new Set(quotes.map((quote) => quote.mnemonic));
    throw new Error(`No current quote is displayed for ${mnemonics.filter((mnemonic) => !found.has(mnemonic)).join(", ")}.`);
  }
  const delayNotice = await page.locator("body").innerText().then((body) =>
    /Flux différés de 15 min/i.test(body) ? "15 minutes" : null,
  );
  process.stdout.write(JSON.stringify({
    quotes,
    source_url: sourceUrl,
    retrieved_at: new Date().toISOString(),
    delay_notice: delayNotice,
  }));
} finally {
  await browser.close();
}
