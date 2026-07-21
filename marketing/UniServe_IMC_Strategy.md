# UniServe — Integrated Marketing Communications (IMC) Strategy

**Version 1.0 · July 2026 · India-first go-to-market**

> UniServe is a multi-tenant, AI-powered unified complaint & feedback platform born out of firsthand observation at a Tamil Nadu Electricity Board (TNEB) customer-care and social-media desk, built as an IIM Calcutta capstone project and now a working product. This document is the single source of truth for how UniServe communicates — one message architecture reused across the pitch deck, website, LinkedIn, email, and events.

---

## 1. Executive Summary

UniServe solves a problem its founders watched happen in real time: **the same citizen complaint arriving over WhatsApp, IVR and email becomes three separate tickets**, ~30% of tickets arrive incomplete, and a social-media desk manually watches Twitter for minister-tagged complaints with a ~15-minute window before they trend. Every large service organisation in India — utilities, banks, hospitals, universities — lives some version of this.

UniServe's answer, **working today**: email and WhatsApp inbound channels feed a single AI conversation agent that verifies identity (or grants explicit anonymity with ANON-XXXX reference IDs), gathers tenant-configured intake fields conversationally, filters auto-responses and bounces, scores priority against an admin-editable rubric, and routes into a role-based agent dashboard with a full audit trail, analytics, and a public status-lookup page. The architecture — four open-source services, event-driven, single-writer database, only one public-facing service — is itself a sales asset for government and regulated buyers who need on-prem or hybrid deployment.

**The IMC job for the next 12 months:**

1. **Establish the category frame** — "unified grievance intelligence," not "another helpdesk" — anchored on the TNEB origin story.
2. **Win a beachhead**: mid-size private-sector CX teams (NBFCs, auto service networks, D2C/e-commerce) where WhatsApp-first intake and AI intake-completion deliver visible ROI in weeks, **plus** cultivate one government lighthouse account (a discom or municipal corporation) as a long-cycle credibility play.
3. **Build founder-led, proof-heavy owned media** (LinkedIn + demo video + landing page) on a lean budget, before any significant paid spend.

The strategy is honest by design: everything we claim publicly is live in the product; roadmap items (Twitter/X ministerial-tag alerting, IVR, web chat, PII scrubbing with Presidio, multi-LLM including air-gapped local models) are always labelled "roadmap."

---

## 2. Market Context & Opportunity

### 2.1 The problem space (observed, not theorised)

| Observed at TNEB desk | Generalised market pain |
|---|---|
| Same complaint via WhatsApp + IVR + email → 3 tickets | No cross-channel identity stitching in incumbent tools |
| ~30% of tickets incomplete (missing consumer no., location, etc.) | Agents burn first-response time chasing basic details |
| Manual Twitter monitoring; ~15-min window before minister-tagged complaints trend | Reputation risk managed by human vigilance, not systems |
| No anonymity path | Whistleblower / sensitive complaints (harassment, ragging, medical) go unreported |

### 2.2 Market sizing (directional estimates — clearly labelled, not citations)

*The figures below are reasonable public-domain-informed estimates for planning purposes; validate before investor use.*

- **India customer-experience / helpdesk software** is plausibly a **US$0.8–1.5B annual market growing 15–20%**, dominated by Zendesk, Freshdesk (Freshworks, home-market advantage), Salesforce Service Cloud, and Sprinklr at the enterprise end. (Estimate.)
- **Government grievance redressal** is a distinct, underserved segment: CPGRAMS processes **millions of grievances per year** at the central level alone; every state discom, municipal corporation, and PSU runs its own fragmented intake. Digital India / e-governance budgets and MeitY/NIC cloud-and-on-prem mandates create structural demand for **data-resident, on-prem-deployable, open-stack** solutions — exactly UniServe's architecture. (Directional.)
- **WhatsApp is India's default service channel**: 500M+ Indian users make WhatsApp-first intake a requirement, not a feature, for banks, NBFCs, telecom, e-commerce and auto service networks. (Widely reported figure; treat as approximate.)
- **Regulatory tailwinds**: RBI/IRDAI grievance-redressal timelines for financial services, UGC anti-ragging and hospital grievance norms mandating anonymous channels, and the DPDP Act pushing data-residency conversations — all favour a platform with anonymity support, audit trails, and on-prem deployment.

