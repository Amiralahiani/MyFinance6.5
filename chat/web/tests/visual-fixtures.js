import { test as base } from "@playwright/test";

// One page is intentionally shared by the serial visual demonstration.  Each
// scenario navigates from a clean URL, but the Chromium window stays open so a
// person can follow the complete test run instead of seeing it flash per test.
export const test = base.extend({
  visualPage: [async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await use(page);
    await context.close();
  }, { scope: "worker" }],
});
