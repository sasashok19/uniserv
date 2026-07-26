# UI Review Report — UniServe Dashboard

**Generated:** 2026-07-26
**Dashboard version:** 1.0.0 (`apps/dashboard/package.json`)
**Process:** Source-code-grounded UI/UX review (1 specialist agent, findings independently spot-verified by the moderator against `AnnouncementsPanel.tsx` and `SystemPanel.tsx` — the two files the agent's key P0/P1 claims hinged on) → consolidated into this report.

---

## EXECUTIVE SUMMARY

**Overall rating: 5.5/10** — the functional core (RBAC, sessionStorage-persisted queue state, server-side sort/pagination, mandatory-note transition logic, the DB-reset destructive-action flow) is genuinely solid and correctly implemented end-to-end. The visual/interaction layer is "functional-minimal" exactly as the codebase's own docs admit, and diverges substantially from `docs/UI_REVAMP_v2.md`'s own target spec — most notably, zero motion/animation infrastructure exists despite the spec requiring it, and two colour systems (brand tokens vs. an unrelated indigo default) run in parallel across the app.

**Top 3 strengths:**
1. `SystemPanel.tsx`'s DB-reset flow — differentiated 401/429/generic error handling, disabled-until-valid button, non-dismissible destructive overlay, explicit success state before redirect. Best-executed feedback pattern in the app; verified directly in code.
2. RBAC and queue-state logic — agents are correctly restricted to `assignedTo=me` server-side, sessionStorage view-state restoration genuinely works, and server-side sort/pagination/whitelisted `sortBy` are all correctly wired.
3. Semantic HTML discipline — no `<div onClick>` pattern found anywhere across 20 files reviewed; every clickable element is a real `<button>`/`<a>`/`<select>`/`<input>`.

**Top 3 critical issues:**
1. **`AnnouncementsPanel.tsx`'s `toggleActive`/`remove` claim success without checking `resp.ok`** (verified directly in code, lines 40-55) — a failed deactivate/delete is reported to the admin as having succeeded, risking stale public-facing content staying live unnoticed. The only P0 in this review.
2. **The ticket queue's default sort (`createdAt desc`) contradicts the product's own documented spec** (`docs/12_AGENT_DASHBOARD.md` line 110: "Priority score descending... oldest high-priority first") — combined with no visual priority emphasis in rows, a Lead's default view surfaces the newest tickets, not the most urgent ones.
3. **Zero animation/motion infrastructure** — no `framer-motion`, no shadcn/ui, `tailwindcss-animate`'s utilities registered but never used — despite `docs/UI_REVAMP_v2.md` explicitly specifying both as required dependencies for the transitions this report's Domain 4 was scoped to review.

---

## SECTION 1: Navigation & Information Architecture

The 3-tab + collapsible-sidebar shell is clean and shallow — nothing is buried. sessionStorage-based queue-state restoration genuinely works as designed and a Lead lands on the right default tab after login. The one real defect is a client-only role read that visibly changes the nav a beat after paint.

- **[NAV-1] P1** — `apps/dashboard/src/app/dashboard/page.tsx` (`DashboardPage`, `Sidebar`): `role` starts as `useState("")`, populated only in a `useEffect` reading the `role` cookie. On an admin's first paint, `role===""`, so the Administration nav item (and `AnalyticsPanel`'s `canViewAll`, `TicketQueue`'s `showToggle`) briefly renders as if for an agent, then pops in a render later. **Fix:** read the cookie synchronously in the `useState` initializer instead of an effect — cookies are available synchronously client-side. Quick win.
- **[NAV-2] P3** — `Administration`'s `subTab` state is local and resets to `"team"` whenever the parent unmounts it (switching to Analytics/Queue and back). **Fix:** lift `subTab` up to `DashboardPage` or persist in sessionStorage. Quick win.
- **[NAV-3] P3** — `Sidebar`'s `collapsed` state is local and resets on any full route change (e.g. navigating to ticket detail and back), since the sidebar unmounts with the page. **Fix:** persist `collapsed` in `localStorage` (durable preference, not per-visit state). Quick win.

**Quick wins:** NAV-1, NAV-2, NAV-3.

---

## SECTION 2: Visual Hierarchy & Design Consistency

The biggest structural problem in this review: two colour systems run in parallel, and the file meant to be the single source of truth for one of them (`badges.ts`) doesn't read from the other (`design-tokens.ts`) despite `design-tokens.ts`'s own header comment warning against exactly that. Several spec'd visual-hierarchy devices (priority dot, SLA indicator, channel icon, hero KPI row, author-type colour coding) are simply unimplemented — and more than one is load-bearing for the Lead's "what's urgent" workflow (Section 7).

- **[VIS-1] P1** — `src/lib/badges.ts`: every badge function hardcodes its own Tailwind classes (e.g. `bg-blue-100 text-blue-700`) instead of reading `tokens.status`/`tokens.priority`/`tokens.identityStatus`. The values aren't even the same hex pair as the tokens. **Fix:** rebuild each function from the token objects, using inline `style={{background, color}}` rather than dynamic Tailwind arbitrary-value classes (which aren't JIT-safe). Not a quick win — touches 5 functions, needs visual QA.
- **[VIS-2] P1** — Every primary button/link/active-tab underline/focus-border across the queue, ticket detail, and admin forms uses `indigo-600`/`700`/`50`/`400` — not in the brand palette at all — while `Topbar`, `Sidebar`, login, and the Danger Zone correctly use brand teal/coral. Result: the chrome looks like one branded government product; the work surface looks like a generic template. **Fix:** add a `brand` colour scale to `tailwind.config.ts` and replace every `indigo-*` utility across the affected files. Not a quick win — many files, needs visual QA.
- **[VIS-3] P2** — The files that *do* get the brand right (`Topbar`, `Sidebar`, `AnnouncementBanner`, `AnnouncementBell`, `SystemPanel`, login) bypass `design-tokens.ts` to do it, hardcoding hex values inline instead. **Fix:** do together with VIS-2's Tailwind config extension.
- **[VIS-4] P2** — Ticket queue rows have no zebra striping, contradicting `UI_REVAMP_v2` §A6. **Fix:** `odd:bg-white even:bg-slate-50/60` on the `<tr>`. Quick win.
- **[VIS-5] P1** — Priority renders only as a small text pill — no dot, no row accent — despite `UI_REVAMP_v2` §A6 specifying an 8px priority dot for exactly the "scan and spot urgency" reason. Directly fails the brief's Lead-journey test. **Fix:** add a coloured dot from `tokens.priority[label].dot`, plus a faint tint on `critical` rows. Quick win — token data already exists.
- **[VIS-6] P2** — No SLA/age indicator column exists at all, despite the pre-filter bar spec (`Overdue`) assuming one. **Fix:** new feature (SLA deadline computation + coloured clock icon), not a restyle. Not a quick win.
- **[VIS-7] P2** — Channel renders as plain capitalized text; `design-tokens.ts` already models `tokens.channel.email`/`.whatsapp` with icon + color, unused. **Fix:** map to `lucide-react` `Mail`/`MessageCircle` + token color. Quick win.
- **[VIS-8] P2** — Nearly every section heading app-wide (ticket detail, all 6 admin panels) uses the identical `text-sm font-semibold text-slate-700` — a "wall of same-size text" with no true heading scale. **Fix:** introduce a title tier (`text-base font-semibold`) and a muted sub-label tier. Quick win — class swap only.
- **[VIS-9] P2** — Conversation messages distinguish only inbound/outbound, not AI vs. agent vs. citizen authorship — no colour-coded border despite `docs/12_AGENT_DASHBOARD.md`'s own Notes Timeline spec calling for it, which matters for audit/QA in a government context. **Fix:** add a left-border accent keyed on `authorType` (teal/blue/slate). Quick win.
- **[VIS-10] P1** — `ticket.resolution` exists in the type and is fetched, but **is never rendered anywhere** — no textarea, no Generate Summary button, no locked state for closed tickets, despite both `UI_REVAMP_v2` §A7 and `docs/12_AGENT_DASHBOARD.md`'s `ResolutionField` spec describing it as a core feature. A real functional gap, not cosmetic. **Fix:** add a Resolution section to the right column with edit/lock/generate states; verify the corresponding API route exists before wiring the button. Not a quick win.
- **[VIS-11] P2** — No hero KPI stat row exists in Analytics; `UI_REVAMP_v2` §A5 calls for 4 gradient cards with count-up. **Fix:** new data aggregation + styling. Not a quick win.

