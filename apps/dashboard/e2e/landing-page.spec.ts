import { test, expect, loginAsUI } from "./helpers";

/**
 * Landing page (Feature 25): the public page renders tenant-configured copy,
 * and Administration → Landing Page edits it.
 *
 * Note the ISR window — `/` revalidates every 60s, so a save is NOT visible on
 * the public page immediately. The save test therefore asserts the admin round
 * trip (which is synchronous) rather than racing the public page; the render
 * tests below assert structure and defaults, which do not move.
 */

test.describe("Landing page (public, no auth)", () => {
  test("renders the hero, the track box and the sections without a session", async ({
    sharedPage: page,
  }) => {
    await page.context().clearCookies();
    await page.goto("/");

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: /track your complaint/i })).toBeVisible();
    await expect(page.getByPlaceholder(/TKT-|ANON-/i)).toBeVisible();
  });

  test("agent sign in is reachable from the header, the hero and the footer", async ({
    sharedPage: page,
  }) => {
    // The reported problem was that this link was effectively invisible. Three
    // placements now point at /login; all must survive a re-word.
    await page.goto("/");
    const signIn = page.locator('a[href="/login"]');
    expect(await signIn.count()).toBeGreaterThanOrEqual(3);
    await expect(signIn.first()).toBeVisible();
  });

  test("the About / How it works / Contact sections render below the hero", async ({
    sharedPage: page,
  }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /about/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /how it works/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /contact/i })).toBeVisible();
  });

  test("the track form rejects an empty submit without navigating", async ({
    sharedPage: page,
  }) => {
    // Pure client-side guard, so this holds with or without the backend.
    await page.goto("/");
    await page.getByRole("button", { name: /track/i }).click();
    await expect(page.getByText(/enter your reference number or email/i)).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/");
  });

  test("the track form still routes a reference to the status page", async ({
    sharedPage: page,
  }) => {
    // Feature 25 moved this form into its own client component -- prove the
    // rewire did not break the one thing the page exists to do.
    //
    // NEEDS THE DEV STACK: /status/[ref] is server-rendered from the gateway
    // and 500s without it, which aborts the client-side push before the URL
    // commits. `waitUntil: "commit"` still catches a hard navigation, but with
    // no backend at all this test cannot pass -- as with the rest of this
    // suite (see playwright.config.ts), run it against scripts/dev.sh.
    await page.goto("/");
    await page.getByPlaceholder(/TKT-|ANON-/i).fill("ANON-TEST");
    await page.getByRole("button", { name: /track/i }).click();
    await page.waitForURL("**/status/ANON-TEST", { waitUntil: "commit" });
  });

  test("renders even when the page has never been configured", async ({ sharedPage: page }) => {
    // Defaults come from the gateway, but an unreachable gateway must still
    // produce complete copy rather than a page of blanks.
    const resp = await page.goto("/");
    expect(resp?.status()).toBeLessThan(500);
    await expect(page.getByRole("heading", { level: 1 })).not.toHaveText("");
  });
});

test.describe("Administration — Landing Page", () => {
  test("loads the current content pre-filled", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /landing page/i }).click();

    await expect(page.getByLabel("Brand name")).not.toHaveValue("");
    await expect(page.getByLabel("Tagline")).not.toHaveValue("");
  });

  test("saves a re-worded tagline", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /landing page/i }).click();

    await page.getByLabel("Tagline").fill("The complaint that gets heard.");
    await page.getByRole("button", { name: /save changes/i }).click();
    await expect(page.getByText(/saved/i)).toBeVisible();
  });

  test("a cleared field comes back as its default rather than blank", async ({
    sharedPage: page,
  }) => {
    // Blank means "use the default" -- the panel must visibly repaint with the
    // default so an admin is never left thinking they blanked the live page.
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /landing page/i }).click();

    await page.getByLabel("Brand name").fill("");
    await page.getByRole("button", { name: /save changes/i }).click();
    await expect(page.getByText(/saved/i)).toBeVisible();
    await expect(page.getByLabel("Brand name")).toHaveValue("UniServe");
  });

  test("rejects a logo URL that is not a path or an http(s) URL", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /landing page/i }).click();

    await page.getByLabel("Logo URL").fill("javascript:alert(1)");
    await page.getByRole("button", { name: /save changes/i }).click();
    await expect(page.getByText(/logoUrl|must be a same-origin path/i)).toBeVisible();
  });

  test("an extra section can be added and removed", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /landing page/i }).click();

    await page.getByRole("button", { name: /add section/i }).click();
    await expect(page.getByText(/^Section 1$/)).toBeVisible();
    await page.getByRole("button", { name: /^remove$/i }).first().click();
    await expect(page.getByText(/no extra sections yet/i)).toBeVisible();
  });
});
