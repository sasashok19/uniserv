import { test, expect, CREDS, loginAsUI } from "./helpers";

test.describe("Authentication", () => {
  test("admin can log in and lands on dashboard", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await expect(page).toHaveURL(/\/dashboard/);
    // Role pill lives in the topbar <header> — scope there since the seeded
    // agent's own NAME is literally "Agent", which also appears as queue-table
    // "Assigned to" cell text and would otherwise make this locator ambiguous.
    await expect(page.locator("header").getByText(/^admin$/i)).toBeVisible();
  });

  test("lead can log in and lands on dashboard", async ({ sharedPage: page }) => {
    await loginAsUI(page, "lead");
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.locator("header").getByText(/^lead$/i)).toBeVisible();
  });

  test("agent can log in and lands on dashboard", async ({ sharedPage: page }) => {
    await loginAsUI(page, "agent");
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.locator("header").getByText(/^agent$/i)).toBeVisible();
  });

  test("wrong password shows an inline error and does not navigate", async ({ sharedPage: page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("Email").fill(CREDS.admin.email);
    await page.getByPlaceholder("Password").fill("wrong-password-123");
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByText(/invalid email or password/i)).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("FEED-10/A11Y-1: wrong password reddens input borders and inputs keep a visible focus ring", async ({ sharedPage: page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("Email").fill(CREDS.admin.email);
    await page.getByPlaceholder("Password").fill("wrong-password-123");
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByText(/invalid email or password/i)).toBeVisible();
    const emailInput = page.getByPlaceholder("Email");
    await expect(emailInput).toHaveClass(/border-red-400/);
    // Focus-visible ring class should be present in the className (A11Y-1 fix).
    await expect(emailInput).toHaveClass(/focus-visible:ring-2/);
  });

  test("logout clears the session and redirects to login", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /logout/i }).click();
    await expect(page).toHaveURL(/\/login/);
    // A subsequent direct visit to /dashboard without a session should not show admin-only content.
    await page.goto("/dashboard");
    await expect(page.getByText(/administration/i)).toHaveCount(0);
  });
});