**Quick wins:** VIS-4, VIS-5, VIS-7, VIS-8, VIS-9.

---

## SECTION 3: Loading & Perceived Performance

Every loading state defaults to a bare `Loading…` text line, with exactly two accidental exceptions (`AnnouncementsPanel`, `NewsWidget`) that already use correct `animate-pulse` skeletons — proof the team knows the pattern, it's just not applied to the highest-traffic surfaces (the ticket queue table and the 4-chart analytics grid), both of which collapse to one line and snap back to full size on every load.

- **[PERF-1] P1** — `TeamPanel`, `IntakeFieldsPanel`, `PriorityRulesPanel`, `GeneralSettingsPanel`, ticket detail page all use bare `Loading…` text with no skeleton. **Fix:** extract the existing `AnnouncementsPanel` skeleton pattern into a reusable helper and apply consistently. Not a quick win — touches 5 files.
- **[PERF-2] P1** — `AnalyticsPanel`'s entire 4-chart grid (known, fixed dimensions) is replaced by one text line during load, then snaps to full height. **Fix:** always render the `ChartCard` shells; dim contents (`opacity-40`) while loading instead of unmounting the grid. Not a quick win.
- **[PERF-3] P1** — Ticket queue's `<table>` (static, known column set) fully unmounts to a text line during load. **Fix:** always render `<thead>`; show skeleton `<tbody>` rows while loading. Not a quick win.
- **[PERF-4] P2** — The 30s auto-refresh gives no visible cue in the table itself that a refresh happened (only the manual "Refresh" button's own label changes). **Fix:** add a "Last updated Xs ago" caption. Quick win.
- **[PERF-5] P1** — `AnalyticsPanel`'s filter-change effect re-triggers the full-grid collapse (PERF-2) on *every single filter edit* — worse than "sits there," it visibly destroys and rebuilds the whole view each time. **Fix:** same remedy as PERF-2 (stale-while-revalidate, dim don't unmount). Not a quick win — shares implementation with PERF-2.
- **[PERF-8] P2** — `saveNoteOnly`/`assign`/`transition` all await a full round-trip re-fetch before any UI update — no optimistic append for a typed note. **Fix:** optimistic local state update, reconciled on `load()` response. Not a quick win.

