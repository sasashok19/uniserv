# UniServe Dashboard — E2E Test Report (Playwright)

**Date:** 2026-07-26
**Scope:** Full RBAC and functional-flow regression suite for the dashboard, written and run against the local dev stack (`scripts/dev.sh`, `RUN_MODE=local`) after implementing the fixes from `reports/ui-review-report.md`.
**Final result: 53/53 tests passing (100%)**, confirmed reproducible across two consecutive full passes (`run-09`, `run-10-final`).

---

## Summary

| Run | Scope | Result |
|---|---|---|
| run-01 | Full suite, one browser context per test (Playwright default) | 40 passed / 7 failed / 6 skipped — all 7 failures were test-authoring bugs (ambiguous locators, unauthenticated API helper calls), not app bugs |
| run-02 – run-05 | Full suite, various Chromium launch-flag attempts (`video:off`, `--no-sandbox`, `--single-process`) | Environment crash: Chromium reliably hard-crashes (Windows access violation, `0xC0000005`) on the 2nd browser context created in the process — a sandbox/resource constraint of this session, not an app or test defect |
| run-06 – run-08 | Full suite, single shared context (worker-scoped), then context-recycling variants | Confirmed: exactly one context per OS process is stable; ANY 2nd `browser.newContext()` call crashes it, regardless of when. A single context sustained 11 consecutive full-app navigations before an unrelated memory-driven crash appeared further in |
| **run-09** | **Architecture fix: one spec file per CLI invocation** (fresh OS process per file, one context per file — every file has ≤11 tests) | **52/53 passed**, 1 real test bug found (locator ambiguity) + 1 real test-timing bug found (see below) |
| **run-10-final** | Full re-run after fixing both bugs found in run-09 | **53/53 passed** — confirms the fix, not a fluke |

**Test-data issues found and fixed *before* the first real run** (per the "ensure no challenge with test data" instruction):
- The seeded "Lead" account's actual email (`lead@uniserv.com`) didn't match the password on file for the documented credential (`Lead@123` rejected) — reset via the admin password-reset API (`PATCH /api/agents/{id}/password`) to the documented value. Non-destructive: no data deleted, just a known password re-established for automation.
- Confirmed real seed-data shape via direct API calls before writing tests (agent roster, ticket status distribution, announcement/intake-field/rubric state) rather than guessing, so tests query for tickets by status dynamically (`findTicketByStatus`, `findUnassignedOpenTicket`) instead of hardcoding IDs that would go stale as tests mutate data.

---

## Environment issue encountered, root-caused, and resolved

This machine has a very tight memory ceiling while running the full 5-service dev stack (Valkey/db-writer/api-gateway/ai-core/dashboard) alongside the user's own browser (~1-1.2GB free out of 8GB observed). Playwright's default behavior — a fresh browser context per test — crashed Chromium deterministically on the *second* context created in a process, independent of `--no-sandbox`, `--disable-gpu`, or `--single-process` (the last of which made things worse — Chromium refused to launch at all).

**Root cause, confirmed by elimination:** this session's process sandbox cannot sustain more than one Chromium browser context per OS process. It is not a gradual memory leak (recycling contexts every 5 tests crashed immediately on the first recycle) and not fixable via launch flags (tried the standard `--no-sandbox`/`--disable-setuid-sandbox`/`--single-process` combinations used for constrained CI/container environments).

**Fix:** restructured `e2e/helpers.ts` to hold a single worker-scoped browser context for the life of one CLI invocation (`test.extend`, no fixture re-creation), and run each spec file as its **own separate `npx playwright test <file>` process** rather than one combined run. Every file in this suite has ≤11 tests — at or under the threshold a single context was independently proven to sustain. This is now the supported way to run this suite (see `apps/dashboard/e2e/helpers.ts`'s header comment for the full reasoning, kept in-code so it isn't lost).

**Also encountered:** this session's background-task notification system fired premature/incorrect "killed" statuses for several long-running commands whose underlying process was, on inspection (`tasklist`, `wmic process`), still alive and still producing output. All conclusions in this report are based on directly reading the actual log files and process state, not on trusting those notifications.

---

## Real bugs found by the test suite (not environment noise)

Two genuine issues were found and fixed during the run-fix-rerun loop — both are legitimate findings, documented here for transparency:

1. **Test bug (not an app bug):** `admin-team.spec.ts`'s "editing an agent's name" test asserted `getByText("Renamed via E2E")`, which matched *two* elements — the intended table cell and the success banner ("Renamed via E2E's details were updated."), since the banner text contains the same substring. Fixed by scoping the assertion to the table.

