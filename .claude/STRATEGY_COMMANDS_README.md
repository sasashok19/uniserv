# UniServe — Strategy CLI Commands

Two Claude CLI slash commands that run multi-agent strategy
sessions for UniServe. Run them in sequence.

---

## Setup

Copy the `.claude/` folder into your UniServe project root:

```bash
cp -r .claude /path/to/UniServe/
```

Confirm the commands appear in Claude CLI:
```bash
cd /path/to/UniServe
claude /   # type / to see available commands
# Should show: market-strategy, digital-marketing
```

---

## Usage

### Step 1 — Integrated Market Strategy

```bash
claude /market-strategy
```

**What happens:**
- Moderator loads all project context (README, docs)
- 4 analyst agents work in parallel (Market, Customer,
  Commercial, Growth & Exits)
- Moderator consolidates into a draft IMS
- Draft shared back to all agents for challenge/confirm
- Moderator adjudicates and produces final report
- Saves to: `reports/market-strategy-report.md`

**Time estimate:** 10-20 minutes

**You will be asked to confirm at:**
- Phase 2→3 (before sharing draft back to agents)
- Phase 3→4 (before final adjudication)

**Output covers:**
TAM/SAM/SOM · Competitive landscape · Buyer personas ·
Pricing (India) · 3-phase rollout · Penetration strategy ·
Sustain & grow · Exit scenarios · Revenue Y1-Y3 ·
Unit economics (CAC/LTV) · Key risks

---

### Step 2 — Digital Marketing Strategy

```bash
claude /digital-marketing
```

**Run after /market-strategy.** Reads IMS report as input.

**What happens:**
- Moderator loads IMS report + project context
- 4 specialist agents work in parallel (Channels, Content,
  Sales Enablement, Growth & Community)
- Moderator consolidates into a draft DMS
- Draft shared back to agents for challenge/confirm
- Moderator adjudicates (IMS always wins on conflicts)
- Saves to: `reports/digital-marketing-report.md`

**Time estimate:** 10-20 minutes

**Output covers:**
Channel mix by segment · Budget allocation (INR) ·
KPIs per channel · Content pillars · SEO strategy ·
Q1 content calendar · Sales pitch narrative ·
10-slide pitch deck outline · Objection handling guide ·
Lead scoring model · 6-email nurture sequence ·
Partner programme · 12-month campaign calendar ·
Y1 marketing budget (INR)

---

## Output Files

```
reports/
├── market-strategy-report.md    ← IMS: pricing, phases, exit
└── digital-marketing-report.md  ← DMS: channels, content, sales
```

Both files are used as input to future strategy iterations.
Re-run either command to update — it will load the prior
version as context.

---

## Agent Files

```
.claude/
├── commands/
│   ├── market-strategy.md        ← /market-strategy orchestrator
│   └── digital-marketing.md      ← /digital-marketing orchestrator
└── agents/
    ├── market-analyst.md          ← TAM, competitive landscape
    ├── customer-strategist.md     ← segments, personas, procurement
    ├── commercial-strategist.md   ← pricing, revenue, unit economics
    ├── growth-exits-strategist.md ← phases, penetration, exit
    ├── digital-channels-specialist.md  ← channel mix, budget, KPIs
    ├── content-specialist.md           ← content, SEO, thought leadership
    ├── sales-enablement-specialist.md  ← pitch, deck, objections, demo
    └── growth-community-specialist.md  ← leads, nurture, PLG, partners
```

---

## Tips

- Run in a Claude CLI session with full project context loaded
- The agents are opinionated — expect real debate, not consensus
- The moderator adjudicates based on evidence, not politeness
- Both reports are living documents — re-run as the product evolves
- Add new context to README.md before re-running for better results