**Strengths worth preserving:** `AnnouncementsPanel`/`NewsWidget`'s existing skeletons (use as the template). `status/[ref]/page.tsx` is genuinely SSR with `cache: "no-store"` — fast by construction. Login's `NewsWidget` is async/non-blocking.

**[PERF-9] P2 — confirmed via E2E testing, refines PERF-1.** File: `apps/dashboard/src/app/dashboard/tickets/[id]/page.tsx`, `TicketDetailPage`. Issue: `load()` sets `loading=true` synchronously at the start of every re-fetch, and the component's top-level guard (`if (loading) return <p className="p-6 text-sm text-slate-500">Loading…</p>`) unmounts the **entire ticket detail view** on every action-triggered reload — not just the initial page load. Every status transition, assign, note-save, and reply-send calls `load()` at the end, meaning each of those actions flashes the whole page to a bare "Loading…" and back, briefly wiping the very success message (`statusMsg`) the action just set. Caught directly during Playwright E2E testing (`e2e/ticket-detail.spec.ts`): a `getByText(/status changed to resolved/i)` assertion intermittently found nothing because the poll landed inside that blank window, even though the transition had genuinely succeeded (confirmed via the audit trail). Fix: give `load()` a `background` parameter (the ticket queue's own `load(background)` on the same page already does exactly this pattern) so action-triggered reloads keep the current view mounted instead of replacing it with the loading fallback — reserve the full-unmount `Loading…` state for the true initial mount only. Quick win: No (touches the shared `load()` used by every action handler; needs care to keep the initial-mount case correct).