### 2.3 Why now, why us

1. **AI intake is finally credible.** LLM-driven conversational intake (live in UniServe today, with a deterministic fallback when no LLM key is configured) turns the 30%-incomplete-ticket problem into a solved problem.
2. **Incumbents are cloud-only and channel-siloed.** Zendesk/Freshdesk treat channels as inboxes; identity stitching across channels and true on-prem deployment are not their game.
3. **The founders saw the problem from inside a government desk** — an origin story no competitor can copy.

---

## 3. STP — Segmentation, Targeting, Positioning

### 3.1 Segmentation

| Segment | Sub-segments | Key need | Deployment fit | Sales cycle |
|---|---|---|---|---|
| **A. Government & utilities** | Discoms (TNEB-like), municipal corporations, PF/RTI grievance cells | Data residency, NIC/MeitY compliance, audit trail, on-prem | On-prem single-tenant | 9–18 months (tenders, pilots) |
| **B. Private — WhatsApp-first CX** | Banks/NBFCs, telecom, e-commerce/D2C, auto service networks | WhatsApp intake, AI completion, SLA analytics, fast time-to-value | Cloud SaaS or hybrid | 1–4 months |
| **C. Healthcare & education** | Hospitals, university grievance cells | **Anonymity mandatory**, audit trail, priority triage | Cloud or on-prem | 3–9 months |

### 3.2 Targeting (phased)

- **Beachhead (months 0–6): Segment B, mid-market** — specifically NBFCs, auto service networks and mid-size D2C brands with 10–100 support agents. Rationale: shortest sales cycle, WhatsApp inbound + email are live today, buyers feel ticket-deflection ROI immediately, and reference logos compound.
- **Lighthouse (months 0–12, parallel, low-cost): one Segment A account** — a single discom or municipal corporation pilot (leveraging the TNEB observation network). Not a revenue play in year one; a **credibility and case-study play**.
- **Expansion (months 6–12): Segment C** — hospitals and universities once the anonymity + audit-trail story has one private-sector proof point behind it.

### 3.3 Positioning statement

> **For** service organisations drowning in fragmented complaint channels, **UniServe** is the **AI-powered unified grievance platform** that **turns every email and WhatsApp message into one complete, correctly prioritised, fully audited ticket** — **because** its AI agent gathers missing details in-conversation, stitches identity across channels, supports truly anonymous complaints, and deploys anywhere: cloud, on-prem, or hybrid. **Unlike** Zendesk, Freshdesk or Sprinklr, UniServe was designed from inside an Indian government service desk for India's channel mix, compliance realities, and deployment constraints.

### 3.4 Messaging house

**Core promise (roofline):**
> **"Every complaint. One ticket. Fully heard."**

| | Pillar 1 — Complete tickets, automatically | Pillar 2 — One citizen, one thread | Pillar 3 — Deploy where your data must live |
|---|---|---|---|
| **Message** | Our AI agent talks to the complainant *before* the ticket lands — so agents start with everything they need. | Email and WhatsApp resolve to one identity and one ticket, with anonymity when it matters. | Four open-source services; only one is public-facing; runs local, Docker, cloud, on-prem or hybrid. |
| **Proof points (all live today)** | Identity gate; tenant-configured intake fields with per-channel mandatory/optional and validation (mobile/PIN); max-N follow-ups; auto-response/bounce filtering; AI priority scoring on an admin-editable rubric | Email threading via `[Ticket TKT-xxxxx]` subject tags; WhatsApp inbound (Meta webhook, HMAC-validated); ANON-XXXX anonymous references; public status lookup; full audit trail with mandatory transition notes | Single db-writer as sole write owner (SQLite→Postgres swap touches nothing else); event-driven via Valkey Streams; adding a channel = one adapter; MIT-friendly stack; deterministic AI fallback when no LLM key exists |
| **Roadmap (always labelled)** | Multi-LLM incl. air-gapped local Llama; PII scrubbing (Presidio) + at-rest encryption | Twitter/X ministerial-tag alert engine; IVR (Twilio); web chat; outbound WhatsApp; SMS | — |
| **Emotional hook** | "Stop asking customers the same question three times." | "The complaint you filed on WhatsApp shouldn't be a stranger to the one you emailed." | "Your data, your premises, your rules." |

