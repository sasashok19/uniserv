import { test, expect, loginAsUI } from "./helpers";

test.describe("Analytics", () => {
  test("admin sees all 4 chart cards including Agent performance", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /analytics/i }).click();
    await expect(page.getByText(/ticket volume/i)).toBeVisible();
    await expect(page.getByText(/sla performance/i)).toBeVisible();
    await expect(page.getByText(/priority distribution/i)).toBeVisible();
    await expect(page.getByText(/agent performance/i)).toBeVisible();
  });

  test("agent does NOT see Agent performance data (view-only restriction)", async ({ sharedPage: page }) => {
    await loginAsUI(page, "agent");
    await page.getByRole("button", { name: /analytics/i }).click();
    await expect(page.getByText(/visible to leads and admins only/i)).toBeVisible();
  });

  test("time-frame filter change re-fetches data", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /analytics/i }).click();
    let refetched = false;
    page.on("request", (req) => {
      if (req.url().includes("/api/analytics/volume") && req.url().includes("period=90d")) refetched = true;
    });
    await page.locator("select").first().selectOption("90d");
    await expect.poll(() => refetched).toBeTruthy();
  });

  test("priority filter narrows results without erroring", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /analytics/i }).click();
    const prioritySelect = page.locator("select").filter({ hasText: /all priorities/i });
    await prioritySelect.selectOption("critical");
    // No crash / error text should appear.
    await expect(page.getByText(/error/i)).toHaveCount(0);
  });
});
