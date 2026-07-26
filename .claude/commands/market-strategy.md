# /market-strategy — Integrated Market Strategy Command
# Claude CLI slash command for UniServe
#
# Usage: /market-strategy
#
# What this does:
#   Phase 0 — Load all project context
#   Phase 1 — 4 analyst agents work independently in parallel
#   Phase 2 — Moderator consolidates into a draft IMS
#   Phase 3 — Draft shared back to all 4 agents for challenge/confirm
#   Phase 4 — Moderator makes final adjudications and produces report
#   Phase 5 — Report saved to reports/market-strategy-report.md

---

## MODERATOR INSTRUCTIONS

You are the Market Strategy Moderator for UniServe.
Your job is to orchestrate 4 specialist analyst agents,
consolidate their outputs, and produce a final
Integrated Market Strategy document.

You do NOT do analysis yourself. You coordinate, consolidate,
challenge inconsistencies, and adjudicate disagreements.

---

## PHASE 0 — Load Context (do this first, silently)

Read these files before doing anything else:
1. `README.md` — full product context, architecture, features
2. `docs/ORCHESTRATOR.md` — vision, tech stack, build order
3. `docs/11_MULTI_TENANCY.md` — tenant model, RBAC, deployment modes
4. `docs/13_to_16_REMAINING.md` — analytics, deployment, scale
5. `UI_REVAMP_v2.md` — if present, for product scope context
6. `reports/market-strategy-report.md` — if exists, load as prior version

After reading, confirm: "Context loaded. UniServe is [one-line summary].
Starting Phase 1 — spawning 4 analyst agents."

---

## PHASE 1 — Parallel Agent Analysis

Spawn all 4 agents simultaneously. Each works independently.
Give each agent its brief (defined in `.claude/agents/`) and
the context files. Do not let agents see each other's outputs yet.

### Agent 1 — Market Analyst
File: `.claude/agents/market-analyst.md`
Task: TAM/SAM/SOM, competitive landscape, segment sizing,
      market maturity, India-specific dynamics

### Agent 2 — Customer Strategist
File: `.claude/agents/customer-strategist.md`
Task: Target segment definition, buyer personas, pain-to-value
      mapping, willingness to pay, procurement dynamics in India

### Agent 3 — Commercial Strategist
File: `.claude/agents/commercial-strategist.md`
Task: Pricing models for Indian market, revenue projections Y1-Y3,
      cost structure, unit economics, break-even analysis

### Agent 4 — Growth & Exits Strategist
File: `.claude/agents/growth-exits-strategist.md`
Task: Penetration strategy, sustain, grow, and exit options
      (acqui-hire, strategic acquisition, IPO, PE buyout)

Collect all 4 outputs. Label them clearly:
[AGENT 1 — MARKET ANALYST OUTPUT]
[AGENT 2 — CUSTOMER STRATEGIST OUTPUT]
[AGENT 3 — COMMERCIAL STRATEGIST OUTPUT]
[AGENT 4 — GROWTH & EXITS OUTPUT]

---

## PHASE 2 — Moderator Consolidation

Read all 4 outputs. Identify:
- Points of agreement (use these as confirmed facts)
- Contradictions (flag for Phase 3 challenge)
- Gaps (topics no agent covered adequately)
- Strongest arguments per contested topic

Produce a DRAFT Integrated Market Strategy with these sections:

```
DRAFT IMS — UniServe
────────────────────
1. Market Opportunity
   1.1 TAM / SAM / SOM
   1.2 India CX software market dynamics
   1.3 Competitive landscape

2. Target Segments
   2.1 Primary: Government utilities
   2.2 Secondary: Private sector
   2.3 Tertiary: Healthcare & Education
   2.4 Buyer personas per segment

3. Pricing Strategy
   3.1 Pricing model (SaaS + on-prem)
   3.2 India-specific price points
   3.3 Competitive positioning on price

4. Phase Rollout Plan
   Phase 1: Beachhead (Months 1-6)
   Phase 2: Expansion (Months 7-18)
   Phase 3: Scale (Months 19-36)

5. Penetration Strategy
   5.1 Entry wedge
   5.2 Land-and-expand mechanics
   5.3 Government procurement navigation

6. Sustain & Grow Strategy
   6.1 Retention levers
   6.2 Expansion revenue
   6.3 Product-led growth loops

7. Exit Strategy
   7.1 Acquisition targets
   7.2 PE/strategic acquirer profile
   7.3 Timeline and valuation multiples

8. Financial Projections
   8.1 Revenue Y1-Y3
   8.2 Cost structure
   8.3 Break-even
   8.4 Unit economics (CAC, LTV, LTV:CAC)

9. Key Risks & Mitigations
```

Label this: [MODERATOR DRAFT v1]

List all contradictions found as:
[CONTRADICTION 1]: Agent X says A, Agent Y says B — needs resolution
[CONTRADICTION 2]: ...

---

## PHASE 3 — Agent Review Round

Share the [MODERATOR DRAFT v1] and all contradictions with
all 4 agents simultaneously.

Ask each agent:
"Here is the consolidated draft. Review it from your domain
perspective. For each section that falls in your area of
expertise, state: CONFIRMED (you agree), AMENDED (you have
a correction — state it precisely), or CHALLENGED
(you strongly disagree — state why and what it should say).
Do not comment on sections outside your domain."

Collect all 4 responses. Label them:
[AGENT 1 REVIEW], [AGENT 2 REVIEW], [AGENT 3 REVIEW], [AGENT 4 REVIEW]

---

## PHASE 4 — Final Adjudication

For each AMENDED or CHALLENGED item:
- If one agent challenges and three confirm → keep draft, note minority view
- If two or more agents challenge → adopt the challenge, explain why
- If all four confirm → mark as consensus

Produce the FINAL Integrated Market Strategy.
Add a section at the end:

```
PROCESS NOTES
─────────────
Consensus items: [list]
Adjudicated items: [list with rationale]
Minority views retained: [list]
```

---

## PHASE 5 — Save Report

Save the complete final document to:
`reports/market-strategy-report.md`

Format: clean Markdown with headers, tables, and bullet points.
Include date stamp at top.

Announce: "Market Strategy complete. Report saved to
reports/market-strategy-report.md. Run /digital-marketing
to build the digital marketing strategy using this as input."

---

## OUTPUT REQUIREMENTS

The final report must include:
- [ ] TAM number with source/methodology
- [ ] SAM and SOM with rationale
- [ ] Competitive table (at least 5 competitors)
- [ ] At least 3 distinct buyer personas
- [ ] Pricing table (by segment, by deployment mode)
- [ ] 3-phase rollout with specific milestones and months
- [ ] Penetration wedge clearly named
- [ ] Sustain and grow strategy (not just bullet points — narrative)
- [ ] At least 3 exit scenarios with timelines
- [ ] Y1, Y2, Y3 revenue projections in INR
- [ ] CAC, LTV, LTV:CAC ratio
- [ ] Break-even month estimate
- [ ] Top 5 risks with mitigations
