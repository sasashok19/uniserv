import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for UniServe's dashboard E2E suite. Targets the already-
 * running local dev stack (scripts/dev.sh) rather than spawning its own
 * server, since the suite needs the full backend (api-gateway/db-writer/
 * ai-core) to exercise real RBAC/ticket-lifecycle flows, not just the
 * Next.js frontend in isolation.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false, // shared seed data — avoid cross-test races on the same tickets
  workers: 1,
  retries: 0,
  reporter: [
    ["list"],
    ["json", { outputFile: "e2e-reports/last-run.json" }],
    ["html", { outputFolder: "e2e-reports/html", open: "never" }],
  ],
  use: {
    baseURL: "http://localhost:3000",
    // Video recording is the heaviest per-test resource cost and this machine
    // is memory-constrained while running the full 5-service dev stack
    // alongside the user's own browser — trace-on-failure alone is enough to
    // diagnose a failure without video's overhead.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    launchOptions: {
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