**Reason to believe (foundation):** Built from firsthand observation inside TNEB's customer-care and social-media desk; working product, not a deck; open-source architecture inspectable end to end.

---

## 4. Brand Identity & Voice

| Element | Direction |
|---|---|
| **Brand idea** | *The listening infrastructure.* UniServe is what a service organisation sounds like when it actually hears people. |
| **Personality** | Engineer-honest, civic-minded, quietly confident. We show terminal output and dashboards, not stock photos of headsets. |
| **Voice rules** | (1) Live vs roadmap always distinguished — "today" / "on the roadmap." (2) Specifics over adjectives: "30% of tickets arrived incomplete" beats "inefficient processes." (3) Plain English + plain Hindi/Tamil-friendly phrasing for citizen-facing copy. (4) Never bash competitors by name in public assets; compare on capability tables in sales assets. |
| **Visual cues** | Product-real screenshots (agent dashboard, SLA donut, ticket audit trail), the 4-service architecture diagram as a signature graphic, ticket-tag motif (`TKT-xxxxx` / `ANON-XXXX`) as a design element. |
| **Naming discipline** | "UniServe" always one word, capital U and S. Tagline lockup: *UniServe — Every complaint. One ticket. Fully heard.* |
| **Origin story (canonical 2 sentences)** | "UniServe began at a TNEB customer-care desk, watching one complaint become three tickets and a social-media team race a 15-minute window on minister-tagged tweets. We built the system we wished that desk had." |

---

## 5. Buyer Personas

### Persona 1 — "CGM Ramesh" (Govt/utility decision-maker)
- **Role:** Chief General Manager (IT/Commercial) at a state discom, or a municipal commissioner's IT secretary.
- **Pains:** CPGRAMS/CM-cell escalations landing without context; minister-tagged tweets trending before his team knows; audit queries he can't answer; cloud-procurement friction; vendor lock-in fear.
- **Buying triggers:** A public social-media incident; an e-governance modernisation budget line; a directive to reduce grievance pendency; peer discom adopting something similar.
- **What convinces him:** On-prem deployment, open-source stack, full audit trail with mandatory transition notes, the TNEB-observed origin story, a low-risk pilot on one channel.
- **Blockers:** Tender processes, NIC empanelment expectations, "who else in government uses this?"

### Persona 2 — "COO/Head-of-CX Priya" (Bank/NBFC/auto network)
- **Role:** Head of Customer Experience or COO at a mid-size NBFC, auto service network, or D2C brand; 10–100 agents.
- **Pains:** WhatsApp messages handled from a shared phone; duplicate tickets inflating volumes and SLA misses; agents spending first touch collecting loan-account numbers; RBI grievance-timeline pressure; Freshdesk feels like an email tool wearing a WhatsApp costume.
- **Buying triggers:** RBI/IRDAI audit finding; NPS or resolution-time target in her OKRs; WhatsApp volume crossing what a shared handset can absorb; renewal date on the incumbent helpdesk.
- **What convinces her:** A live demo where a WhatsApp message becomes a complete, prioritised ticket without agent touch; SLA and agent-performance analytics; per-tenant pricing that undercuts per-seat incumbents; 2-week pilot.
- **Blockers:** IT security review, migration fear, "is this a student project?" — countered by architecture depth and working product.

### Persona 3 — "Hospital Administrator Dr. Meera / University Registrar"
- **Role:** Hospital administrator / medical superintendent; university registrar or anti-ragging committee chair.
- **Pains:** Grievance committees required by regulation (NABH/UGC) but running on paper and a suggestion box; complainants fear identification; zero triage — a billing quibble and a patient-safety report sit in the same pile.
- **Buying triggers:** Accreditation cycle (NABH/NAAC), a ragging or negligence incident, regulator inspection.
- **What convinces them:** **Anonymous complaints with ANON-XXXX status lookup** (unique among mainstream tools), AI priority scoring on an admin-editable rubric so safety issues surface first, audit trail for committee records.
- **Blockers:** Tiny budgets, committee-based decisions — counter with low-cost single-tenant pricing and a compliance-mapped one-pager.