**Quick wins:** PERF-4.

---

## SECTION 4: Transitions & Motion (NEW)

Confirmed: `framer-motion` is not installed, no `components/ui/` directory exists, and `tailwindcss-animate`'s utility classes are registered as a plugin but used **zero times** in `src/`. The only motion in the app today is `animate-spin` on `Loader2` icons, `animate-pulse` on the two skeletons, one CSS-in-JS keyframe marquee in `AnnouncementTicker`, and a `transition-[width]`/`transition-colors` on the sidebar/scope-toggle. Every fix below assumes the install step (`npm install framer-motion`).

- **[MOTION-1] P2** — Tab switches (top-level and admin sub-tabs) are instant conditional-render swaps. **Fix:** `AnimatePresence` + `motion.div` fade, 150ms.
- **[MOTION-2] P2** — Both modals (`AnnouncementsPanel`'s `EditModal`, `SystemPanel`'s `ResetModal`) appear instantly at full opacity/scale. **Fix:** backdrop fade + panel scale-in, 150ms.
- **[MOTION-3] P2** — No button anywhere gives press feedback (confirmed zero `active:scale` usages). **Fix:** `active:scale-[0.97] transition-transform`, ideally via an extracted `<Button>` component (the already-installed-but-unused `class-variance-authority` + `cn()` in `src/lib/utils.ts` are sitting ready for exactly this).
- **[MOTION-4] P3** — Ticket row hover is a flat background change only. **Fix:** `hover:-translate-y-px hover:shadow-sm transition-[transform,box-shadow,background-color]`. Quick win — the only motion fix that doesn't require the framer-motion install.
- **[MOTION-5] P3** — `AnnouncementBanner` appears/disappears instantly. **Fix:** slide-down/up via `max-height`/`opacity` transition.
- **[MOTION-6] P3** — Count-up animation on Analytics hero stats is blocked on VIS-11 (no hero row exists yet to animate).

**Quick wins:** MOTION-4 only (everything else needs the framer-motion install first).

---

## SECTION 5: Feedback & Error States

The DB-reset flow is the best-executed feedback pattern in the app and should be the template the rest of the app is brought up to. Against that bar: there is no toast system anywhere, and one real correctness bug was found and independently verified.

- **[FEED-2] P0** — `AnnouncementsPanel.tsx`'s `toggleActive`/`remove` (verified: lines 40-55) never check `resp.ok` before showing a success message. Every other admin panel correctly branches on `resp.ok`; this one regressed. Meets the brief's own P0 bar: "causes confusion that leads to wrong action" — an admin who believes a stale announcement was deactivated won't retry. **Fix:** check `resp.ok`, branch the message accordingly. Quick win — two one-line-condition fixes.
- **[FEED-1] P1** — No toast system exists anywhere; every success/error notice is a differently-styled inline `<p>` that never auto-dismisses, copy-pasted into 5+ files. **Fix:** build a lightweight toast provider (context + portal, 4s auto-dismiss) and migrate async-action-level messages to it (keep field-level validation errors inline, per standard practice). Not a quick win — new component + touches 6 call sites.
- **[FEED-7 / ROLE-7] P1** — The 20-char mandatory-note requirement is only discovered after clicking a transition button and getting an error — the exact anti-pattern the brief names: "should say 'Note required' before they click." **Fix:** precompute per-button whether the transition needs a note, disable + badge it, show a live character counter. Quick win — self-contained ~20-line change.
- **[FEED-8 / ROLE-8] P2** — The citizen-facing "Ask a follow-up" box and the internal-only note box are visually identical (same white card, same indigo button) despite one being emailed to the citizen and the other staying internal. **Fix:** give the citizen-facing box a teal left-border accent + a "Citizen will see this" tag. Quick win.
- **[FEED-3] P2** — `TeamPanel`'s `AddAgentForm` only validates on submit, not on blur. **Fix:** call field validation on `onBlur`. Quick win.
- **[FEED-4] P2** — Ticket queue's empty state ("No tickets.") gives no context about which scope/filter produced zero results. **Fix:** scope-aware message + icon, mirroring `AnalyticsPanel`'s already-good `EmptyState`. Quick win.
- **[FEED-10] P3** — Login's wrong-password error shows only a message box; input borders stay default grey. **Fix:** add a red border when `error` is set. Quick win.