2. **Real, minor application UX issue, confirmed via the app's own audit trail data (`PERF-9` in `reports/ui-review-report.md`):** `TicketDetailPage`'s `load()` function sets `loading=true` synchronously on every re-fetch — including reloads triggered by actions (status transitions, assign, note-save, reply-send), not just the initial page mount. The component's top-level `if (loading) return <p>Loading…</p>` guard unmounts the *entire* ticket detail view during that window, briefly wiping the very success message the action just triggered. This intermittently made a `status changed to resolved` assertion fail even though the transition had genuinely succeeded (verified via the ticket's own audit-trail log). Fixed the test to wait for the actual reload network round-trip and assert on the durable status badge instead of the transient message; the underlying app behavior is now logged as `PERF-9` (P2, deferred) in the UI review report with a concrete fix recommendation (give `load()` the same `background` parameter the ticket queue's own reload already uses, so action-triggered reloads don't blank the page).

No other real application defects were found — every other failure across all 10 runs traced back to either the environment crash (resolved via the per-file-process architecture) or a test-authoring bug (ambiguous locators, unauthenticated `request` fixture usage) fixed during the loop.

---

## Coverage

**Covered (53 tests across 8 files):**
- **Authentication** (`auth.spec.ts`, 6 tests): all 3 role logins, wrong-password handling, focus/border error styling, logout.
- **RBAC** (`rbac.spec.ts`, 7 tests): admin/lead/agent nav visibility, the Confirmed/Needs-identity scope toggle's role-gating, agent server-side `assignedTo=me` scoping, first-paint nav-flash regression (NAV-1), direct ticket-detail navigation.
- **Ticket Queue** (`ticket-queue.spec.ts`, 11 tests): default sort (ROLE-3 fix), scope toggle, column sort/`aria-sort`, `scope="col"`, pagination, manual refresh, "last updated" caption (PERF-4), priority dot (VIS-5), channel icon (VIS-7), brand-color consistency (VIS-2), scope-aware empty state (FEED-4).
- **Ticket Detail** (`ticket-detail.spec.ts`, 7 tests): citizen details, the mandatory-note badge/disable logic (FEED-7/ROLE-7), a full status lifecycle (open→assigned→in_progress→resolved) with the 20-char mandatory note, the citizen-facing-vs-internal visual distinction (FEED-8/ROLE-8), internal note add, follow-up send with delivery confirmation, audit trail.
- **Analytics** (`analytics.spec.ts`, 4 tests): all 4 chart cards for admin, agent-performance restriction for agents, filter re-fetching.
- **Administration — Team** (`admin-team.spec.ts`, 4 tests): on-blur validation (FEED-3), agent creation, agent editing, table `scope="col"` (A11Y-4).
- **Administration — other panels** (`admin-panels.spec.ts`, 11 tests): Intake Fields, Priority Rules (+ focus ring, A11Y-1), General Settings (valid + invalid input), Announcements (create, modal Escape/focus-return A11Y-8, and the FEED-2 `resp.ok` regression test via route interception), System health display, and the Reset Database modal's Escape-to-close-while-idle + wrong-password-rejection path.
- **Citizen status page** (`citizen-status.spec.ts`, 3 tests): unauthenticated load, branding on an unknown ref (ROLE-11), non-crashing not-found handling.

**Deliberately NOT exercised (by design, not oversight):**
- **The destructive DB reset's success path.** The suite verifies the modal's Escape/keyboard behavior and wrong-password rejection, but never submits a *correct* password — doing so would wipe all tenant data (tickets, identities, notes, announcements, non-admin agents), destroying the seed data every other test in this suite (and the user's own manual testing) depends on. This is a deliberate, permanent exclusion for this suite, not a gap to close later.
- **Any test that would require guessing or fabricating a valid anonymous citizen reference** for the status page's "found" path — the anon_ref_id isn't exposed via any authenticated API this suite has credentials for, and triggering the live email/WhatsApp AI pipeline to generate one is out of scope for a UI E2E suite. Only the "not found" path is covered for that page's data-driven state; the SSR/branding/error-handling behavior is otherwise fully covered.
- **VIS-10 (Resolution field)** — not implemented in the app yet (a real backend gap, documented in the UI review report), so nothing to test.

---

## How to re-run this suite

```bash
cd apps/dashboard
# Ensure the dev stack is running first: ../../scripts/dev.sh (RUN_MODE=local)
for f in admin-panels admin-team analytics auth citizen-status rbac ticket-detail ticket-queue; do
  npx playwright test "e2e/${f}.spec.ts"
done
```

Do not run `npx playwright test` (all files at once) without modification in this environment — see the crash root-cause above. If run on a machine without this session's process-sandbox constraint, the single combined command should work fine; the per-file split is a workaround for this environment specifically, not a permanent architectural requirement.

Per-run raw logs are preserved in `reports/test-runs/run-01-raw.log` through `run-10-final/*.log` for audit purposes.