---

## 6. Channel Strategy — PESO, mapped to personas and funnel

### 6.1 PESO overview

| | Awareness | Consideration | Decision | Retention/Advocacy |
|---|---|---|---|---|
| **PAID** | LinkedIn sponsored posts to CX/IT titles (Persona 2); Google Search on "WhatsApp helpdesk India", "grievance management software" | LinkedIn lead-gen for demo-video views; retargeting site visitors | — (sales-led) | — |
| **OWNED** | Founder LinkedIn posts (TNEB story, build-in-public); landing page; demo video | Product tour video; architecture explainer for govt buyers; comparison pages; blog: "Why 30% of your tickets are incomplete" | ROI one-pager; security/architecture PDF; pilot proposal template | Release notes; customer newsletter; admin-console tips content |
| **EARNED** | GovTech/CX trade-press pitches on the TNEB origin story; IIM Calcutta capstone-to-product story to campus & startup media | Analyst/community mentions (NASSCOM, SaaSBoomi); podcast guesting on Indian SaaS/CX shows | Reference calls with pilot customers | Case studies (with metrics), award submissions (Aegis Graham Bell, Digital India awards) |
| **SHARED** | LinkedIn engagement pods with IIM/alumni network; WhatsApp Business community groups for CX leaders | Webinars co-hosted with a CX community; open-source repo visibility (GitHub) | Customer champions sharing pilot results | User community / advisory circle of first 10 customers |

### 6.2 Persona-channel emphasis

- **Persona 2 (beachhead):** LinkedIn (organic + paid) + targeted cold email + demo video. Fast, measurable, cheap.
- **Persona 1 (lighthouse):** Zero paid media. BD-led: warm introductions via the TNEB observation network, GovTech events, an on-prem architecture whitepaper, and one meticulously run pilot.
- **Persona 3:** Content-led — compliance-mapped one-pagers (NABH/UGC), the anonymity demo clip, and outreach timed to accreditation cycles.

---

## 7. Content Strategy & 90-Day Calendar Skeleton

**Content spine:** one **pillar asset per month**, atomised into 8–10 LinkedIn posts, 1 email, and 1 short video clip.

| Weeks | Pillar asset | Atomised outputs | Funnel stage |
|---|---|---|---|
| 1–2 | **Origin-story essay:** "What I saw at the TNEB complaint desk" (founder byline) | 3 LinkedIn posts (the 3-tickets problem; the 15-minute Twitter window; the 30% incomplete stat), landing page goes live | Awareness |
| 3–4 | **Demo video v1** (4 min: WhatsApp → AI intake → complete ticket → dashboard) | 60-sec cut for LinkedIn, GIF snippets, email #1 to warm network | Awareness→Consideration |
| 5–6 | **"Anatomy of a complete ticket"** blog + annotated screenshot | 2 posts on identity gate & intake fields; 1 post on auto-response filtering ("your helpdesk is talking to out-of-office bots") | Consideration |
| 7–8 | **Architecture whitepaper** (4 services, single-writer, on-prem story) — the govt asset | 2 technical posts; post in relevant engineering communities; GovTech outreach begins | Consideration (Persona 1) |
| 9–10 | **Comparison content:** "UniServe vs generic helpdesks — 6 things we do differently" (capability table, no name-bashing) | 3 posts, one per differentiator cluster; email #2 | Consideration→Decision |
| 11–12 | **Pilot playbook:** "Run a 2-week UniServe pilot" + ROI worksheet | 2 posts; webinar #1 (live demo + Q&A); email #3 with pilot CTA | Decision |
| Ongoing weekly | Founder build-in-public post (1/wk), product screenshot post (1/wk) | — | All |