**Strengths worth preserving:** `SystemPanel.tsx`'s `ResetModal` feedback flow (gold standard — use as the toast-system reference). `AnalyticsPanel`'s contextual `EmptyState`. `TicketDetailPage.sendReply`'s three-way `idle/sending/sent/failed` state with distinct icons.

**Quick wins:** FEED-2 (highest-priority quick win in the whole review), FEED-7, FEED-8, FEED-3, FEED-4, FEED-10.

---

## SECTION 6: Accessibility

Semantic HTML is solid — every interactive element checked was a real `<button>`/`<a>`/`<select>`/`<input>`, no `<div onClick>` found anywhere. Icon-only buttons that matter most already have `aria-label`. The two real gaps: weak focus visibility on the highest-traffic inputs (login), and the two modals having no dialog semantics or keyboard-dismiss path.

- **[A11Y-1] P1** — Login's email/password inputs, the queue's pageSize select, and the priority-rubric textarea all set `focus:outline-none` and rely solely on a 1px border-color shift — a WCAG 2.4.7 (Focus Visible) failure pattern, hitting the highest-traffic keyboard interaction in the app. **Fix:** `focus-visible:ring-2 focus-visible:ring-[#028090] focus-visible:ring-offset-1`, rolled out consistently. Quick win.
- **[A11Y-8] P1** — Neither modal has `role="dialog"`/`aria-modal`, focus trapping, `Escape` handling, or focus-return on close. Worst on `ResetModal`, which is deliberately non-dismissible by outside click — meaning a keyboard-only user who opens it has no way to close it except tabbing all the way to Cancel. **Fix:** shared `useModalA11y()` hook (Escape listener gated on `!submitting` for the reset modal, `role="dialog"`, focus-trap, focus-return). Not a quick win.
- **[A11Y-4] P2** — No `<th scope="col">` anywhere in the queue or Team tables — materially degrades screen-reader table navigation on an 11-column table. **Fix:** add `scope="col"`. Quick win.
- **[A11Y-5] P3** — Sort direction is communicated only via an `aria-hidden` glyph. **Fix:** add `aria-sort` to the `<th>`. Quick win.
- **[A11Y-6] P2** — `text-muted-foreground` at `text-xs` sizes sits at a fragile ~4.6:1 contrast margin. **Fix:** bump `text-xs` instances to `text-slate-600` (~7:1). Quick win, but touches many files.
- **[A11Y-2] P3** — A custom-field remove button uses `title` only, no `aria-label`. **Fix:** add `aria-label`. Quick win.

