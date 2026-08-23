import { expect, test } from "@playwright/test";

const idleContext = {
  mode: "idle", bank_id: null, bank_name: null, reporting_year: null, topic: null,
  document_scope: null, document_anchor: null, document_anchor_page: null, metric_id: null,
};

const answers = {
  "What was BIAT's NBI in 2023?": {
    type: "numeric", metric_id: "net_banking_income", value: "1396872", currency: "TND",
    unit_scale: "thousand", reporting_year: 2023,
    context: { ...idleContext, mode: "metric", bank_id: "biat", bank_name: "BIAT", metric_id: "net_banking_income", reporting_year: 2023 },
    source_document: "data/raw/official-reports/etat financier/biat/biat_efd311223.pdf",
    page_number: 4, source_excerpt: "Produit Net Bancaire 1 396 872 1 267 146",
  },
  "What does BIAT's 2021 report say about related-party transactions?": {
    type: "document", mode: "document",
    context: { ...idleContext, mode: "document", bank_id: "biat", bank_name: "BIAT", reporting_year: 2021 },
    analysis: { direct_answer: "BIAT documents the nature and terms of related-party transactions in a dedicated note." },
    evidence: [
      { chunk_id: "biat-2021-38", bank_name: "BIAT", reporting_year: 2021, page_number: 38, source_path: "data/raw/official-reports/etat financier/biat/biat_efd311221.pdf", text: "Related-party transactions are disclosed in the note, including their nature and terms." },
      { chunk_id: "biat-2021-39", bank_name: "BIAT", reporting_year: 2021, page_number: 39, source_path: "data/raw/official-reports/etat financier/biat/biat_efd311221.pdf", text: "The report identifies the counterparties and documents the relevant transaction conditions." },
    ],
  },
  "What is BIAT's current share price?": {
    type: "market_quote", mode: "market", context: { ...idleContext, mode: "market", market_bank_ids: ["biat"] },
    answer: "BIAT is quoted at 98.50 TND.",
    quote: { bank_name: "BIAT", mnemonic: "BIAT", price: 98.5, change_percent: 0.25, currency: "TND", retrieved_at: "2026-08-23T10:00:00Z", delay_notice: "15 minutes", isin: "TN0001800457", source_url: "https://tunis-stockexchange.com/market-watch" },
  },
  "What is the principal stock-market index in the United States?": {
    type: "general", mode: "general", context: idleContext,
    answer: "The S&P 500 is a principal US stock-market index.",
    sources: [{ source_id: "spglobal_sp500", title: "S&P Dow Jones Indices", url: "https://www.spglobal.com/spdji/en/indices/equity/sp-500/" }],
  },
};

async function askWithKeyboard(page, question) {
  const input = page.getByRole("textbox", { name: "Your question" });
  await input.fill(question);
  await input.press("Enter");
}

test("walks through an analyst journey: navigation, answers, evidence, scrolling and reset", async ({ page }) => {
  test.setTimeout(60_000);

  // The delayed deterministic API reply makes the loading state visible in the live viewer.
  await page.route("**/api/conversation/answer", async (route) => {
    const { message } = route.request().postDataJSON();
    // Visible Playwright runs use a deliberate action slow-down. Keep the first
    // reply on screen long enough that a human can actually see the loading UI.
    await new Promise((resolve) => setTimeout(resolve, message === "What was BIAT's NBI in 2023?" ? 2_500 : 350));
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(answers[message]) });
  });

  await page.goto("/");

  // Explore the non-conversation areas first, as a user would.
  await page.getByRole("button", { name: /Sources/ }).click();
  await expect(page.getByRole("heading", { name: "Every answer can be audited." })).toBeVisible();
  await page.getByRole("button", { name: /Banks/ }).click();
  await expect(page.getByText("Banks on the radar.")).toBeVisible();
  await page.getByRole("button", { name: /Analysis/ }).click();
  await expect(page.getByRole("heading", { name: "Clear answers. Immediate evidence." })).toBeVisible();

  // Send the first question with Enter, and prove that the UI reacts while the answer is loading.
  await askWithKeyboard(page, "What was BIAT's NBI in 2023?");
  await expect(page.getByRole("button", { name: /ANALYSING/ })).toBeVisible();
  await expect(page.getByText("Checking the relevant official source…")).toBeVisible();
  await expect(page.locator(".value strong")).toHaveText("1,396,872");

  // Continue the conversation, then unfold both official excerpts.
  await askWithKeyboard(page, "What does BIAT's 2021 report say about related-party transactions?");
  await expect(page.getByText("BIAT documents the nature and terms of related-party transactions in a dedicated note.")).toBeVisible();
  await page.getByText("View 2 excerpts").click();
  await expect(page.getByText(/The report identifies the counterparties/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Open PDF ↗" })).toHaveCount(2);

  // Add two different response modes to create a real conversation that must scroll.
  await askWithKeyboard(page, "What is BIAT's current share price?");
  await expect(page.getByText("CURRENT SHARE PRICE", { exact: true })).toBeVisible();
  await askWithKeyboard(page, "What is the principal stock-market index in the United States?");
  await expect(page.getByRole("link", { name: /Official source · S&P Dow Jones Indices/ })).toBeVisible();

  const thread = page.locator(".thread");
  await expect.poll(() => thread.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
  await thread.hover();
  const scrollBefore = await thread.evaluate((node) => node.scrollTop);
  await page.mouse.wheel(0, 420);
  await page.waitForTimeout(700);
  const scrollAfterFirstStep = await thread.evaluate((node) => node.scrollTop);
  expect(scrollAfterFirstStep).toBeGreaterThan(scrollBefore);
  await page.mouse.wheel(0, 620);
  await page.waitForTimeout(700);
  await expect.poll(() => thread.evaluate((node) => node.scrollTop)).toBeGreaterThan(scrollAfterFirstStep);
  // Pause on the latest answer, then scroll back to the PDF evidence so both
  // directions are visible in the embedded live browser panel.
  await page.waitForTimeout(900);
  await page.mouse.wheel(0, -480);
  await page.waitForTimeout(700);
  await expect.poll(() => thread.evaluate((node) => node.scrollTop)).toBeLessThan(scrollAfterFirstStep + 620);

  // Finally, clear the session and make sure the interface immediately returns to a clean state.
  await page.getByRole("button", { name: "NEW ANALYSIS" }).click();
  await expect(thread).toBeHidden();
  await expect(page.getByText("No context retained yet")).toBeVisible();
});