**Consistency rule:** every asset uses the messaging house verbatim — same core promise, same three pillars, same proof points, same live-vs-roadmap labels. The deck, website, LinkedIn, email signatures, and event booths quote the same positioning statement.

---

## 8. Sales Enablement

| Asset | Purpose | Source material |
|---|---|---|
| **Demo deck (12 slides)** | First meetings; mirrors messaging house 1:1 | Existing pitch (UniServe_Pitch_v3) refreshed to this doc's language |
| **TNEB case narrative (2 pages)** | The emotional + factual anchor: 3-tickets problem, 30% incomplete, 15-minute window — and how each maps to a live feature | Origin story + PRODUCT FACTS |
| **Live demo script (15 min)** | Repeatable demo: WhatsApp inbound → identity gate → intake fields → priority scoring → dashboard → audit trail → anonymous lookup | Product |
| **Architecture & security PDF** | IT/security review unblockers; on-prem story for Persona 1 | README + SYSTEM_OVERVIEW |
| **Capability comparison table** | vs Zendesk/Freshdesk/Sprinklr on: cross-channel identity stitching, in-loop AI info gathering, anonymous complaints, on-prem/govt deployment, ministerial-tag alerting (roadmap-labelled), multi-factor AI priority scoring | Competitive frame |
| **Pilot proposal template** | 2-week pilot, success criteria (ticket completeness %, first-response time, duplicate rate), pricing | — |
| **Compliance one-pagers** | RBI-grievance mapping (Persona 2), NABH/UGC mapping (Persona 3), data-residency note (Persona 1) | — |

---

## 9. Events & BD Motions

| Motion | Target | Cadence | Cost posture |
|---|---|---|---|
| **GovTech summits** (e.g., state e-governance conclaves, Digital India events) | Persona 1 | 2–3/year, attend-and-network first, booth only when funded | Lean: travel only |
| **NASSCOM / SaaSBoomi / startup ecosystem** | Credibility, partnerships, talent | Quarterly participation; apply to showcase tracks | Free–low |
| **Banking & CX forums** (BFSI CX summits, CX community meetups) | Persona 2 | 1–2/quarter; aim for a speaking slot with the TNEB story | Lean: travel only |
| **IIM Calcutta network** | Warm intros to all personas; alumni in BFSI/govt | Continuous; capstone showcase, alumni newsletters | Free |
| **Direct BD — lighthouse account** | One discom/municipal corp | Dedicated founder time, monthly touchpoints, pilot proposal by month 4 | Founder time |
| **Webinars (own)** | Persona 2 & 3 | Monthly from month 3 | Free (Zoom/LinkedIn Live) |

---

## 10. Metrics & KPIs per Funnel Stage

| Stage | KPI | Lean-scenario 6-month target |
|---|---|---|
| Awareness | LinkedIn follower growth; post impressions; landing-page unique visitors | 2,000 followers; 150K cumulative impressions; 3,000 visitors |
| Consideration | Demo-video completions; whitepaper downloads; webinar registrants; email open/reply rates | 500 video completions; 100 downloads; 150 registrants; >40% open / >5% reply on cold sequences |
| Decision | Demos booked; pilots started; pilot→paid conversion | 30 demos; 6 pilots; 3 paying tenants |
| Retention/Advocacy | Tenant retention; case studies published; referenceable logos | 100% of first 3; 2 case studies; 2 reference customers |
| Lighthouse (Persona 1) | Meetings with discom/municipal stakeholders; pilot MoU | 8 meetings; 1 pilot MoU signed |

**Measurement discipline:** every external link carries UTMs (scheme defined in the Digital Campaign Brief); one shared dashboard (a spreadsheet is fine at lean stage) reviewed weekly.

---

## 11. Budget Scenarios (12 months, INR)

### 11.1 Lean / bootstrap (₹4–5 lakh total)

| Line | ₹ (lakh) | Notes |
|---|---|---|
| LinkedIn paid experiments | 1.2 | ₹10K/month avg, spiky around campaigns |
| Video production (DIY + freelance editor) | 0.6 | Demo video + cutdowns |
| Design (freelance: deck, one-pagers, landing page polish) | 0.6 | |
| Domain, hosting, email tooling (landing page, outreach, CRM-lite) | 0.5 | |
| Events & travel (3–4 events, no booths) | 1.2 | |
| Contingency / experiments | 0.6 | |
| **Total** | **≈4.7** | Founder time is the real budget |

