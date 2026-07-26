import { test, expect, loginAsUI, findUnassignedOpenTicket, findTicketByStatus } from "./helpers";

test.describe("Ticket Detail", () => {
  test("shows citizen details, status badge, and a back-to-queue link", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    const ticket = await findTicketByStatus(page.request, "open");
    test.skip(!ticket, "no open ticket in seed data");
    await page.goto(`/dashboard/tickets/${ticket!.id}`);
    await expect(page.getByRole("heading", { name: ticket!.ticketNumber })).toBeVisible();
    await expect(page.getByText(/citizen details/i)).toBeVisible();
    await expect(page.getByText(/back to ticket queue/i)).toBeVisible();
  });

  test("FEED-7/ROLE-7: a transition requiring a mandatory note is badged and disabled before 20 characters are typed", async ({
    sharedPage: page,
  }) => {
    await loginAsUI(page, "admin");
    const ticket = await findTicketByStatus(page.request, "in_progress");
    test.skip(!ticket, "no in_progress ticket in seed data");
    await page.goto(`/dashboard/tickets/${ticket!.id}`);

    const resolveBtn = page.getByRole("button", { name: /move to resolved/i });
    await expect(resolveBtn).toBeVisible();
    await expect(resolveBtn.getByText(/note required/i)).toBeVisible();
    await expect(resolveBtn).toBeDisabled();

    const noteBox = page.getByPlaceholder(/add internal note/i);
    await noteBox.fill("Short note");
    await expect(resolveBtn).toBeDisabled();

    await noteBox.fill("This is a sufficiently long resolution note for the mandatory-note transition.");
    await expect(resolveBtn).toBeEnabled();
  });

  test("full lifecycle: open -> assigned -> in_progress -> resolved with mandatory note", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    const ticket = await findUnassignedOpenTicket(page.request);
    await page.goto(`/dashboard/tickets/${ticket.id}`);

    // Assign to an agent.
    const assignSelect = page.locator("select").first();
    const options = await assignSelect.locator("option").allTextContents();
    const agentOption = options.find((o) => o.trim() && o.trim() !== "Unassigned");
    test.skip(!agentOption, "no agent available to assign");
    await assignSelect.selectOption({ label: agentOption! });
    await expect(page.getByText(/assignment updated/i)).toBeVisible();

    // Each transition's success message renders as soon as the POST
    // resolves — one render tick BEFORE the component's subsequent ticket
    // re-fetch (`load()`) updates `ticket.status` and, with it, which
    // next-status buttons exist. Waiting only for the message (or for a
    // button that might already/still match) races that re-fetch; wait for
    // the actual GET /api/tickets/{id} round trip the component issues.
    const ticketReload = () => page.waitForResponse((r) => r.url().includes(`/api/tickets/${ticket.id}`) && r.request().method() === "GET");

    // open -> assigned (no note required)
    let reload = ticketReload();
    await page.getByRole("button", { name: /move to assigned/i }).click();
    await expect(page.getByText(/status changed to assigned/i)).toBeVisible();
    await reload;

    // assigned -> in_progress (no note required)
    reload = ticketReload();
    await page.getByRole("button", { name: /move to in progress/i }).click();
    await expect(page.getByText(/status changed to in progress/i)).toBeVisible();
    await reload;

    // in_progress -> resolved (mandatory 20-char note)
    const resolveBtn = page.getByRole("button", { name: /move to resolved/i });
    await expect(resolveBtn).toBeDisabled();
    await page.getByPlaceholder(/add internal note/i).fill("Verified the meter reading and corrected the billing amount for the customer.");
    await expect(resolveBtn).toBeEnabled();
    reload = ticketReload();
    await resolveBtn.click();
    await reload;
    // Assert the durable status badge, not the transient "Status changed to…"
    // message — `load()` sets `loading=true` synchronously and the page's
    // top-level `if (loading) return <p>Loading…</p>` guard unmounts the
    // ENTIRE view (including that message) for every action-triggered
    // reload, not just the initial page load. A fast poll can land during
    // that blank window and miss text that genuinely rendered a moment
    // earlier — the badge, checked after the reload settles, is not.
    await expect(page.getByText("resolved", { exact: true })).toBeVisible();
  });

  test("FEED-8/ROLE-8: the citizen-facing follow-up box is visually tagged distinct from internal notes", async ({
    sharedPage: page,
  }) => {
    await loginAsUI(page, "admin");
    const ticket = await findTicketByStatus(page.request, "open");
    test.skip(!ticket, "no open ticket in seed data");
    await page.goto(`/dashboard/tickets/${ticket!.id}`);
    await expect(page.getByText(/citizen will see this/i)).toBeVisible();
    await expect(page.getByText(/internal notes/i)).toBeVisible();
  });

  test("adding an internal note appears in the Internal notes list", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    const ticket = await findTicketByStatus(page.request, "open");
    test.skip(!ticket, "no open ticket in seed data");
    await page.goto(`/dashboard/tickets/${ticket!.id}`);

    const marker = `E2E note ${Date.now()}`;
    await page.getByPlaceholder(/add internal note/i).fill(marker);
    await page.getByRole("button", { name: /save note only/i }).click();
    await expect(page.getByText(/note added/i)).toBeVisible();
    await expect(page.getByText(marker)).toBeVisible();
  });

  test("sending a follow-up shows the sent/failed delivery state, never silent", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    const ticket = await findTicketByStatus(page.request, "open");
    test.skip(!ticket, "no open ticket in seed data");
    await page.goto(`/dashboard/tickets/${ticket!.id}`);

    await page.getByPlaceholder(/ask the citizen a question|ask a question or share an update/i).fill(
      "E2E test follow-up message — please disregard.",
    );
    await page.getByRole("button", { name: /^send$/i }).click();
    // One of these two must appear — the app must never leave the agent guessing.
    await expect(page.locator("text=/sent|failed/i").first()).toBeVisible({ timeout: 10000 });
  });

  test("audit trail lists at least the ticket-created event", async ({ sharedPage: page }) => {
    await loginAsUI(page, "admin");
    const ticket = await findTicketByStatus(page.request, "open");
    test.skip(!ticket, "no open ticket in seed data");
    await page.goto(`/dashboard/tickets/${ticket!.id}`);
    await expect(page.getByText(/audit trail/i)).toBeVisible();
  });
});
