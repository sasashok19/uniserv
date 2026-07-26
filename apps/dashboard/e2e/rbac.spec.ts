import { test, expect, loginAsUI } from "./helpers";

test.describe("RBAC — role-gated navigation and queue scoping", () => {
  test("admin sees Analytics, Ticket Queue, and Administration in the sidebar", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await expect(page.getByRole("button", { name: /analytics/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /ticket queue/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /administration/i })).toBeVisible();
  });

  test("NAV-1: admin's Administration nav item is present immediately on first paint (no pop-in)", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    // Assert visibility with a very tight timeout — if the cookie read were still
    // deferred to a useEffect (the pre-fix bug), this would be flaky/absent here.
    await expect(page.getByRole("button", { name: /administration/i })).toBeVisible({ timeout: 500 });
  });

  test("lead sees Analytics and Ticket Queue but NOT Administration", async ({ sharedPage: page }) => {
    await loginAsUI(page, "lead");
    await expect(page.getByRole("button", { name: /analytics/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /ticket queue/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /administration/i })).toHaveCount(0);
  });

  test("agent sees Analytics and Ticket Queue but NOT Administration", async ({ sharedPage: page }) => {
    await loginAsUI(page, "agent");
    await expect(page.getByRole("button", { name: /analytics/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /ticket queue/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /administration/i })).toHaveCount(0);
  });

  test("admin/lead see the Confirmed vs Needs-identity scope toggle; agent does not", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await expect(page.getByRole("button", { name: /^confirmed$/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /needs identity/i })).toBeVisible();
  });

  test("agent queue is scoped server-side to their own tickets (no scope toggle, assignedTo=me)", async ({ sharedPage: page }) => {
    let sawAssignedToMe = false;
    page.on("request", (req) => {
      if (req.url().includes("/api/tickets?") && req.url().includes("assignedTo=me")) sawAssignedToMe = true;
    });
    await loginAsUI(page, "agent");
    await expect(page.getByRole("button", { name: /^confirmed$/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /needs identity/i })).toHaveCount(0);
    await expect.poll(() => sawAssignedToMe).toBeTruthy();
  });

  test("direct navigation to /dashboard/tickets/[id] works for any authenticated role", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    // Use page.request (shares the page's session cookies) — the standalone
    // `request` fixture is an unauthenticated context and would 401/return empty.
    const resp = await page.request.get("/api/tickets?identityStatus=confirmed&page=1&pageSize=1");
    const data = await resp.json();
    const id = data.tickets[0].id;
    await page.goto(`/dashboard/tickets/${id}`);
    await expect(page.getByText(/back to ticket queue/i)).toBeVisible();
  });
});
