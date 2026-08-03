import { defineConfig } from "@playwright/test";

// The local Testing service may start this suite from a virtual environment
// without the Playwright browser. It therefore supplies its base interpreter.
const pythonForUv = process.env.MYFINANCE_UV_PYTHON ?? "python";
// Local validation is deliberately observable; set this to 0 only for a
// non-interactive automation environment.
const showBrowser = process.env.MYFINANCE_PLAYWRIGHT_VISIBLE !== "0";

export default defineConfig({
  testDir: "./tests",
  reporter: [["list"], ["json", { outputFile: "test-results/playwright-results.json" }]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
    headless: !showBrowser,
    launchOptions: showBrowser ? { slowMo: 900 } : {},
  },
  webServer: [
    {
      command: `"${pythonForUv}" -m uv run --project ../.. python ../scripts/run_orchestrator.py --port 8002`,
      url: "http://127.0.0.1:8002/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4173",
      url: "http://127.0.0.1:4173",
      env: { VITE_API_URL: "http://127.0.0.1:8002" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
