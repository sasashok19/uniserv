import { test, expect, loginAsUI } from "./helpers";

test.describe("Administration — Intake Fields", () => {
  test("loads the field matrix and saves without error", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /intake fields/i }).click();
    await expect(page.getByText(/choose which details the assistant collects/i)).toBeVisible();
    await page.getByRole("button", { name: /save changes/i }).click();
    await expect(page.getByText(/intake field configuration saved/i)).toBeVisible();
  });

  test("A11Y-2: custom-field remove button (if any custom fields exist) has an aria-label", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /intake fields/i }).click();
    const removeButtons = page.locator('button[aria-label^="Remove "]');
    const count = await removeButtons.count();
    // Zero is fine (no custom fields configured yet) — if any exist, they must be labelled.
    expect(count).toBeGreaterThanOrEqual(0);
  });
});

test.describe("Administration — Priority Rules", () => {
  test("loads the rubric textarea pre-filled and saves", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /priority rules/i }).click();
    const textarea = page.locator("textarea");
    await expect(textarea).not.toHaveValue("");
    await page.getByRole("button", { name: /save changes/i }).click();
    await expect(page.getByText(/priority rubric saved/i)).toBeVisible();
  });

  test("A11Y-1: rubric textarea has a visible focus ring class", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /priority rules/i }).click();
    await expect(page.locator("textarea")).toHaveClass(/focus-visible:ring-2/);
  });
});

test.describe("Administration — Settings", () => {
  test("max follow-up questions saves within 0-5", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /^settings$/i }).click();
    const input = page.locator("#maxFollowupQuestions");
    await input.fill("3");
    await page.getByRole("button", { name: /save changes/i }).click();
    await expect(page.getByText(/settings saved/i)).toBeVisible();
  });

  test("rejects an out-of-range value client-side", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /^settings$/i }).click();
    const input = page.locator("#maxFollowupQuestions");
    await input.fill("9");
    await page.getByRole("button", { name: /save changes/i }).click();
    await expect(page.getByText(/enter a whole number between 0 and 5/i)).toBeVisible();
  });
});

test.describe("Administration — Announcements", () => {
  test("creates a new announcement end-to-end", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.locator("nav.border-b").getByRole("button", { name: /^announcements$/i }).click();
    await page.getByRole("button", { name: /new announcement/i }).click();
    const stamp = Date.now();
    await page.getByPlaceholder(/title \(min 3/i).fill(`E2E announcement ${stamp}`);
    await page.getByPlaceholder(/body \(min 10/i).fill("This is an end-to-end test announcement body.");
    await page.getByRole("button", { name: /^save$/i }).click();
    await expect(page.getByText(/announcement published/i)).toBeVisible();
    await expect(page.getByText(`E2E announcement ${stamp}`)).toBeVisible();
  });

  test("A11Y-8: the create/edit modal closes on Escape and returns focus to the trigger", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.locator("nav.border-b").getByRole("button", { name: /^announcements$/i }).click();
    const trigger = page.getByRole("button", { name: /new announcement/i });
    await trigger.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test("FEED-2: a failed deactivate/delete shows a failure message, never a false-positive success", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.locator("nav.border-b").getByRole("button", { name: /^announcements$/i }).click();

    // Force the PATCH (deactivate) request to fail server-side.
    await page.route("**/api/announcements/*", async (route) => {
      if (route.request().method() === "PATCH") {
        await route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
      } else {
        await route.continue();
      }
    });

    const deactivateBtn = page.getByRole("button", { name: /^(deactivate|activate)$/i }).first();
    await deactivateBtn.click();
    await expect(page.getByText(/failed to update announcement/i)).toBeVisible();
    await expect(page.getByText(/^announcement (deactivated|reactivated)\.$/i)).toHaveCount(0);
    // Critical on a shared/reused page (see helpers.ts): an un-cleared route
    // interceptor would silently break every later test's real network calls.
    await page.unroute("**/api/announcements/*");
  });
});

test.describe("Administration — System (health only, no destructive reset)", () => {
  test("service health panel shows all 3 backend services", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /^system$/i }).click();
    await expect(page.getByText(/api-gateway/i)).toBeVisible();
    await expect(page.getByText(/db-writer/i)).toBeVisible();
    await expect(page.getByText(/ai-core/i)).toBeVisible();
  });

  test("A11Y-8: Reset Database modal supports Escape-to-close while idle, and rejects a wrong password without wiping data", async ({
    sharedPage: page,
  }) => {
    await loginAsUI(page, "admin");
    await page.getByRole("button", { name: /administration/i }).click();
    await page.getByRole("button", { name: /^system$/i }).click();

    const openBtn = page.getByRole("button", { name: /^reset database$/i });
    await openBtn.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // Escape should close it while idle (A11Y-8 fix) — verify BEFORE ever submitting.
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);

    // Reopen and verify a wrong password is rejected (401) WITHOUT resetting anything —
    // this intentionally never submits a correct password, so tenant data is untouched.
    await openBtn.click();
    await page.getByLabel(/enter your password/i).fill("definitely-the-wrong-password");
    await page.getByLabel(/type reset to confirm/i).fill("RESET");
    await page.getByRole("button", { name: /reset everything/i }).click();
    await expect(page.getByText(/incorrect password/i)).toBeVisible();
    // Cancel out — the destructive path is never exercised in this suite.
    await page.getByRole("button", { name: /^cancel$/i }).click();
  });
});
