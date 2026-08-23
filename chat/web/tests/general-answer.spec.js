import { expect, test } from "@playwright/test";

test("renders a general explanation without crashing the conversation", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("**/api/conversation/answer", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      type: "general",
      mode: "general",
      topic: "general_education",
      answer: "A tailored explanation generated for this general question.",
      context: { mode: "idle", bank_id: null, bank_name: null, reporting_year: null, topic: null, document_scope: null, document_anchor: null, document_anchor_page: null, metric_id: null },
    }),
  }));

  await page.goto("/");
  await page.getByRole("textbox").fill("whta is a financial repport");
  await page.getByRole("button", { name: "SEND" }).click();

  await expect(page.getByText("MYFINANCE · GENERAL EXPLANATION")).toBeVisible();
  await expect(page.getByText(/A tailored explanation generated/)).toBeVisible();
  expect(pageErrors).toEqual([]);
});
