import { APIRequestContext, Page, test as base, expect } from "@playwright/test";

/**
 * This session's sandbox appears to cap concurrent Chromium child processes:
 * the default per-test browser context (a fresh context/process per test)
 * crashes deterministically on the *second* context's first page, regardless
 * of --no-sandbox/--disable-gpu. Rather than fight the environment, this
 * overrides `page` to a single WORKER-scoped context reused across every test
 * in the run (workers: 1 in playwright.config.ts, so that's one context for
 * the whole suite) — one browser context total instead of ~53. Every test
 * still exercises a real login/navigation, so this doesn't weaken what's
 * being tested, only how many OS-level contexts it costs to test it.
 */
/**
 * This session's sandbox reliably crashes Chromium (Windows access
 * violation) the moment a SECOND browser context is created in one OS
 * process — not gradually from memory growth, but specifically on that 2nd
 * `browser.newContext()` call, confirmed by testing a recycle-every-N-tests
 * variant that crashed immediately on its first recycle regardless of N. A
 * single context sustained 11 consecutive full-app navigations/logins with
 * no issue (proven in an earlier run). The fix lives in how the suite is
 * INVOKED, not here: run one spec file per `npx playwright test <file>`
 * CLI call (see reports/test-runs/ + the run script) so each file gets a
 * fresh OS process and exactly one context — every file in this suite has
 * ≤11 tests, at or under the proven-safe threshold. This fixture just
 * guarantees a single worker-scoped context per process, and never recycles.
 */
let currentPage: Page | null = null;

export const test = base.extend<{ sharedPage: Page }, {}>({
  sharedPage: async ({ browser }, use) => {
    if (!currentPage) {
      const context = await browser.newContext();
      currentPage = await context.newPage();
    }
    await use(currentPage);
  },
});
export { expect };

export const CREDS = {
  admin: { email: "admin@tneb.demo", password: "Admin@123", role: "admin" },
  lead: { email: "lead@uniserv.com", password: "Lead@123", role: "lead" },
  agent: { email: "agent@tneb.demo", password: "Agent@123", role: "agent" },
} as const;

export type RoleKey = keyof typeof CREDS;

/** Logs in via the real UI form (not an API shortcut) so auth-flow bugs are caught too. */
export async function loginAsUI(page: Page, role: RoleKey) {
  const { email, password } = CREDS[role];
  await page.goto("/login");
  await page.getByPlaceholder("Email").fill(email);
  await page.getByPlaceholder("Password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL("**/dashboard");
}

/** Faster login via the same BFF route the UI form calls — used in specs where the
 * login flow itself isn't what's under test, to keep the suite's wall-clock down. */
export async function loginViaApi(request: APIRequestContext, role: RoleKey) {
  const { email, password } = CREDS[role];
  const resp = await request.post("/api/auth/login", { data: { email, password } });
  expect(resp.ok(), `login as ${role} should succeed`).toBeTruthy();
  return resp;
}

/** Fetch a ticket id whose current status matches `status`, scoped to confirmed
 * identity, via the authenticated ticket-list BFF route. Picks dynamically so
 * tests stay valid even as seed data is mutated by earlier test runs. */
export async function findTicketByStatus(
  request: APIRequestContext,
  status: string,
): Promise<{ id: string; ticketNumber: string } | null> {
  const resp = await request.get(
    `/api/tickets?identityStatus=confirmed&page=1&pageSize=100&sortBy=createdAt&sortDir=desc`,
  );
  const data = await resp.json();
  const match = (data.tickets ?? []).find((t: any) => t.status === status);
  return match ? { id: match.id, ticketNumber: match.ticket_number } : null;
}

export async function findUnassignedOpenTicket(request: APIRequestContext) {
  const resp = await request.get(
    `/api/tickets?identityStatus=confirmed&page=1&pageSize=100&sortBy=createdAt&sortDir=desc`,
  );
  const data = await resp.json();
  const match = (data.tickets ?? []).find((t: any) => t.status === "open" && !t.assigned_to);
  if (!match) throw new Error("No unassigned open ticket found in seed data — cannot run lifecycle test");
  return { id: match.id, ticketNumber: match.ticket_number };
}
