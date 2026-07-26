import { test, expect } from "./helpers";

test.describe("Citizen status page (public, no auth)", () => {
  test("loads without any authentication cookie", async ({ sharedPage: page }) => {
    await page.context().clearCookies();
    await page.goto("/status/ANON-TEST");
    await expect(page.getByRole("heading", { name: /complaint status/i })).toBeVisible();
  });

  test("ROLE-11: shows UniServe branding even for an unknown reference", async ({ sharedPage: page }) => {
    await page.goto("/status/ANON-DOES-NOT-EXIST");
    await expect(page.getByText("UniServe")).toBeVisible();
    await expect(page.getByText(/no record found/i)).toBeVisible();
  });

  test("unknown reference shows a clear not-found message, not a crash", async ({ sharedPage: page }) => {
    const resp = await page.goto("/status/ANON-ZZZZ99");
    expect(resp?.status()).toBeLessThan(500);
    await expect(page.getByText(/no record found/i)).toBeVisible();
  });
});
