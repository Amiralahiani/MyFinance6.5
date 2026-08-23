import { defineConfig } from "@playwright/test";

// The visual suite starts only the Chat Web application. Its deterministic
// fixtures intercept answer calls, so Docker never has to start a second
// Python orchestrator inside the Testing container.
const chatApiUrl = process.env.MYFINANCE_PLAYWRIGHT_API_URL ?? "http://127.0.0.1:8000";
const showBrowser = process.env.MYFINANCE_PLAYWRIGHT_VISIBLE === "1";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  reporter: [["list"], ["json", { outputFile: "test-results/playwright-results.json" }]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
    headless: !showBrowser,
    launchOptions: showBrowser ? { slowMo: 900 } : {},
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173",
    env: { VITE_API_URL: chatApiUrl },
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