### 11.2 Funded (₹25–30 lakh total)

| Line | ₹ (lakh) | Notes |
|---|---|---|
| Paid digital (LinkedIn + search + retargeting) | 8 | Scaled after lean-phase signal |
| Content & video (agency-grade demo film, case-study videos, monthly production) | 5 | |
| Brand & web (proper site, design system) | 3 | |
| Events (booth at 1 GovTech + 1 BFSI event, speaking sponsorships) | 6 | |
| Marketing hire (1 growth/content generalist, part-year) | 6 | |
| Tools (CRM, marketing automation, analytics) | 1.5 | |
| **Total** | **≈29.5** | |

---

## 12. Phased 12-Month Roadmap

| Phase | Months | Focus | Exit criteria |
|---|---|---|---|
| **P0 — Foundation** | 1–2 | Messaging house locked; landing page + demo video live; deck refreshed; UTM/measurement set up; lighthouse outreach begins | All core assets shipped; first 10 cold conversations |
| **P1 — Beachhead proof** | 3–6 | Founder-led LinkedIn + email sequences at Persona 2; monthly webinars; first pilots; GovTech relationship-building | 6 pilots, 3 paying tenants, 1 govt pilot MoU |
| **P2 — Amplify** | 7–9 | First case studies published; paid spend scaled on what worked; Persona 3 (healthcare/education) content launched; speaking slots | 2 case studies; CAC baseline established |
| **P3 — Expand** | 10–12 | Funded-scenario decisions; lighthouse pilot results publicised (with permission); roadmap items shipping (label shift from "roadmap" to "live" in all assets as they land) | 8–10 paying tenants; repeatable sales motion documented |

---

## 13. Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| "Student project" perception | High | Lead with working product + architecture depth; publish the repo story; land 1–2 private pilots fast; never hide the capstone origin — reframe it as "built from field observation, validated at IIM Calcutta" |
| Govt sales cycle stalls the company | High | Beachhead revenue from Persona 2 funds patience; lighthouse is a credibility play, not a cash-flow plan |
| Incumbent (Freshworks) ships identity-stitching | Medium | Speed + niche depth (anonymity, on-prem, govt workflows); our moat is deployment flexibility and the grievance-specific workflow, not one feature |
| AI-claim overreach / compliance blowback | Medium | Hard rule: only claim live capabilities; roadmap always labelled; deterministic fallback disclosed; no "fully autonomous resolution" claims |
| WhatsApp platform dependency (Meta policy/pricing changes) | Medium | Email channel is equally first-class; IVR/SMS/web chat on roadmap diversify intake |
| Founder bandwidth (marketing vs product) | High | This doc's lean plan assumes ~30% founder time; batch content creation; hire in P2 if funded |
| Data-privacy scrutiny (DPDP) before Presidio scrubbing ships | Medium | Be transparent: hybrid mode (on-prem data, PII-stripped AI calls) is roadmap; offer LLM-off deterministic mode today for sensitive buyers |

---

## 14. Consistency Rules (the "one voice" contract)

1. **One positioning statement** (§3.3) — quoted verbatim in the deck's positioning slide, the website hero sub-head, LinkedIn company page "About," and event boilerplate.
2. **One core promise** — *"Every complaint. One ticket. Fully heard."* — as tagline everywhere.
3. **Three pillars, fixed order** — Complete tickets / One citizen one thread / Deploy anywhere — structure every asset's body: deck sections, website sections, demo-video chapters, webinar agenda.
4. **Live vs roadmap labelling** — mandatory in every asset; a reviewer checks this before anything ships.
5. **One origin story, two sentences** (§4) — never improvised.
6. **One metrics sheet** — the KPIs in §10; no asset invents new success numbers.

---

*Companion document: `UniServe_Digital_Campaign_Brief.md` — the execution-ready brief for the first digital campaign.*