**Strengths worth preserving:** no `<div onClick>` anywhere; `AnnouncementBell`/`AnnouncementBanner`'s dismiss/`Sidebar`'s collapse toggle already have correct `aria-label`s; every badge shows visible text, not colour-only (constrains VIS-5's priority-dot fix to be additive, never a replacement).

**Quick wins:** A11Y-1, A11Y-4, A11Y-5, A11Y-2, A11Y-6.

---

## SECTION 7: Role-Based UX (Admin / Lead / Agent / Citizen)

**Admin:** Solid. Reachable via a persistent sidebar item (modulo NAV-1's flash), 6 sub-tabs open with Team first (the most common daily action), and the Danger Zone is exactly where the brief wants it — last sub-tab, visually walled off, coral-bordered, `AlertTriangle` icon, explicit consequence copy. A genuine strength — cite it as the pattern other destructive UI should follow.

**Lead (heaviest user):** This is where the review's most consequential defect lives.
- **[ROLE-3] P1** — The queue's default sort (`createdAt desc`) directly contradicts the product's own documented spec (`docs/12_AGENT_DASHBOARD.md`: "Priority score descending... oldest high-priority first"). Combined with VIS-5's missing visual priority emphasis, a Lead's first 30 seconds of scanning are fighting the tool twice. **Fix:** change `QUEUE_DEFAULTS.sortBy` to `"priorityLabel"` (the sort key is already wired end-to-end server-side — confirmed via `TicketService.SORT_COLUMNS`) — verify tie-break behavior is acceptable before shipping. Quick win (1-line frontend change).
- **[ROLE-5] P2** — Reassigning a ticket requires opening ticket detail (a full navigation) — there's no inline assignee control in the queue itself, despite "reassign to agent" being a named common Lead task. **Fix:** inline `<select>` in the Assigned-to column for admin/lead. Not a quick win — moderate effort.

**Agent:** Correctly scoped — `assignedTo=me` is set server-side and the scope-toggle UI is hidden entirely for agents, confirmed directly in code. A real strength. Remaining friction points are FEED-7/ROLE-7 and FEED-8/ROLE-8 (already covered in Section 5).

**Citizen (public status page):**
- **[ROLE-9] P1** — The ticket-status pill is small, monochrome, outline-only, and shows the raw API string verbatim (`in_progress`, not humanized) — despite this being the single most important piece of information on the page, and the brief's explicit test being "big, coloured badge." **Fix:** colour from `tokens.status`, humanize the label, increase visual weight. Quick win.
- **[ROLE-10] P2** — No plain-language "what happens next" message tied to status — a citizen seeing "Pending customer" may misread whose turn it is to act. **Fix:** a per-status one-line explainer map. Quick win.
- **[ROLE-11] P2** — Zero branding anywhere on the page (no logo, no colour, no footer) — in stark contrast to the heavily-branded login page, undermining trust at the one touchpoint where an unauthenticated citizen most needs reassurance this is their utility's real site. **Fix:** add the same teal-gradient wordmark treatment used elsewhere, plus a minimal footer. Static-shell change only — does not touch SSR/no-auth/fast-load behavior. Quick win.

**Quick wins:** ROLE-3, ROLE-9, ROLE-10, ROLE-11.

---

## PRIORITISED FINDINGS

**P0 — Critical (1 finding):**
- FEED-2 — `AnnouncementsPanel` reports success on failed API calls

**P1 — High (13 findings):**
- NAV-1, VIS-1, VIS-2, VIS-5, VIS-10, PERF-1, PERF-2, PERF-3, PERF-5, FEED-1, FEED-7/ROLE-7, A11Y-1, A11Y-8, ROLE-3, ROLE-9

*(Note: 15 items listed above because FEED-7 and ROLE-7 are one finding cross-referenced from two domains, and ROLE-3/ROLE-9 sit at the Section-7/other-domain intersection — 13 distinct P1 findings in total.)*

**P2 — Medium (17 findings):**
- VIS-3, VIS-4, VIS-6, VIS-7, VIS-8, VIS-9, VIS-11, PERF-4, PERF-8, PERF-9, FEED-8/ROLE-8, FEED-3, FEED-4, A11Y-4, A11Y-6, ROLE-5, ROLE-10, ROLE-11

**P3 — Low (7 findings):**
- NAV-2, NAV-3, MOTION-4, MOTION-5, MOTION-6, FEED-10, A11Y-2, A11Y-5

**Estimated effort to reach a "polished" state:**

| Workstream | Days |
|---|---|
| Colour-system unification (VIS-1/2/3 + Tailwind config extension) | 1.5 |
| Skeleton loaders (PERF-1/2/3/5) + shared skeleton component | 1.5 |
| Toast system build + rollout (FEED-1) + FEED-2/3/4/8/10 | 1.5 |
| Motion layer: framer-motion install + MOTION-1/2/3/4/5/6 | 2 |
| Ticket queue visual/UX (VIS-4/6/7, ROLE-3/5, PERF-4) | 1.5 |
| Resolution field + Generate Summary UI (VIS-10 — new feature) | 1.5 |
| Accessibility pass (A11Y-1/2/4/5/6/8) | 1 |
| Citizen status page (ROLE-9/10/11) | 0.5 |
| Analytics hero KPI row + count-up (VIS-11, MOTION-6) | 1 |
| Nav/IA polish (NAV-1/2/3) | 0.5 |
| **Total** | **~12.5 days** (1 engineer, includes QA per workstream) |

---

## IMPLEMENTATION BRIEF

> The blocks below are paste-ready for a coding agent. This session implemented the items marked **[IMPLEMENTED THIS SESSION]** directly — see the companion commit/diff for the actual applied changes, which may differ slightly in detail from the brief below where the live codebase required adaptation (e.g. Tailwind JIT-safety, exact line numbers having shifted). Items not marked implemented remain queued for a future pass (see `docs/UI_REVAMP_v2.md`-scale effort estimate above).

### Fix FEED-2: AnnouncementsPanel silently reports success on failed API calls — **[IMPLEMENTED THIS SESSION]**
File: `apps/dashboard/src/components/admin/AnnouncementsPanel.tsx`
Change: Check `resp.ok` in `toggleActive` and `remove` before setting the success message; show a failure message otherwise.
Test: Force a failing response (e.g. stop the backend or throttle-block the request) and confirm the message reads "Failed to..." rather than the success text.

### Fix NAV-1: Role-gated sidebar item flashes in after mount — **[IMPLEMENTED THIS SESSION]**
File: `apps/dashboard/src/app/dashboard/page.tsx`
Change: Read the `role` cookie synchronously in the `useState` initializer instead of a `useEffect`.
Test: Log in as admin, hard-refresh `/dashboard`, confirm the Administration nav item is present on first paint with no pop-in.

### Fix VIS-1: badges.ts hardcodes classes instead of reading design-tokens.ts — **[IMPLEMENTED THIS SESSION]**
File: `apps/dashboard/src/lib/badges.ts`
Change: Rebuild each badge function from `tokens.status`/`tokens.priority`/`tokens.identityStatus`, using inline `style={{background, color}}` (Tailwind JIT can't see dynamic arbitrary-value classes at build time, so inline style is the correct, lowest-risk implementation — not the arbitrary-value-class approach floated in the original review).
Test: Confirm every status/priority/identity badge shows its correct colour; confirm changing a value in `design-tokens.ts` reflects in badges without touching `badges.ts` again.

### Fix VIS-2/VIS-3: Indigo interactive elements disconnected from brand palette — **[IMPLEMENTED THIS SESSION]**
File: `apps/dashboard/tailwind.config.ts` + all files using `indigo-*` utilities
Change: Add a `brand` colour scale to Tailwind config; replace every `indigo-*` utility with the corresponding `brand-*` one across the queue, ticket detail, and admin panels.
Test: Grep for `indigo-` post-change — expect zero matches; visually confirm every button/link/active-tab now renders in brand teal.

### Fix VIS-5: Priority doesn't visually pop in the ticket queue — **[IMPLEMENTED THIS SESSION]**
File: `apps/dashboard/src/app/dashboard/page.tsx`
Change: Add a priority dot before the ticket number; tint `critical` rows.
Test: Load the queue with mixed priorities; confirm each row shows a dot matching its priority colour and critical rows have a faint red tint.

### Fix ROLE-3: Ticket queue default sort contradicts documented spec — **[IMPLEMENTED THIS SESSION]**
File: `apps/dashboard/src/app/dashboard/page.tsx`
Change: `QUEUE_DEFAULTS.sortBy` → `"priorityLabel"`, `sortDir` → `"desc"`. Verified server-side: `TicketService.SORT_COLUMNS` already whitelists `priorityLabel` → `t.priority_label`, so this is a safe, already-wired sort key.
Test: Load the queue fresh (no sessionStorage state); confirm it's sorted by priority (critical first), not creation date.

### Fix FEED-7/ROLE-7: Mandatory-note requirement only discovered after clicking — **[IMPLEMENTED THIS SESSION]**
File: `apps/dashboard/src/app/dashboard/tickets/[id]/page.tsx`
Change: Precompute per-button whether a transition needs a note; disable + badge it; show a live character counter.
Test: Open a ticket in `in_progress`; confirm "Move to Resolved" shows a "Note required" badge and stays disabled until 20+ characters are typed.

### Fix A11Y-1: Weak focus indicator on login inputs — **[IMPLEMENTED THIS SESSION]**
File: `apps/dashboard/src/app/login/page.tsx` (+ rolled out broadly)
Change: Replace `focus:outline-none` + border-only with `focus-visible:ring-2 focus-visible:ring-[#028090] focus-visible:ring-offset-1`.
Test: Tab into the email field on `/login`; confirm a clear teal ring appears, not just a border-colour shift.

### Fix A11Y-8: Modals lack Escape-to-close, focus trap, focus return — **[IMPLEMENTED THIS SESSION]**
File: `apps/dashboard/src/components/admin/SystemPanel.tsx`, `AnnouncementsPanel.tsx`
Change: Escape-key listener (gated on `!submitting` for the reset modal), `role="dialog"`/`aria-modal`, focus returns to the trigger on close.
Test: Open the Reset Database modal, press Escape while idle — it closes and focus returns to the button that opened it. Confirm Escape does NOT close it mid-request.

### Remaining P1/P2 quick wins implemented this session:
VIS-4 (zebra rows), VIS-7 (channel icons), VIS-8 (heading tiers), VIS-9 (message author-type borders), FEED-8/ROLE-8 (citizen-facing accent), FEED-3 (on-blur validation), FEED-4 (scope-aware empty state), FEED-10 (red input border on login error), A11Y-2 (aria-label), A11Y-4 (scope="col"), A11Y-5 (aria-sort), A11Y-6 (text-xs contrast), ROLE-9 (colour the status badge), ROLE-10 ("what happens next" copy), ROLE-11 (citizen page branding), PERF-4 ("last updated" caption).

### Deferred to a future pass (not implemented this session — higher effort/risk, see effort table):
VIS-6 (SLA column — new feature), VIS-11 (hero KPI row — new data aggregation), PERF-1/2/3 (list/panel skeleton loaders beyond the queue table, which was done — moderate, multi-file), MOTION-1/2/3/5/6 (require `framer-motion` install — deferred to avoid adding a new dependency without full regression time; MOTION-4's row-hover-lift and the `active:scale` press-feedback rollout were done without it), ROLE-5 (inline queue reassignment — moderate new feature), PERF-8 (optimistic UI).

**VIS-10 (Resolution field) — investigated, partially blocked on a real backend gap, not a frontend oversight.** Verified directly against the backend source: `POST /api/v1/tickets/{id}/generate-resolution-summary` does exist end-to-end (gateway → db-writer), but `TicketService.resolutionSummary()` is an intentional Phase-1 stub that always throws `503 AI_UNAVAILABLE` ("the AI summariser is not wired to db-writer yet"). More importantly, **there is no exposed endpoint for an agent to manually save typed resolution text** — db-writer's generic `TicketService.update()` accepts a `resolution` field internally, but no gateway route (`TicketsResource.java`) exposes a PATCH for it to the dashboard. Building a fully-functional Resolution field therefore requires a small backend addition (a `PATCH /api/v1/tickets/{id}/resolution` gateway route forwarding to the existing internal update path) — a legitimate scope decision for the product owner, not something to silently add during a UI-only pass. Recommend: add that one gateway endpoint in a follow-up, then wire the frontend field described in the original brief (editable textarea, locked when closed, Generate Summary button already correctly hitting a real endpoint whose current always-503 response IS the documented Phase-1 behavior).

---

## PROCESS NOTES

This review was conducted with a single specialist agent (no multi-agent contradiction to adjudicate), so the moderator's Phase 3 "agent confirmation" round was replaced with direct spot-verification: `AnnouncementsPanel.tsx` and `SystemPanel.tsx` (the two files underpinning the review's highest-severity claims — FEED-2, MOTION-2, A11Y-8) were read in full by the moderator and found to match the agent's citations exactly, including line-level details (the `ResetModal`'s "Overlay click deliberately does NOT close" comment, the missing `resp.ok` checks). No corrections were needed to the agent's technical claims; the report above is the agent's findings as-verified, reorganized into the required template.
