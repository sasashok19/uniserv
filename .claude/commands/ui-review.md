# /ui-review — UniServe Dashboard UI Review Command
# Claude CLI slash command
#
# Usage: /ui-review
#
# What this does:
#   Phase 0 — Load all source files and context
#   Phase 1 — UI/UX reviewer agent analyses the dashboard
#   Phase 2 — Moderator structures findings into a report
#   Phase 3 — Agent reviews and confirms/amends the report
#   Phase 4 — Final prioritised report saved as an
#              actionable implementation brief
#
# Output: reports/ui-review-report.md
#
# Run this AFTER /market-strategy so segment and persona
# context informs the UX recommendations.

---

## MODERATOR INSTRUCTIONS

You are the UI Review Moderator for UniServe.
Your job is to direct one specialist UX reviewer agent,
consolidate findings, and produce a final actionable
report that can be fed directly into Claude CLI to
implement fixes.

You do NOT do the UX review yourself.
You load context, brief the agent, consolidate output,
and structure the final report.

---

## PHASE 0 — Load Context (do this first, silently)

Read ALL of these before doing anything else.
You must read the actual source files — not just the docs.

### Source files to read (dashboard)
```
apps/dashboard/src/app/page.tsx
apps/dashboard/src/app/login/page.tsx
apps/dashboard/src/app/dashboard/page.tsx
apps/dashboard/src/app/dashboard/tickets/[id]/page.tsx
apps/dashboard/src/app/status/[ref]/page.tsx
apps/dashboard/src/components/analytics/AnalyticsPanel.tsx
apps/dashboard/src/components/admin/TeamPanel.tsx
apps/dashboard/src/components/admin/IntakeFieldsPanel.tsx
apps/dashboard/src/components/admin/PriorityRulesPanel.tsx
apps/dashboard/src/components/admin/GeneralSettingsPanel.tsx
apps/dashboard/src/lib/badges.ts
apps/dashboard/src/lib/gateway.ts
apps/dashboard/tailwind.config.js (or .ts)
apps/dashboard/src/app/globals.css
```

If `apps/dashboard/src/lib/design-tokens.ts` exists, read it.

Read any file matching:
```
apps/dashboard/src/components/layout/*
apps/dashboard/src/components/ui/*
apps/dashboard/src/components/announcements/*
apps/dashboard/src/components/news/*
```

### Documentation to read
```
UI_REVAMP_v2.md              (if present — target design spec)
docs/12_AGENT_DASHBOARD.md   (dashboard feature spec)
docs/11_MULTI_TENANCY.md     (RBAC — 3 roles and their journeys)
reports/market-strategy-report.md (if present — who the users are)
```

### After loading, confirm:
"Context loaded. Dashboard has [N] pages, [N] components.
Design tokens: [found/not found].
UI_REVAMP_v2: [found/not found].
IMS report: [found/not found].

Key observations before review:
- Current UI appears to be: [brief honest characterisation]
- Tech stack confirmed: Next.js 14, Tailwind CSS, [recharts/lucide/framer-motion if present]
- Starting Phase 1 — briefing UI/UX reviewer agent."

---

## PHASE 1 — Agent Review

Hand all loaded source files and context to the
UI/UX reviewer agent defined in:
`.claude/agents/ui-ux-reviewer.md`

Instruct the agent:
"Review the UniServe dashboard as loaded from source.
Your brief is in ui-ux-reviewer.md. Produce a complete
structured review covering all 7 domains. For every
finding include the specific file and line/component
where the issue lives. Be concrete and technically
precise — this report will be used to implement fixes."

Collect the full agent output.
Label it: [UI/UX REVIEWER OUTPUT]

---

## PHASE 2 — Moderator Consolidation

Read the agent output. Produce a structured report
with these sections:

```
UI REVIEW REPORT — UniServe Dashboard
───────────────────────────────────────
Generated: [date]
Dashboard version: [from README or package.json]

EXECUTIVE SUMMARY
  Overall rating: [1-10]
  Top 3 strengths
  Top 3 critical issues

SECTION 1: Navigation & Information Architecture
SECTION 2: Visual Hierarchy & Design Consistency
SECTION 3: Loading & Perceived Performance
SECTION 4: Transitions & Motion (NEW)
SECTION 5: Feedback & Error States
SECTION 6: Accessibility
SECTION 7: Role-Based UX (Admin / Lead / Agent / Citizen)
SECTION 8: Mobile & Responsive Behaviour

PRIORITISED FINDINGS
  P0 — Critical (breaks usability)
  P1 — High (significantly hurts experience)
  P2 — Medium (noticeable friction)
  P3 — Low (polish)

IMPLEMENTATION BRIEF
  (technically precise fix instructions per finding)
```

Label this: [MODERATOR DRAFT REPORT]

---

## PHASE 3 — Agent Confirmation

Share [MODERATOR DRAFT REPORT] with the agent.

Ask:
"Review this consolidated report. For each section
in your domain: CONFIRMED (accurate), AMENDED
(correction needed — state it precisely), or
MISSING (something important was dropped).
Flag any finding where the technical implementation
advice is incorrect given the actual source code."

Collect: [AGENT CONFIRMATION]

Apply all AMENDED and MISSING items.

---

## PHASE 4 — Save Report

Save the final report to:
`reports/ui-review-report.md`

The Implementation Brief section must be formatted
so it can be pasted directly into Claude CLI as
implementation instructions.

Announce:
"UI Review complete. Report saved to
reports/ui-review-report.md.

Summary:
- [N] critical findings (P0)
- [N] high priority findings (P1)
- [N] medium findings (P2)
- [N] polish items (P3)

To implement fixes, run:
claude 'Read reports/ui-review-report.md.
Implement all P0 and P1 findings in the
Implementation Brief section. Confirm before
making each change.'"

---

## OUTPUT REQUIREMENTS

The final report must include:
- [ ] Every finding references a specific file + component
- [ ] Every finding has a severity (P0/P1/P2/P3)
- [ ] Every P0/P1 finding has an implementation fix
      with specific code guidance (not vague advice)
- [ ] Transition/motion section covers every interactive
      element (nav clicks, modal opens, tab switches,
      row hover, side-sheet slide-in)
- [ ] Loading states reviewed for every data-fetching
      component (skeleton vs spinner vs nothing)
- [ ] Mobile behaviour reviewed for all 3 role dashboards
- [ ] Citizen status page reviewed separately
- [ ] Design token consistency checked
      (are colours used from tokens or hardcoded?)
- [ ] At least one "quick win" per section
      (something fixable in under 30 minutes)
