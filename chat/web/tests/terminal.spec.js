import { expect, test } from "@playwright/test";

const context = {
  mode: "idle", bank_id: null, bank_name: null, reporting_year: null, topic: null,
  document_scope: null, document_anchor: null, document_anchor_page: null, metric_id: null,
};

async function answerWith(page, answer) {
  await page.route("**/api/conversation/answer", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(answer) });
  });
}

async function ask(page, question) {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Your question" }).fill(question);
  await page.getByRole("button", { name: "SEND" }).click();
}

test("renders an automatically validated financial value with its PDF evidence", async ({ page }) => {
  await answerWith(page, {
    type: "numeric", metric_id: "net_banking_income", value: "1396872", currency: "TND",
    unit_scale: "thousand", reporting_year: 2023, context: { ...context, mode: "metric", bank_name: "BIAT" },
    source_document: "data/raw/official-reports/etat financier/biat/biat_efd311223.pdf",
    page_number: 4, source_excerpt: "Produit Net Bancaire 1 396 872 1 267 146",
  });

  await ask(page, "What was BIAT's NBI in 2023?");

  await expect(page.getByText("MYFINANCE · AUTOMATICALLY VALIDATED VALUE")).toBeVisible();
  await expect(page.locator(".value strong")).toHaveText("1,396,872");
  await expect(page.getByText("PRIMARY EVIDENCE")).toBeVisible();
  await expect(page.getByText(/Produit Net Bancaire 1 396 872/)).toBeVisible();
});

test("renders a documentary answer with a source excerpt", async ({ page }) => {
  await answerWith(page, {
    type: "document", mode: "document", context: { ...context, mode: "document", bank_id: "biat", bank_name: "BIAT", reporting_year: 2021 },
    analysis: { direct_answer: "BIAT documents the related-party transaction in the relevant note." },
    evidence: [{ chunk_id: "biat-2021-38", bank_name: "BIAT", reporting_year: 2021, page_number: 38, source_path: "data/raw/official-reports/etat financier/biat/biat_efd311221.pdf", text: "Related-party transactions are disclosed in the note." }],
  });

  await ask(page, "What does BIAT's 2021 report say about related-party transactions?");

  await expect(page.getByText("BIAT documents the related-party transaction in the relevant note.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Source · BIAT · 2021 · p. 38/ })).toBeVisible();
  await expect(page.getByText("View excerpt")).toBeVisible();
});

test("renders an official Market Watch quote without using a report value", async ({ page }) => {
  await answerWith(page, {
    type: "market_quote", mode: "market", context: { ...context, mode: "market", market_bank_ids: ["biat"] },
    answer: "BIAT is quoted at 98.50 TND.",
    quote: { bank_name: "BIAT", mnemonic: "BIAT", price: 98.5, change_percent: 0.25, currency: "TND", retrieved_at: "2026-08-23T10:00:00Z", delay_notice: "15 minutes", isin: "TN0001800457", source_url: "https://tunis-stockexchange.com/market-watch" },
  });

  await ask(page, "What is BIAT's current share price?");

  await expect(page.getByText("MYFINANCE · MARKET WATCH")).toBeVisible();
  await expect(page.getByText("CURRENT SHARE PRICE", { exact: true })).toBeVisible();
  await expect(page.locator(".market-price strong")).toHaveText("98.5");
  await expect(page.getByRole("link", { name: /Open Market Watch/ })).toBeVisible();
});

test("renders a safe Market Watch notice when an official quote is unavailable", async ({ page }) => {
  await answerWith(page, {
    type: "market_notice", mode: "market", context: { ...context, mode: "market", market_bank_ids: ["biat"] },
    title: "Official quote unavailable", message: "The official Market Watch quote could not be read right now.",
  });

  await ask(page, "What is BIAT's current share price?");

  await expect(page.getByText("Official quote unavailable")).toBeVisible();
  await expect(page.getByText(/could not be read right now/)).toBeVisible();
});

test("renders an official source link for a general explanation", async ({ page }) => {
  await answerWith(page, {
    type: "general", mode: "general", context,
    answer: "The S&P 500 is a principal US stock-market index.",
    sources: [{ source_id: "spglobal_sp500", title: "S&P Dow Jones Indices", url: "https://www.spglobal.com/spdji/en/indices/equity/sp-500/" }],
  });

  await ask(page, "What is the principal stock-market index in the United States?");

  await expect(page.getByText("MYFINANCE · GENERAL EXPLANATION")).toBeVisible();
  await expect(page.getByRole("link", { name: /Official source · S&P Dow Jones Indices/ })).toBeVisible();
});
