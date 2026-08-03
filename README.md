# UniServe

Multi-tenant, AI-powered complaint/feedback portal. Citizens reach out over
Email or WhatsApp (Phase 1 channels; Twitter/IVR/WebChat land in Phase 2);
an AI pipeline confirms their identity, gathers missing details, classifies
and prioritizes the complaint, deduplicates it against existing open
tickets, and routes it into a role-based agent dashboard with a structured
resolution workflow and full audit trail.

> **Maintenance note:** this file is meant to stay exhaustive and current —
> every code change or new feature should update the relevant section below
> as part of the same change, not as a follow-up.

---

## Contents

- [Live deployment](#live-deployment)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Ports](#ports)
- [Running the stack](#running-the-stack)
- [Services](#services)
- [Event bus & streams](#event-bus--streams)
- [Data model](#data-model)
- [Queue separation & ticket lifecycle](#queue-separation--ticket-lifecycle)
- [Citizen-facing notifications](#citizen-facing-notifications)
- [Subject-line ticket threading & dedup](#subject-line-ticket-threading--dedup)
- [Configurable per-channel intake fields](#configurable-per-channel-intake-fields)
- [Configurable priority rubric & general settings](#configurable-priority-rubric--general-settings)
- [HTTP API reference](#http-api-reference)
- [Environment variables](#environment-variables)
- [Logging, log levels & transaction tracing](#logging-log-levels--transaction-tracing)
- [Testing](#testing)
- [Dashboard app](#dashboard-app)
- [Feature docs index](#feature-docs-index)
- [Phase roadmap](#phase-roadmap)
- [Security notes](#security-notes)

---

## Live deployment

Deployed via each provider's GitHub integration (auto-deploys on push to
`main`) across the 4-provider $0-cost stack — see
[Environment variables](#environment-variables) for the per-service config
each one needs.

| Service    | Provider | URL                                             |
|------------|----------|--------------------------------------------------|
| Dashboard  | Vercel   | https://uniserv-delta.vercel.app/                |
| api-gateway| Render   | https://uniserve-api-gateway.onrender.com         |
| ai-core    | Render   | https://uniserv-ai-core.onrender.com              |
| db-writer  | Railway  | https://uniserv-production.up.railway.app         |
| valkey/Redis | Upstash | (no public URL — accessed via internal `rediss://` connection string) |

Render's free web services cold-start after ~15 min idle, so the first
request to api-gateway/ai-core after inactivity can be slow.

---

## Architecture

Four services, all communicating **asynchronously through an event bus** —
no service calls another's business logic directly.

```
                 ┌──────────────┐        ┌──────────────┐
  Email/WhatsApp │              │ events │              │  events   ┌────────────┐
  ───────────────▶ api-gateway  ├───────▶│   ai-core    ├──────────▶│  db-writer │
                 │  (Java/      │  Valkey│  (Python/    │  Valkey   │  (Java/    │
  Dashboard ◀────┤   Quarkus)   │Streams │   FastAPI)   │ Streams   │   Quarkus) │
   (REST)        │              │◀───────┤              │           │  SQLite    │
                 └──────┬───────┘        └──────────────┘           └─────┬──────┘
                        │                                                  │
                        └──────────────────── REST (db reads/writes) ──────┘
```

- **api-gateway** (Java 21 / Quarkus) — the only public-facing service.
  Ingests channel messages (IMAP email polling, WhatsApp Meta webhooks),
  authenticates all dashboard traffic via JWT, publishes canonical events to
  the event bus, and exposes the REST API the dashboard calls (tickets,
  agents, tenant config, public citizen status lookup).
- **db-writer** (Java 21 / Quarkus) — the *only* service allowed to touch
  the SQLite file. Everything else reads/writes through its REST API. Runs
  as a single, non-scaled instance (SQLite is single-writer); a Caffeine
  in-memory cache absorbs read load.
- **ai-core** (Python 3.11 / FastAPI) — consumes `channel.message.received`
  events, runs the identity-gate + conversation flow, calls an LLM (OpenAI
  Assistants API, with a deterministic rule-based fallback when no LLM key
  is configured), scrubs PII before any LLM call, classifies/deduplicates/
  prioritizes complaints, and calls back into db-writer to resolve/create
  identities.
- **dashboard** (Next.js 14) — agent-facing PWA (Analytics / Ticket Queue /
  Administration, role-gated) plus a public, unauthenticated, server-rendered
  citizen complaint-status page. Its own Next.js API routes act as a thin
  BFF proxy to api-gateway.

**Single-writer + SQLite WAL:** db-writer runs SQLite in WAL mode (`journal_mode=WAL`,
concurrent readers / one writer), serializes writes itself, and layers a
2-minute-TTL Caffeine cache (max 1000 entries) on reads. If write volume ever
exceeds roughly 5,000/day sustained, the documented migration path is a
Hibernate dialect swap to Postgres — no other service is aware of the
storage engine, since everything goes through db-writer's REST API.

**Everything is multi-tenant.** Every table, every event, and every request
carries a `tenantId` — see [11_MULTI_TENANCY](docs/11_MULTI_TENANCY.md).

---

## Repository layout

```
UniServe/
├── services/
│   ├── api-gateway/     # Java 21 / Quarkus — ingestion, auth, dashboard API   :8080
│   ├── db-writer/       # Java 21 / Quarkus — sole SQLite writer               :8090
│   └── ai-core/         # Python 3.11 / FastAPI — AI pipeline                  :8001
├── apps/
│   └── dashboard/       # Next.js 14 — agent + citizen-facing UI               :3000
├── packages/
│   ├── event-contracts/ # shared JSON event schemas (Feature 02f)
│   └── test-stubs/      # .http test files + mock seed scripts
├── infrastructure/
│   ├── docker/          # shared Docker assets
│   ├── k8s/             # Kubernetes manifests
│   └── compose/docker-compose.dev.yml   # Docker dev stack
├── scripts/
│   ├── dev.sh           # entry point — dispatches on RUN_MODE
│   ├── dev-local.sh     # no-Docker local dev (bare processes)
│   └── dev-stop.sh      # stops whichever mode is running
└── docs/                # one .md per feature (see Feature docs index)
```

---

## Ports

Identical in both local (no-Docker) and Docker modes, so nothing downstream
changes when you flip `RUN_MODE`:

| Service      | Port | Stack |
|--------------|------|-------|
| api-gateway  | 8080 | Java / Quarkus |
| db-writer    | 8090 | Java / Quarkus |
| ai-core      | 8001 | Python / FastAPI |
| dashboard    | 3000 | Next.js |
| valkey       | 6379 | Redis-compatible event bus |

> The feature specs under `docs/` mention 8080/8081 for db-writer in a
> couple of places (an earlier draft); the actual stack standardized on
> **8090** to avoid a port clash with api-gateway.

---

## Running the stack

Single entry point, controlled by `RUN_MODE` (default `local`):

```bash
./scripts/dev.sh                   # RUN_MODE=local — bare processes, no Docker
RUN_MODE=docker ./scripts/dev.sh   # Docker Compose stack instead
```

**Local mode** (`scripts/dev-local.sh`):
- Auto-detects a JDK 21 / Maven install if `JAVA_HOME`/`PATH` are stale.
- Starts Valkey/Redis on 6379 (skips if something's already listening).
- Starts db-writer (`mvn quarkus:dev`, 8090), waits for `/q/health/ready`.
- Starts api-gateway (`mvn quarkus:dev`, 8080).
- Starts ai-core (creates/reuses `.venv`, installs requirements, `uvicorn
  --reload`, 8001).
- Starts the dashboard (`npm install`, `npm run dev`, 3000).
- Writes each service's own log to `scripts/<service>.log`, **and** tees a
  tagged, interleaved copy of every line into `scripts/combined.log` — see
  [Logging, log levels & transaction tracing](#logging-log-levels--transaction-tracing).
- Stop with `Ctrl+C` or `./scripts/dev-stop.sh` from another shell.

**Docker mode**: `docker compose -f infrastructure/compose/docker-compose.dev.yml up --build`
brings up all five containers with matching ports and healthchecks; each
service waits on its dependencies' `service_healthy` condition before
starting.

**Health checks** (either mode):

| Service     | Health URL                              |
|-------------|------------------------------------------|
| api-gateway | http://localhost:8080/api/v1/health     |
| db-writer   | http://localhost:8090/api/v1/health     |
| ai-core     | http://localhost:8001/api/v1/health     |
| dashboard   | http://localhost:3000/api/health        |

Quarkus services also expose `/q/health/live` and `/q/health/ready`.

**Running a single service directly** (e.g. against an already-running rest
of the stack):

```bash
cd services/ai-core && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8001
cd apps/dashboard && npm install && npm run dev
cd services/api-gateway && mvn quarkus:dev
cd services/db-writer  && mvn quarkus:dev
```

---

## Services

### api-gateway (Java 21 / Quarkus, port 8080)

- **Adapters** (`com.uniserve.adapters.email`, `...whatsapp`) — turn a raw
  inbound message into the canonical `ChannelMessageReceived` event and
  publish it. Email polls IMAP on a schedule (`EmailAdapter.scheduledPoll`)
  using the same Gmail App Password as outbound SMTP, and now also carries
  the message's `subject` line on the event (nullable — see
  [Subject-line ticket threading & dedup](#subject-line-ticket-threading--dedup)).
  **Machine-generated mail never enters the pipeline**: `EmailAdapter.isAutoGenerated`
  drops bounces, out-of-office and no-reply notification streams at ingestion
  (RFC 3834 `Auto-Submitted`, auto-responder/`Precedence` headers, DSN
  `multipart/report` content-types, null return-path, mailer-daemon /
  postmaster / *noreply* senders, and bounce/OOO subjects), with a matching
  sender/subject safety net in ai-core's dispatcher
  (`is_auto_generated_email`) and an outbound guard that refuses to email
  RFC 2606 reserved domains (`example.com` etc.) — a Gmail DSN once became a
  confirmed "technical complaint" from mailer-daemon via a
  seed→bounce→ticket feedback loop;
  WhatsApp is a Meta Business webhook validated via HMAC-SHA256
  (`WhatsAppSignatureValidator`) and has no subject concept.
- **Auth** (`com.uniserve.auth`) — JWT issuance/refresh/logout, RBAC-scoped
  ticket/agent/tenant endpoints, and the public citizen status lookup
  (`PublicStatusResource`).
- **Events** (`com.uniserve.events`) — `EventBusPublisher` (XADD to Valkey
  Streams + DLQ routing on failure), `EventStreams` (stream name catalogue).
- Every adapter/publisher stage logs at INFO with the transaction's
  `traceId` — see the tracing section below.

### db-writer (Java 21 / Quarkus, port 8090)

- Sole owner of the SQLite file (`quarkus.datasource.jdbc.url`, WAL mode).
- Flyway-managed schema (`db/migration/V1__initial_schema.sql`, etc.) — see
  [Data model](#data-model).
- `InternalKeyFilter` — pod-to-pod auth: requires a matching `X-Internal-Key`
  header on every `/api/v1/db/*` request once `DB_WRITER_INTERNAL_API_KEY`
  is non-empty (a no-op in default local dev).
- `RequestLoggingFilter` — logs every `/api/v1/db/*` request (method, path,
  status, duration, and the caller's `X-Trace-Id` when supplied) at
  INFO/WARN/ERROR depending on status code.
- `TicketCache` — Caffeine read cache (max 1000 entries, 2-min TTL,
  hardcoded — not env-configurable despite similarly-named doc'd env vars).
- `POST /api/v1/db/tickets/{id}/messages` — append a message (citizen text or
  AI/agent reply) to a ticket's timeline; used by ai-core's ticket-creation
  pipeline to record the original complaint and any duplicate follow-ups.

### ai-core (Python 3.11 / FastAPI, port 8001)

- `app/events/dispatcher.py` — the live consumer loop: reads
  `channel.message.received` off Valkey and hands each event to
  `ConversationAgent.process()`.
- `app/conversation/agent.py` — identity gate (declines to proceed until the
  citizen is identified or explicitly anonymous), info-gathering follow-up
  questions, and either the OpenAI Assistants API path (tool-calling
  `confirm_identity`/`submit_complaint`) or a deterministic rule-based
  fallback when no LLM key is configured. The rule-based path asks a
  structured intake question driven entirely by the tenant's **configurable
  per-channel intake fields** (`app/conversation/intake_fields.py`; see
  [Configurable per-channel intake fields](#configurable-per-channel-intake-fields))
  — it renders a numbered form of every askable field for that channel
  (marking which are required), extracts each field by its label, validates
  the numeric ones (10-digit mobile, 6-digit pin code), and re-asks only for
  whatever mandatory field is still missing or invalid. A field that's native
  to the channel (the email address on the email channel, the verified phone
  on WhatsApp) is auto-satisfied and never asked; a field already on file for
  a returning citizen is reused rather than re-requested. It remembers the
  original complaint text across that back-and-forth (saved to Valkey
  conversation state) so the ticket's initial message is the actual
  complaint, not the intake reply. The OpenAI Assistants path enforces the
  same mandatory-fields config in code, not just as a prompt hint — its
  system prompt/tool schema isn't regenerated per tenant, so it can't ask
  intelligently the way the rule-based path does, but
  `_update_intake_and_get_missing` runs the SAME extractor/validator every
  turn (merging across turns, so an earlier-satisfied field is never
  re-asked) and `_tool_confirm_identity`/`_tool_submit_complaint` are gated
  on the result: a verified channel (e.g. WhatsApp) still resolves identity
  immediately, but the ticket isn't surfaced as identity-confirmed (moving
  it into the dashboard's Confirmed queue) and `submit_complaint` is refused
  until the tenant's mandatory fields for that channel are actually present
  — fixing a real bug where a bare WhatsApp message with no name/email
  reached a fully "Confirmed" ticket despite both being mandatory.
  **Live-testing follow-up bug:** the label-anchored regex extractor
  (designed for the rule-based path's structured numbered-form replies)
  couldn't understand casual conversational replies at all — "Ashok,
  miscemail19@gmail.com" (no literal "name"/"email" words) or "I already
  provided the name… ashok" (the separator regex didn't recognise an
  ellipsis) both left the ticket stuck "pending" forever despite the model
  correctly identifying the citizen every time. Fixed by giving the model a
  direct channel to hand over what it already understood:
  `confirm_identity`'s `providedFields` argument (label → value, using the
  exact labels shown in that turn's instructions) is merged into the
  tracked intake state (`_merge_provided_fields`) and takes priority over
  the regex pass, which remains only as a cheap best-effort pre-check.
  `_extract_email` (and the other label extractors) also gained a
  word-boundary check — without it, "email" matched mid-word inside the
  citizen's own address (`miscemail19@gmail.com` contains "email" as a
  substring), silently truncating the captured value.
  **Contradictory identity-gate instructions for email (live-testing
  fix).** The Assistant's base instructions said to *ask* the citizen for
  an email/phone whenever the channel isn't "verified" — true for email
  (Meta-style channel verification doesn't apply to it), but the separate
  per-turn hint said the opposite ("never ask, it's already known from the
  From address"). Live testing showed the model resolving this
  contradiction by calling no tool at all on the first email turn, never
  confirming identity. Fixed by having the base instructions explicitly
  treat email's own From address the same as a verified channel for this
  decision — `confirm_identity` is called immediately either way, with the
  tenant's other required fields still tracked and gated separately.
  **Conversation memory (Valkey state + the OpenAI thread) is keyed by the
  ticket** (`_conv_key` → `ticket:<id>`), not the per-message email thread key,
  so a citizen's identity reply — which threads off *our* outbound email and so
  carries a different `In-Reply-To` — still finds the original complaint
  instead of starting over; the assistant path additionally carries the first
  message forward as `original_complaint` so it submits the complaint the
  citizen already sent rather than re-asking for it.
- `app/identity/resolver.py` + `db_client.py` — resolves a channel identity
  (phone/email/anonymous) to a canonical `master_id` via db-writer, merging
  across channels by matching phone/email. `_resolve_phone()` now also honours
  a citizen-*provided* email (`confirmedEmail`), not just an email native to
  the channel, so a WhatsApp-solicited email actually links/merges the two
  identities instead of being silently dropped. `db_client.py` also exposes
  `get_tenant_config()`, which the intake gate reads to know each channel's
  configured field list.
- `app/conversation/intake_fields.py` — the field catalog (Name, Mobile,
  Email, Service/Customer ID, Area Pin Code — each with an extractor +
  validator), the built-in per-channel defaults, and the helpers
  (`fields_for_channel`, `extract_configured_fields`, `missing_fields`,
  `build_identity_request_message`) that drive the configurable intake gate.
  See [Configurable per-channel intake fields](#configurable-per-channel-intake-fields).
- `app/notifications/sender.py` — consumes `ai.reply.send` (a third
  background consumer): actually delivers the conversation agent's replies
  (identity requests, follow-ups) via api-gateway's email or WhatsApp send
  endpoint, by channel. This event used to be published with nothing
  consuming it — the citizen never received the identity-request message,
  so no reply was possible and no ticket could ever form. The
  identity-request message also tells the citizen their ticket will be
  auto-closed after 14 days without a reply (see
  [Queue separation & ticket lifecycle](#queue-separation--ticket-lifecycle)
  below). The same module's `send_ticket_ack` sends a structured
  acknowledgment — carrying the ticket ID/number, category, and status — as
  soon as a ticket is created or a message is appended to an existing one
  (called from `dispatcher.py`'s `complaint.ready` handler, right after
  `create_ticket_from_complaint` succeeds). WhatsApp sends are subject to
  Meta's 24-hour customer service window (see
  [docs/02b_ADAPTER_WHATSAPP.md](docs/02b_ADAPTER_WHATSAPP.md)) — a
  pre-approved template message fallback outside that window is not
  implemented, so a send attempted outside it fails.
- `app/tickets/intake.py` — `ensure_ticket_stub`/`update_ticket_identity`:
  called from `dispatcher.py` the instant a `channel.message.received` event
  arrives, before the conversation agent even runs, so a ticket exists (and
  is visible somewhere in the dashboard) from the citizen's very first
  message — see
  [Queue separation & ticket lifecycle](#queue-separation--ticket-lifecycle).
- `app/tickets/service.py` — consumes `complaint.ready` (a second background
  consumer): scores priority and updates the stub ticket already created
  for this thread in place — either as that ticket's first-ever complaint
  (sets category/priority/etc.) or as a continuation (just appends the
  message), decided purely from the ticket's own state, never by comparing
  against other tickets. Falls back to the coarser identity+category dedup
  heuristic only for callers that bypass the live pipeline entirely (no
  stub at all — direct/test calls). See
  [Subject-line ticket threading & dedup](#subject-line-ticket-threading--dedup).
- `app/classify`, `app/pii`, `app/priority`, `app/dedup` — classification,
  PII scrubbing, priority scoring, and cross-channel dedup; each is also
  exposed as a standalone internal HTTP endpoint for direct testing, and
  `dedup`/`priority`/`classify` are also used in-process by the ticket
  pipeline above (PII scrubbing is not yet wired into the automatic flow).
  **Priority scoring is now rubric-aware** (`app/priority/llm_scorer.py`): when
  a tenant has configured a free-text `priorityRubric` *and* an OpenAI key is
  present, `create_ticket_from_complaint` asks the LLM to score priority by
  applying that rubric (strict-JSON `{score,label}`); otherwise — no rubric, no
  key, or any LLM error/timeout — it transparently falls back to the
  deterministic weighted engine (`app/priority/engine.py`). See
  [Configurable priority rubric & general settings](#configurable-priority-rubric--general-settings).
- Every stage logs at INFO with the transaction's `traceId` (see below);
  `DbWriterClient` sends it onward as `X-Trace-Id` on every call to
  db-writer.

### dashboard (Next.js 14, port 3000)

- `src/app/page.tsx` — landing page (agent sign-in / track-a-complaint
  links).
- **Backgrounds** — the login brand panel and every `/dashboard` route
  (via `src/app/dashboard/layout.tsx`) render layered, colourful backdrops:
  a gradient/glow treatment that also acts as the fallback, with an
  OPTIONAL image layer underneath. Drop images at
  `public/backgrounds/login-hero.jpg` (hero for the login page's SIGN-IN
  side, shown under a light veil plus a white radial pool behind the form
  card so it stays readable; the navy brand/news panel is deliberately
  image-free for headline readability) and
  `public/backgrounds/app-wash.jpg` (wide, subtle texture for the dashboard,
  shown under a strong pale-teal→gold veil so white panels stay readable) —
  a missing file fails silently and the gradients render alone. No code
  change or restart needed when adding/swapping the images.
- `src/app/login/page.tsx` — agent login, split layout (UI_REVAMP_v2 §A4):
  navy brand panel with tagline, the **BBC Tamil headlines widget**
  (`src/components/news/NewsWidget.tsx`, fed by the RSS-parsing `/api/news`
  route — no API key) and the **public announcement ticker**
  (`AnnouncementTicker.tsx`, CSS marquee, hidden when empty); sign-in card on
  the right with the original submit logic unchanged.
- `src/app/dashboard/page.tsx` — role-gated agent dashboard (Analytics /
  Ticket Queue / Administration) wrapped in the UI_REVAMP_v2 §A3 shell:
  sticky **topbar** (`src/components/layout/Topbar.tsx` — teal wordmark,
  announcement bell with unread badge + mark-all-read, role pill, logout) and
  a collapsible **sidebar** (`Sidebar.tsx` — w-56/w-14 with a 200ms
  transition, teal active accents; becomes a bottom tab bar ≤768px) that
  drives the same tab state the old top tab bar did. A dismissible
  **announcement banner** (`AnnouncementBanner.tsx`, per-session dismissal)
  renders under the topbar. Status/priority/identity badges use the shared
  palette (`src/lib/badges.ts`); brand colours live in
  `src/lib/design-tokens.ts` (UI_REVAMP_v2 §A1). The Ticket Queue shows admins and leads a
  **Confirmed vs "Needs identity" scope toggle** (Confirmed →
  `?identityStatus=confirmed`, Needs-identity →
  `?identityStatus=pending,anonymous`) and an **Identity** column, so
  not-yet-resolved stub tickets are viewable in their own queue and move to the
  main (Confirmed) queue automatically once identity resolves; agents still see
  only their own assigned tickets with no toggle. The queue also shows
  **Name / Email / Mobile** columns (the citizen behind each ticket, joined from
  the identity profile), **server-side sortable column headers** (click to sort
  by any column incl. the citizen fields; default **newest-first** by created
  date), and **pagination** (30 per page by default, selectable 30/50/100, with
  Prev/Next + total-count navigation above the table). It **auto-refreshes every
  30s**, has a **manual Refresh button**, and **persists its view state**
  (scope, page, page size, sort) in `sessionStorage` — so returning from a
  ticket-detail page refreshes the list and lands the user back on the same
  queue scope they left.
- `src/components/analytics/AnalyticsPanel.tsx` — real charts (via
  `recharts`): ticket volume (stacked bar by day/channel), SLA performance
  (donut), priority distribution (horizontal bar), and agent performance
  (bar, lead/admin only). Filter bar: time frame, agent (lead/admin can pick
  any agent; a plain agent is locked to their own), customer (typeahead
  search), priority, category — backed by `GET /api/v1/analytics/*`
  (`AnalyticsResource.java`, api-gateway) proxying db-writer's extended
  `AnalyticsResource.java`, which now accepts `agentId`/`identityId`/
  `category`/`priorityLabel` filters on top of the existing tenant + rolling
  `period` window, and excludes archived tickets.
- `src/components/admin/TeamPanel.tsx` — Administration → Team sub-tab:
  lists every agent/lead/admin in the tenant (`GET /api/v1/agents`) with
  role/active-status badges; "Add new" reveals the create form (refreshes
  the list on success); "Edit" opens a panel to change name/role/active and
  optionally reset a password directly (no reset-link email flow) — email
  is shown read-only and rejected server-side if sent in a PATCH
  (`EMAIL_IMMUTABLE`, `AgentAdminResource.java`). Field-level validation
  (name required, email format, 8+ char passwords, role enum, duplicate-email
  check) runs both client-side and in `AgentAdminResource`/`AgentService`.
- `src/components/admin/IntakeFieldsPanel.tsx` — Administration → Intake Fields
  sub-tab: the per-channel intake-field matrix (see
  [Configurable per-channel intake fields](#configurable-per-channel-intake-fields)).
- `src/components/admin/PriorityRulesPanel.tsx` — Administration → Priority
  Rules sub-tab: a free-text editor (pre-filled with the current default
  rubric) for the tenant's AI priority rubric; saves to
  `PUT /api/v1/tenant/priority-rubric`.
- `src/components/admin/GeneralSettingsPanel.tsx` — Administration → Settings
  sub-tab: tenant general settings (currently the max follow-up-question count,
  0–5); saves to `PUT /api/v1/tenant/general-settings`. Both panels are
  described in
  [Configurable priority rubric & general settings](#configurable-priority-rubric--general-settings).
- `src/components/admin/AnnouncementsPanel.tsx` — Administration →
  Announcements sub-tab: active + expired/inactive lists with
  create/edit/deactivate/delete (modal with char counters, optional expiry
  date, active toggle) against `/api/announcements`.
- `src/components/admin/SystemPanel.tsx` — Administration → System sub-tab:
  live service-health dots (api-gateway/db-writer/ai-core via
  `/api/system/health`, 30s auto-refresh + manual refresh) and the
  **danger-zone database reset** — a non-dismissible modal requiring the
  admin's current password AND typing `RESET` exactly; the confirm button
  stays disabled until both are valid, then handles 401 (wrong password),
  429 (rate-limited), and success (toast + redirect to login).
- `src/app/dashboard/tickets/[id]/page.tsx` — ticket detail, two equal
  columns: the **left column is reference material** — the conversation
  timeline (own scroll region) above the **Audit trail** (own scroll,
  newest-first: created / assignments / status transitions with actor +
  timestamp); the **right column is everything the agent acts on** — citizen
  details (Name/Email/Phone/Service-Customer-ID, read-only, sourced from the
  ticket's identity + a `tickets.service_id` column), the **Status &
  internal note** panel (one note textarea with a grey "Add internal note"
  placeholder + one button per allowed next status — the note rides along
  with the transition; a small "Save note only" link covers notes without a
  status change), **"Ask a follow-up / update the customer"** (a **Send**
  button with a busy spinner and an explicit ✓ sent / ✗ failed confirmation,
  so a connection failure is never silent), and the internal-notes history
  list.
  Service/Customer ID is populated by ai-core going forward
  (`create_ticket_from_complaint`); tickets from before that column existed
  fall back to a regex parse of the first message's text
  (`TicketsResource.detail()`). Sending an update calls
  `POST /api/v1/tickets/{id}/reply`, which records the outbound message and
  — for email- or WhatsApp-origin tickets — actually sends it via
  `EmailAdapter.sendReply`/`WhatsAppAdapter.sendReply` (response fields
  `sent`/`sendError`; other, Phase-2 channels just record the message with
  no outbound send). "Assigned to" is an editable select (lead/admin
  only, `PATCH /api/v1/tickets/{id}/assign`) resolved to the agent's name
  via `TicketsResource.agentDirectory()`; agents see the name read-only.
  The Ticket Queue table shows the same resolved name in its own
  "Assigned to" column.
- `src/app/status/[ref]/page.tsx` — public, unauthenticated, server-rendered
  citizen status lookup by `TKT-XXXXX` ticket number, `ANON-XXXX` ref, or
  email; calls api-gateway's `GET /api/v1/public/status/{ref}` server-side.
- `src/app/page.tsx` — the public landing page (`/`). Was a bare placeholder
  whose "Track a complaint" link pointed at a hardcoded example ref
  (`ANON-TEST`) — no real way for a citizen to look up their OWN complaint.
  Now a branded, high-contrast hero with a working search form that submits
  to `/status/{value}` (client-side `router.push`), matching what
  `PublicStatusResource` accepts — **not** a phone number, so the copy
  deliberately doesn't imply that works. "Agent sign in" is kept as a
  small, secondary link to `/login` — citizens are this page's primary
  audience, not staff.
- `src/app/api/*` — Next.js route handlers acting as a thin BFF: proxy to
  api-gateway, forwarding the JWT cookie.
- The fuller component library documented in
  [12_AGENT_DASHBOARD](docs/12_AGENT_DASHBOARD.md) (separate route groups,
  charts, filter panels) is scaffolded as the target design; the current
  Phase-1 implementation is functional-minimal — one role-gated page per
  area rather than the full page/component tree.

---

## Event bus & streams

Valkey (Redis-compatible) Streams, one stream per event type per tenant:
key format `{tenantId}:{streamName}`.

| Stream | Producer → Consumer | Purpose |
|---|---|---|
| `channel.message.received` | api-gateway → ai-core | New inbound message, any channel |
| `identity.resolved` | ai-core → ai-core, db-writer | Citizen identity confirmed/created |
| `identity.pending` | ai-core → ai-core | Identity gate awaiting a reply |
| `complaint.ready` | ai-core → ai-core (ticket pipeline) | Enough info gathered to file a ticket |
| `ticket.created` / `ticket.updated` | db-writer → dashboard, notifications | Ticket lifecycle |
| `ai.reply.send` | ai-core → ai-core (notification sender) → api-gateway | Outbound reply to actually send to the citizen |
| `dlq` | any consumer, on failure | Dead-letter queue for manual review |

- Java side: `EventBusPublisher` (`XADD` + `publishToDlq`).
- Python side: `BasePublisher`/`BaseConsumer` (`app/events/`) — automatic
  retry (`EVENT_BUS_MAX_RETRIES`, default 3) then dead-letter.
- Health: `GET /api/v1/health/eventbus` on api-gateway.
- **`complaint.ready` → ticket creation is wired** (`app/tickets/service.py`,
  consumed by a dedicated background consumer in ai-core): dedup check →
  priority scoring → `POST /api/v1/db/tickets` (+ an initial
  `POST .../messages`) for a new complaint, or a `POST .../messages` append
  onto the existing open ticket for a duplicate. See
  [06_to_10_AI_PIPELINE](docs/06_to_10_AI_PIPELINE.md).

---

## Data model

SQLite, WAL mode, Flyway-migrated (`services/db-writer/src/main/resources/db/migration/`).
See [05_TICKET_SCHEMA](docs/05_TICKET_SCHEMA.md) for full DDL.

| Table | Key fields |
|---|---|
| `tenants` | `id`, `name`, `slug` (unique), `deployment_mode`, `llm_provider`, `config_json` |
| `agents` | `id`, `tenant_id`, `name`, `email` (unique/tenant), `password_hash`, `role` (admin\|lead\|agent), `is_active` |
| `identity_profiles` | `id`, `tenant_id`, `master_id` (unique), `name`/`email`/`phone`, `channel_ids_json`, `is_anonymous`, `anon_ref_id` (e.g. `ANON-7X3K`), `merged_into` |
| `tickets` | `id`, `tenant_id`, `ticket_number` (e.g. `TKT-00142`), `identity_id`, `identity_status` (pending\|anonymous\|confirmed), `assigned_to`, `status` (open\|assigned\|in_progress\|pending_customer\|resolved\|closed\|reopened — `pending_customer` added by `V9`, a table rebuild since SQLite can't alter a CHECK), `category`/`subcategory`, `priority_score` (0–10), `priority_label`, `sentiment_score`, `channel_origin`, `thread_id`, `archived_at`, `is_duplicate`, `parent_ticket_id`, `service_id`, `sla_due_at` |
| `ticket_messages` | `channel`, `direction`, `author_type` (ai\|agent\|user\|system), `content`, `media_urls_json`, `is_ai_generated` |
| `ticket_notes` | `content`, `is_mandatory`, `transition_from`/`transition_to` |
| `ticket_events` | `event_type`, `actor_type`, `actor_id`, `meta_json` (full audit trail) |
| `identity_pending_queue` | `thread_id`, `channel`, `channel_identity_value`, `raw_message`, `timeout_at` (default 48h) |
| `announcements` | `tenant_id`, `title` (≥3 chars), `body` (≥10 chars), `created_by` (agent), `is_active`, `expires_at` (NULL = never; evaluated at read time, no sweep), `created_at`/`updated_at` — migration `V8__announcements.sql` |

**Ticket status flow:** `Open → Assigned → In-Progress → Resolved → Closed`,
with `Closed → Reopened → In-Progress`, and `In-Progress ⇄ Pending-Customer`
(the agent asked the citizen a question and parks the ticket awaiting their
reply; also `Pending-Customer → Resolved`). Any role may move a ticket to
pending-customer (`ticket.status.to_pending_customer`). Mandatory
≥20-character notes are enforced (application layer) on In-Progress→Resolved,
Resolved→Closed, and Closed→Reopened.

**Dev seed logins** (tenant `t1`, "TNEB Demo"): `admin@tneb.demo` /
`Admin@123`, `lead@tneb.demo` / `Lead@123`, `agent@tneb.demo` / `Agent@123`.
Every service's `TENANT_ID` must default to `t1` for these logins to see any
data — every `.env`/`.env.local`/`.env.example`/docker-compose default was
originally `"default"` instead, a separate, empty-config tenant with no
seeded agents, so any data created by the live pipeline was invisible to
every dev login. Fixed (env defaults now `t1`; `V4__realign_default_tenant_data.sql`
moved any data that had already accumulated under `"default"`) — if you're
troubleshooting "logged in but see zero tickets" again, check
`TENANT_ID`/`NEXT_PUBLIC_TENANT_ID` in whichever `.env.local` actually loaded.

**`tickets.identity_id` caveat:** `identity_profiles` has two identifiers —
its primary key `id`, and a separate `master_id` business field. ai-core's
identity resolver (Feature 03 → the automatic `complaint.ready` → ticket
pipeline) always writes `master_id` into `tickets.identity_id`, and both
`PublicStatusResource` (citizen status lookup) and `GET /api/v1/db/identities/{id}`
(tries the primary key first, falls back to `master_id`) have been aligned
to that. **`IdentityService.merge()` was not** — it still reassigns tickets
by primary key, so if identity merging is ever wired into an automatic flow,
it needs the same `master_id` fix first. Not urgent today since nothing
currently triggers a merge automatically.

---

## Queue separation & ticket lifecycle

A ticket row now exists from the moment a channel message arrives — not
only once identity is confirmed and enough complaint detail is gathered.
This replaced an earlier gap where a citizen who emailed or WhatsApp'd in
saw nothing happen (no ticket, no visible record) until the entire
identity + complaint-gathering flow completed.

- **Stub creation.** `dispatcher.py`'s `channel.message.received` handler
  calls `ensure_ticket_stub` (`app/tickets/intake.py`) *before* handing the
  event to the conversation agent: it looks up a ticket already tracking
  this `threadId`, or creates a bare one (`identityStatus=pending`,
  `status=open`, no category yet). `tickets.thread_id` exists specifically
  for this — Valkey conversation state expires after
  `CONVERSATION_STATE_TTL_HOURS` (default 2h), far too short for a thread
  that might sit unconfirmed for days.
- **Update in place, never re-create.** As identity resolves and complaint
  details arrive, the *same* ticket row is updated (`update_ticket_identity`
  as soon as identity resolves; `create_ticket_from_complaint` fills in
  category/priority/etc. once the complaint is ready) — a thread never
  produces two ticket rows. If a complaint dedups to a *different* existing
  ticket, this thread's own stub is linked as a duplicate
  (`isDuplicate=1`, `parentTicketId=<canonical>`, `status=closed`) instead
  of being left stranded pending forever.
- **Two queues, one filter.** The dashboard's Ticket Queue passes
  `identityStatus=confirmed`; a separate Unconfirmed queue passes
  `identityStatus=pending,anonymous` (`GET /api/v1/tickets?identityStatus=`).
  A ticket crosses from Unconfirmed to the main queue automatically the
  moment its identity resolves — no manual move needed.
- **Two independent cleanup mechanisms** (don't confuse them):
  - **Auto-close (14 days, automatic).** `TicketAutoCloseScheduler`
    (api-gateway, `@Scheduled(every = "{ticket.auto-close.interval}")`,
    default hourly) calls db-writer's
    `POST /api/v1/db/tickets/auto-close-unconfirmed`, which transitions
    every `identityStatus=pending` ticket older than 14 days to
    `status=closed` (with a system note) — across every tenant, since it's
    a background schedule, not an admin action. Each closed ticket gets the
    same structured status-update email as a manual close (see
    [Citizen-facing notifications](#citizen-facing-notifications)) when an
    email address is on file.
  - **Archive-stale (60 days, admin-triggered).** A manual button in the
    dashboard's Administration tab (`admin.tickets.archive-stale` RBAC
    action) calls `POST /api/v1/tickets/archive-stale`, which soft-deletes
    (`archived_at` set, never physically deleted) tickets with
    `identityStatus in (pending, anonymous)` older than N days (default
    60). Archived tickets are hidden from every queue
    (`includeArchived=false` is the default on every list call) but remain
    fully retrievable with `includeArchived=true`.

## Citizen-facing notifications

Every citizen-facing notification is structured (ticket ID/number,
category, status) and delivered through api-gateway's
`EmailAdapter.sendReply` (email-origin tickets) or
`WhatsAppAdapter.sendReply` (WhatsApp-origin tickets, Meta Graph API) — any
other, Phase-2 channel is logged as "not delivered" rather than sent.
WhatsApp sends are also subject to Meta's 24-hour customer service window
(no pre-approved template message fallback is implemented — see
[docs/02b_ADAPTER_WHATSAPP.md](docs/02b_ADAPTER_WHATSAPP.md)).

- **Identity request.** Sent when the identity gate can't resolve who's
  writing in; now explicitly states the request will be auto-closed after
  14 days without a reply (`IDENTITY_REQUEST_MESSAGE`,
  `app/conversation/agent.py`). WhatsApp is normally exempt from this in
  practice — its identity is pre-confirmed by Meta (see
  [Channel identity rules](docs/02f_ADAPTER_CONTRACT.md)) — but the send
  path itself is channel-agnostic.
- **Ticket acknowledgment.** Sent once a ticket is created *or* a message
  is appended to an existing one — carries the ticket ID/number, category,
  and status (`send_ticket_ack`, `app/notifications/sender.py`,
  called from `dispatcher.py`'s `complaint.ready` handler). Best-effort: a
  failed send never rolls back the ticket write.
- **Status update on resolve/close.** Sent only when a ticket transitions
  *to* `resolved` or `closed` — not on other transitions, and not for a
  standalone "add note" action — including the mandatory transition note's
  content (`TicketNotifier.sendStatusUpdate`, api-gateway, shared by
  `TicketsResource`'s manual transition endpoint and
  `TicketAutoCloseScheduler`'s automatic 14-day close).

All three require an email address or phone number on file matching the
ticket's origin channel (either the ticket's `identity_id` resolving to an
`email`/`phone` on the identity record, or — for the identity-request
message — the raw address/number the citizen wrote in from) and silently
no-op otherwise (e.g. a ticket that never got far enough to have an
identity record at all, or a Phase-2 channel). Every email subject that
carries a ticket number also gets `[Ticket TKT-XXXXX]` appended, and the
body a "please don't remove the ticket number from the subject" note
(`DO_NOT_REMOVE_NOTE`, `app/notifications/sender.py`) — see below for why
that matters. WhatsApp has no subject line and doesn't dedup by it (see
below), so that note is intentionally omitted from WhatsApp sends.

## Subject-line ticket threading & dedup

**The bug:** a citizen who emailed in a genuinely new, unrelated complaint
could see it silently appended as a note onto an old *different* open
ticket, just because it classified into the same category as that other
ticket. The previous dedup (`app/dedup/service.py`'s `check_duplicate`)
matched on identity + category + open-status alone — too coarse a signal
once a citizen has more than one thing going on with the same category.

**The fix:** every outbound email's subject now carries the ticket number
(`[Ticket TKT-00042]`), and an inbound email's subject — or, since Feature
17, the raw message BODY of any channel — is checked for that same
reference before anything else (`extract_ticket_number`,
`app/tickets/intake.py`) — a citizen's reply always preserves the subject
line (as "Re: ..."), so this is a precise, citizen-visible signal rather
than an inferred one, and a citizen on any channel typing "following up on
TKT-00042" gets the same precise resolution. `ensure_ticket_stub` resolves
in this order:

1. A swipe-reply / `In-Reply-To` quoted-message id matching a ticket's own `origin_message_id` (Feature 19 — see below).
2. An explicit `TKT-XXXXX` reference (subject or message body) → that exact ticket, regardless of thread/category/status.
3. Otherwise, for a channel with no subject line (WhatsApp), when the message is nothing but intake-form data and the citizen has exactly one still-in-intake stub → that stub (Feature 20 — see below).
4. Otherwise, for a channel with no subject line (WhatsApp): identity + open-ticket-count/topic (see below).
5. Otherwise, the existing thread (`threadId` — via In-Reply-To/References headers for email; a stable per-phone key for WhatsApp), but **only if that ticket is still open** (Feature 17 — see below).
6. Otherwise, a brand-new stub ticket — this is what a genuinely new complaint gets.

Because of this, `create_ticket_from_complaint` (`app/tickets/service.py`)
no longer runs the identity+category dedup for any message that already
has a stub (steps 1–2 above found something, or created a new one) — it
only decides "continuation vs. this ticket's first message" from the
ticket's *own* state (does it already have a category set?), never by
comparing against *other* tickets. The old category-based heuristic
remains only as a fallback for callers that bypass the live pipeline
entirely (no stub at all — direct/test calls), where there's no
thread/subject signal available. `EmailAdapter.parseMessage` (api-gateway)
and the `ChannelMessageReceived` event both carry this subject line
end-to-end (`subject` field, nullable — WhatsApp has none).

**Thread-key collapse fix.** `ConversationAgent._thread_key()` used to fall
back to `email:<address>` whenever an inbound email had no real `In-Reply-To`
header — a key identical for *every* email that address ever sent, so a
brand-new, unrelated complaint collapsed onto whatever ticket that address
last had open. It now falls back to `email:<message-id>` (unique per message)
instead, so two unrelated emails from the same sender get distinct thread
keys. WhatsApp's address-based fallback is deliberately unchanged — one
persistent thread per phone number is correct there. Regression-tested in
`tests/test_thread_key.py`.

**Outbound reply-chain threading (RFC 5322).** Every inbound email's own
`Message-ID` is now captured end-to-end — `EmailAdapter.extractMessageId`
(api-gateway) → `ChannelMessageReceived.messageId` → `tickets.origin_message_id`
(migration `V7__ticket_origin_message_id.sql`), set once when the stub is
created. Every reply UniServe sends (identity request, ack, notes-triggered
update, status change) now threads back into the original chain by passing
that stored value as `EmailAdapter.sendReply(...)`'s `inReplyToMessageId`
(sets both `In-Reply-To` and `References`). Previously every caller
(`/test-send`, `TicketsResource.reply()`, `TicketNotifier`, and ai-core's
`app/notifications/sender.py`) hard-coded `null`, so replies arrived as
disconnected new emails. `app/tickets/service.py` returns `originMessageId`
from `create_ticket_from_complaint` so `dispatcher.py` can thread the ack too.

**WhatsApp threading fix (Feature 17).** WhatsApp has no subject line, so
its thread key (`whatsapp:<phone>`) is the SAME for every message that
number ever sends — the bug was that the threadId lookup applied no status
filter at all, so a citizen whose ticket had already been resolved, texting
weeks later about something unrelated, got silently appended to the old,
resolved ticket instead of starting a new one. Fixed in `ensure_ticket_stub`
(`app/tickets/intake.py`):
- The threadId fallback now requires the ticket still be OPEN
  (`open,assigned,in_progress,reopened` — `app/dedup/service.py`'s
  `OPEN_STATUSES`, now also including `reopened`, which it was previously
  missing).
- For a channel with no subject line at all (WhatsApp today), resolution
  now tries identity + open-ticket count BEFORE the threadId match, not
  after: zero open tickets → new; exactly one → append (the same
  identity+open-status logic `check_duplicate` already used for the
  no-stub case); two or more → still create a NEW ticket rather than
  guessing which one this continues — a wrong silent merge is worse than
  an extra ticket an agent can merge by hand. The threadId match is now
  reached ONLY as a fallback for the narrow window before identity has
  linked to any ticket yet — **live-testing found it used to run FIRST**,
  which meant it always won as long as a single ticket for that phone
  number was open, silently reusing it for a genuinely unrelated new
  complaint ("Put not closed" got appended onto an existing "No power"
  ticket) — the exact "too coarse a signal" failure category-based dedup
  had for email, recreated one layer deeper.
- **Fixed (exactly one open ticket, different topic) — Feature 18.**
  Count-based resolution alone genuinely cannot distinguish "a follow-up on
  my one open ticket" from "an unrelated second complaint, and I happen to
  have exactly one other open ticket" — both look identical by count
  alone, and a keyword classifier can't help either (an uncategorizable
  message like "Put not closed" gives no signal either way). Closed with a
  real content-level judgment — see "Message quality" below.
- **Fixed (swipe-reply resolves directly) — Feature 19, see below.**
- **Fixed (the message is an intake ANSWER, not a complaint) — Feature 20,
  see below.**
- **Not implemented:** an interactive "which of your N open complaints is
  this?" back-and-forth for the 2+-open-tickets case — today it just
  creates a new ticket, which an agent can merge manually via the
  dashboard if needed.

**Status inquiries (Feature 17).** "What's the status of my complaint?" is
a fundamentally different kind of message — a read-only question about an
EXISTING complaint, never gated on identity/mandatory fields and never
itself treated as a new complaint to file. Detected channel-agnostically
(same logic for email and WhatsApp): the rule-based path uses a regex
requiring an explicit status/update/progress word near
complaint/ticket/issue/case (`_STATUS_INQUIRY_RE`,
`app/conversation/agent.py`, deliberately narrow so genuine complaint
wording like "my complaint is that my meter isn't working" never
false-positives); the assistant path gets a `check_complaint_status` tool
instead (`app/conversation/tools.py`), which the model calls on its own
judgement. Both paths call the same `summarize_recent_tickets`
(`app/conversation/status_lookup.py`): resolve identity by the citizen's
phone/email, pull their last 5 tickets (`GET /api/v1/db/tickets?identityId=
...&sortBy=createdAt&sortDir=desc&pageSize=5` — already supported the
`identityId` filter, no db-writer change needed), and for each ticket look
up its most recent internal note (`ticket_notes`, falling back to the most
recent outbound message if the ticket has no notes yet) as the "last
action taken." The summary text is composed by code, not left to the LLM
to paraphrase, so a citizen can never be told a hallucinated status or
note — the assistant path is instructed to relay it verbatim.
**Operational note:** the Assistant's tool schema lives on OpenAI's
platform, created once via `scripts/create_assistant.py` — that script only
ever *creates* a new Assistant, so adding `check_complaint_status` to
`ASSISTANT_TOOLS` doesn't reach an already-existing, deployed Assistant on
its own. Run the new `scripts/update_assistant.py` once to push the updated
tools/instructions onto the existing `OPENAI_ASSISTANT_ID`.

**Message quality — coherence & same-topic checks (Feature 18).** Two
related content-level judgments, both live-testing-driven, both in the new
`app/classify/message_quality.py` (a plain chat-completion call — same
pattern as `app/priority/llm_scorer.py`, not the Assistants gateway — so it
needs only an API key, no assistant id) and both **best-effort**: any
error/timeout/missing key returns `None`, and every caller treats that as
"assume the safe default" — a false rejection/split here is worse than a
false negative, since a citizen whose real complaint gets silently dropped
has no other way to complain.

- **`assess_coherence(text)`** — is this message clear enough to act on, or
  does it read as gibberish/a garbled typo? Brevity/vagueness alone is
  explicitly NOT the test ("no power" is coherent) — only text a human
  agent genuinely couldn't act on qualifies. Channel behaviour deliberately
  differs, per what was asked for:
  - **Email — hard reject, no ticket at all.** `dispatcher.py`'s
    `_handle_channel_message` calls this BEFORE `ensure_ticket_stub`, so an
    incoherent email never gets a ticket stub (or a ticket number) — a
    polite rejection is sent directly (`send_email`, no ticket to thread
    it against) and the pipeline stops there.
  - **WhatsApp — ask for confirmation, not reject.** A stub already exists
    by the time this matters (Feature 12's "every message gets a stub"
    still holds for WhatsApp), so instead `submit_complaint`'s new
    `is_coherent` argument (the model's own honesty check on its
    `complaint_summary`) is enforced in code in
    `_process_via_assistant`'s `execute_tool` — `false` refuses the call
    and tells the model to ask the citizen to confirm/clarify rather than
    file it, mirroring the Feature 17 mandatory-fields refusal pattern
    exactly (model reports its understanding via a tool argument; code
    enforces the consequence, not just a prompt hint).
- **`is_same_topic(existing_text, existing_category, new_text)`** — closes
  the Feature 17 gap noted above: `ensure_ticket_stub`'s "exactly one open
  ticket → append" default couldn't tell a genuine follow-up apart from an
  unrelated second complaint, and a keyword classifier gives no signal
  either way for an uncategorisable message. Now, when there's exactly one
  open ticket, its original complaint text is fetched
  (`db.get_messages` → first inbound message) and compared against the new
  message; only a confident "different topic" creates a new ticket instead
  of appending. Live-tested regression case: "No power" (existing ticket)
  vs. "Put not closed" (new message) — same identity, one open ticket,
  correctly recognised as different complaints.
- **Rule-based (no-LLM) fallback:** both checks are LLM-only and simply
  don't run without an API key (`available()` returns `False`) — the
  rule-based path's existing behaviour (file a vague complaint after one
  follow-up; append-on-exactly-one-open-ticket with no content check) is
  unchanged, same graceful-degradation pattern as rubric priority scoring.

**Swipe-reply / In-Reply-To ticket matching (Feature 19).** Even Feature
18's same-topic judgment can misfire on a short, context-free follow-up —
live-tested: a citizen swipe-replied to their own "Voltage fluctuation in
my area" WhatsApp complaint (ticket TKT-00014) with just "It happens
around 11PM"; the LLM same-topic check had no way to know a swipe-reply
had happened and judged the two as unrelated, creating a needless
duplicate ticket (TKT-00015) instead of appending to the one being
replied to. A WhatsApp swipe-reply's quoted-message id (Meta's
`context.id`) was already captured end-to-end as `inReplyTo`
(`WhatsAppParser` → `ChannelMessageReceived.inReplyTo` → the event
payload) but never consumed — it was wired for *outbound* reply
threading only. `ensure_ticket_stub` now checks it FIRST, ahead of even
an explicit `TKT-XXXXX` reference in the text: if `inReplyTo` matches
some ticket's own `origin_message_id`, that ticket is used directly, no
text/identity/topic judgment involved — a citizen taking an explicit "reply
to this message" action is the least ambiguous continuation signal there
is. Requires a new `originMessageId` filter on db-writer's
`GET /api/v1/db/tickets` (`TicketService.buildWhere`), since this is now a
"find the ticket this specific message originated from" lookup, not just
by ticket number/thread/identity. Works for email too (an
`In-Reply-To` header maps to the same `inReplyTo` field), though email
already has robust subject-line matching — this is an extra safety net
there (e.g. a mail client that strips the `[Ticket TKT-XXXXX]` tag from
"Re:" subjects).

**Intake answers are not new complaints — and email typo detection (Feature
20).** Features 17–19 each tuned the question "is this a NEW complaint or a
continuation?" for messages that are, one way or another, *about* a
complaint. None of them considered the other half of every WhatsApp
conversation: the citizen answering the intake form UniServe just sent them.
Live-tested failure (`+918939014142`, three messages, three tickets):

| # | Citizen sent | What happened | What should have happened |
|---|---|---|---|
| 1 | "No power in my area" | stub **TKT-00016**, AI asks for name/email/service ID | ✔ correct |
| 2 | "Nithya", "Nithya@gmaill.com", "56784567" | **new ticket TKT-00017**, marked confirmed, typo email accepted onto the identity profile | stay on TKT-00016, save the name + service ID, query the `gmaill.com` typo |
| 3 | "dharshini.s.raj@gmail.com" | **new ticket TKT-00018**, whose recorded "complaint" was the citizen's own email address | update TKT-00016's identity and move it to the confirmed queue |

Four distinct defects, fixed together:

- **Root cause — the topic check was asked a question it cannot answer.**
  An intake answer names no subject, location, or problem, so Feature 18's
  `is_same_topic` answers "different topic" *correctly by its own
  definition*, and `ensure_ticket_stub` turned each answer into its own
  ticket. Fixed with a guard *ahead of* the topic judgment rather than a
  change to it (`app/tickets/intake.py`): a ticket with **no `category`**
  has never had a complaint filed on it — it is a stub still mid-intake —
  and `looks_like_intake_answer(raw_text)` decides whether this message is
  purely form data. Both conditions must hold, so genuine complaint prose
  still splits off its own ticket exactly as Feature 18 intended. Checked
  even when several tickets are open (as long as exactly one is still in
  intake), so a thread this bug already split self-heals on the next reply
  instead of shedding another ticket per message.
- **`looks_like_intake_answer` is deliberately deterministic — no LLM.** It
  decides whether to even *ask* the LLM topic question, so routing an
  identity answer must not itself depend on an LLM being reachable. It
  requires a structural signal (an email address, a form label, a bare 4+
  digit identifier, or a one-to-two-word bare name) AND rejects the message
  outright if any token is a statement/complaint word (`not`, `still`,
  `working`, `broken`, `power`, `bill`, `leak`, `update`, …). That negative
  check is what stops "my phone is not working" reading as a Mobile-field
  answer just because "phone" is a field label. Erring is one-directional
  by design: a missed intake answer only costs the Feature-18 topic check
  being consulted, i.e. the pre-Feature-20 behaviour.
- **Cascade — a split ticket also wipes the conversation.** Because Valkey
  state and the OpenAI thread are keyed on the ticket
  (`ConversationAgent._conv_key` → `ticket:<id>`), each spurious ticket also
  reset the assistant's memory of the original complaint — which is why
  message 3's ticket recorded the citizen's own email address as the
  complaint text. Fixing the routing fixes this; no state-keying change was
  needed.
- **Email validation (`app/conversation/intake_fields.py`).** The `email`
  field's validator was literally `lambda v: bool(v)` — any non-empty string
  passed, so `gmaill.com` was accepted, written onto the identity profile,
  and every future notification to that citizen would have bounced into
  nothing. Now two levels: a permissive RFC-lite syntax check
  (`is_email_syntax_valid`), plus `suggest_email_correction` — a
  **Damerau**-Levenshtein-distance-1 match against the consumer domains
  citizens actually use (`KNOWN_EMAIL_DOMAINS`, India-weighted). Transposition
  is not an optional extra: `gmial.com` and `hotmial.com` are two of the
  commonest real mistypings and both are distance **two** under plain
  Levenshtein. A domain that IS in the set is always accepted (so
  `mail.com`, one character from `gmail.com`, is never questioned), and a
  domain nothing like any of them is never second-guessed — an ordinary
  corporate or `.gov.in` address passes untouched.
- **The refusal is actionable, not a dead end.** A rejected value comes back
  through `missing_fields` as a question naming *both* spellings — `a
  confirmed Email — did you mean "Nithya@gmail.com" rather than
  "Nithya@gmaill.com"?` — via a new optional `hint(value)` callable on a
  field's catalog spec (fields without one keep the generic wording).
  `ASSISTANT_INSTRUCTIONS` tells the model to put that exact question to the
  citizen keeping both spellings intact, and *never* to substitute the
  suggestion itself — only the citizen can say which is right.
  `_tool_confirm_identity` additionally refuses to pass an unvalidated
  address to the identity resolver, so the typo never reaches the profile
  while the correction is pending.
- **"Confirm or correct" means both — and each has to mean the right thing.**
  The question is *'you sent "x@gmaill.com"; did you mean "x@gmail.com"?'*, so
  **"yes" takes the suggestion**; reading it as "keep what I typed" would
  re-introduce the exact typo on the single most likely reply. Standing by the
  original therefore means sending it again, which the wording explicitly
  invites — that path matters because the domain list is a heuristic and a
  real, unusual address must never be re-asked forever. The queried value is
  held in `state["queried_intake"]` and cleared as soon as it's settled; the
  affirmation check is deliberately narrow and only consulted on a *short*
  message, since words like "right" and "same" are everywhere in ordinary
  complaint prose ("the transformer on the right side"). A bare resend by the
  model never counts — it's told to resend every value it knows on every call,
  so only the citizen's own words decide.
- **The correction turn routes home too.** Because the question invites a
  reply shaped like *"no, it's dharshini@gmail.com"* — or simply *"Yes"* —
  `looks_like_intake_answer` accepts a pure yes/no message outright, and
  forgives a leading negation/affirmation **when the message also carries a
  concrete value**. Otherwise the correction turn would spawn the very
  duplicate ticket this fix exists to prevent. On its own, a negation is still
  complaint content: "no water at 600042" is not an intake answer.
- **An address the model reports as the identity value is recorded too.** The
  `confirm_identity` schema lets the model state an email either as
  `identityValue` or via `providedFields`; only the latter used to reach the
  intake state, so an address refused on the `identityValue` path was
  validated, dropped, and never written anywhere — the citizen saw a bare "we
  still need: Email" with no indication what was wrong with the address they
  had just sent, and retyped the same typo indefinitely. Both routes now merge
  identically.
- **Partial intake is no longer lost.** The Service/Customer ID used to be
  written onto the ticket *only* at complaint-creation time, so a citizen
  stuck on one bad field left an intake reply whose other, perfectly good
  answers were visible nowhere — and gone entirely if conversation state
  expired before they replied again. `update_ticket_identity` now takes
  `extra_fields`, and `_ticket_fields_from_intake` stamps validated,
  citizen-written values onto the stub on the turn they're given (name and
  email are identity attributes and continue to reach the database through
  the resolver). No schema change — db-writer's ticket PATCH already
  accepted `serviceId`.
- **Known limits, stated plainly.** (a) The bare-name rule is the loosest
  part of `looks_like_intake_answer` and does misread a terse noun-phrase
  complaint ("stray dogs") as a name; the utility/service nouns citizens
  actually use that way are listed as statement words, but that list can never
  be complete. The trade is deliberate and one-sided — a false positive
  appends to a stub whose intake is unfinished (both messages stay in one
  conversation, and an agent can split them), while a false negative *is* the
  reported bug. (b) The self-heal for already-split threads needs exactly one
  of the open tickets to still be in intake; if a split left two categoryless
  stubs, the older ">1 open, don't guess" rule applies and an agent merges by
  hand. (c) The confirm/correct round-trip lives in the assistant path only —
  the rule-based fallback keeps no cross-turn intake state at all, so with no
  `OPENAI_API_KEY` configured a flagged-but-real domain is re-asked each turn.
- **Operational note:** `ASSISTANT_INSTRUCTIONS` changed, so run
  `python scripts/update_assistant.py` once (from `services/ai-core`) against
  the live `OPENAI_ASSISTANT_ID` for the intake-answer and email-correction
  guidance to take effect — see the Feature 17 note above for why.

**Cross-ticket duplicate detection, on every channel (Feature 22).** Features
17–20 all improved *WhatsApp* routing. Email was deliberately excluded
(`if channel != "email"`) on the grounds that it had a better signal — the
subject-line ticket number. That holds for *replies*; it does nothing for a
citizen who composes a **fresh** email about a complaint they already have
open, and every unthreaded email gets a per-message thread key (Feature 15),
so it was a new ticket by construction. Live-tested: `sasashok19@gmail.com`
sent two emails 13 seconds apart, both "water logging in my area", and got
TKT-00020 and TKT-00021 — on top of a stale TKT-00019 from that morning.
Traced against the real code: `find_by_email` was called **0 times** for
routing and `is_same_topic` was never reached.

Two things were wrong, and the second is the more interesting one:

- **Email never participated in dedup at all.** The identity branch is now
  channel-agnostic.
- **The count-based rules could only reason about ONE open ticket.** Feature
  17's "2+ open tickets → don't guess → new ticket" is a refusal to decide,
  and it is what let the second email through even after the first was
  correctly created: a stale unconfirmed stub was open alongside it, so the
  message never reached the topic check. This is also why Feature 20's fix
  didn't cover it.

`is_same_topic` (one boolean, one ticket) is replaced by
**`match_open_ticket`** (`app/classify/message_quality.py`): the citizen's
open complaints are presented as a numbered list and the model names which one
this message concerns. **One call regardless of how many tickets are open** —
per-ticket calls would cost N requests per message and then leave the caller
reconciling N verdicts, including the awkward case where two say "same".

The judgment is three-way, and the third value is the point:

| Verdict | Meaning | Action |
|---|---|---|
| `same` | same problem **and** same place | Route to that ticket |
| `different` | different problem, **or** same problem elsewhere | New standalone ticket |
| `unclear` | the message omits the detail that would settle it | New ticket, **flagged**, and the AI **asks** |

"Same place" is not decoration: *water logging in Madambakkam* vs *water
logging in Tambaram* are different complaints, and so are *water logging* vs
*no power* in the same locality. Verified against the live model (temp 0, 3
runs each) on those cases plus the reported transcript — all stable.

**`unclear` is what makes this safe.** A bare "water logging" arriving while
"water logging in Madambakkam" is open is genuinely ambiguous; merging would
be a guess. Instead the ticket is created and carries `suspectedDuplicateOf`,
the per-turn instructions hand the model the other complaint's own words so it
can ask a *specific* question ("…the water logging in Madambakkam you reported
(TKT-00042), or a different location?"), and the new `resolve_duplicate` tool
acts on the citizen's answer. Nothing merges until they say so, so being wrong
here costs one extra question rather than a swallowed complaint.

On a confirmed duplicate the citizen's message is appended to the **original**,
this ticket takes the duplicate treatment that has always existed
(`isDuplicate`/`parentTicketId`/closed), the citizen gets the existing
duplicate-aware ack ("we've added your message to your existing complaint"),
and a `ticket.duplicate_merged` entry is written to the **original's audit
trail** — otherwise a ticket silently grows an extra message with no record of
where it came from. That needed a new `POST /api/v1/db/tickets/{id}/events`
(db-writer): the trail was previously writable only from inside
`TicketService`, so no other service could say anything about a ticket except
by changing its status. No schema change — `ticket_events` already permits an
`ai` actor.

**Failure behaviour stays channel-specific by design.** An unavailable
judgment (no key, timeout, unparseable response) is a network condition, not a
decision, so each channel keeps its long-standing default: WhatsApp appends to
a sole open ticket (its thread key really is per-conversation), email creates a
new one (a fresh email has always been its own complaint). An LLM outage must
never start silently merging a citizen's separate emails.

**Admin-only Cancel (Feature 21).** `cancelled` is a terminal status meaning
"this was never real work" — a confirmed duplicate, a test row, a withdrawn
complaint — as distinct from `closed`, which means the work was done. Reporting
has to tell them apart, so `resolved_at` is deliberately left NULL (a cancelled
ticket is not a resolution, and counting it as one would inflate resolution
rate and skew MTTR) and the SLA query excludes cancelled outright — otherwise a
cancelled ticket with a past due date and no `resolved_at` would count as a
**breach forever**. Requires migration **V11** (SQLite can't alter a CHECK, so
the table is rebuilt exactly as V9 did). It is the one status action a lead
cannot perform (`ticket.status.to_cancelled` → admin only), it is available
from any non-terminal status rather than as a step in the lifecycle chain, it
always requires a ≥20-character note, and the dashboard offers it only when the
server says the role may do it (`canCancel`, decided in the gateway rather than
from a role string in the browser).

**Ticket CSV export (Feature 21).** `GET /api/v1/tickets/export.csv`, honouring
exactly the same filters as the queue so "export" always means "what I'm
looking at". The `ticket.export` permission (admin/lead) had existed in
`RbacPolicy` since Feature 11 with no endpoint behind it. Paged internally at
db-writer's own maximum (100/request) rather than one unbounded query — the
queue query LEFT JOINs the identity table, so memory and latency stay flat
regardless of tenant size — and capped at 50,000 rows, with the cap reported in
`X-Export-Truncated` rather than silently stopping short. Cells are RFC 4180
escaped **and** formula-injection neutralised: these columns hold text the
citizen controls (their name, a complaint resolution), and a value starting
`=`, `+`, `-` or `@` executes when the file is opened in Excel or Sheets.

**Duplicate "complaint registered" acknowledgement (also live-tested).**
Independently of the above, the SAME conversation surfaced a second bug:
citizens got two separate confirmation messages for one new ticket — the
assistant's own end-of-turn "closing acknowledgement" (`ASSISTANT_
INSTRUCTIONS`, `app/conversation/tools.py`) stated the ticket number/
"registered", and moments later the async `complaint.ready` pipeline
(`app/notifications/sender.send_ticket_ack`, triggered once
`create_ticket_from_complaint` actually creates the ticket) sent its own,
separate structured ack — the two were never meant to both announce the
same thing. Fixed by instructing the model to send a brief, generic
closing acknowledgement ("Thanks, we're on it") **without** stating a
ticket number or the word "registered"/"logged"/"created" — the
structured ack remains the single authoritative confirmation with the
real ticket number, sent once the ticket actually exists rather than
guessed at mid-conversation. **Operational note:** this is an
`ASSISTANT_INSTRUCTIONS` change, so it needs `scripts/update_assistant.py`
run once against the live `OPENAI_ASSISTANT_ID` to take effect (see the
Feature 17 status-inquiry note above for why).

---

## Configurable per-channel intake fields

**What it is.** Which identity/intake fields the assistant collects — Name,
Mobile Number, Email, Service/Customer ID, Area Pin Code — and whether each is
mandatory is **configurable per channel** by a tenant admin, replacing the old
hardcoded "only Name is mandatory, everything else best-effort" gate. Each
field carries two independent flags:

- `mandatory` — required before the ticket is fully confirmed.
- `mandatoryIfAnonymous` — still required even when the citizen has explicitly
  declared themselves anonymous (e.g. a Service/Customer ID needed to route
  the complaint from someone who won't give their name).

A ticket only becomes fully confirmed once every mandatory field for its
channel is satisfied.

**The field catalog** lives in `services/ai-core/app/conversation/intake_fields.py`
(`FIELD_CATALOG`) — each entry pairs a label with an extractor (parses the
value out of the citizen's reply by label) and a validator (10-digit mobile,
6-digit pin code, non-empty otherwise). A second copy of the same
(key, label) list exists in `IntakeFieldsResource.java` for the config UI and
PUT validation; **the two must be kept in sync by hand** — there's no shared
source of truth across the Java/Python boundary.

**Built-in defaults** (`DEFAULT_INTAKE_FIELDS`, used until a tenant configures
its own):

| Channel  | Name | Mobile | Email | Service/Customer ID | Pin Code |
|----------|------|--------|-------|---------------------|----------|
| Email    | mandatory | optional | *native* | mandatory-if-anonymous | optional |
| WhatsApp | mandatory | *native (verified)* | **mandatory** | mandatory-if-anonymous | — |

WhatsApp defaulting Email to **mandatory** is the concrete fix for the
cross-channel identity gap: a verified WhatsApp phone used to skip the
identity ask entirely, so the same citizen complaining via both WhatsApp and
email became two separate identities. Asking WhatsApp users for their email
lets the resolver merge them into one (`_resolve_phone()` honours the
provided `confirmedEmail`).

**Native fields.** A field already carried by the channel — the email address
on the email channel, the phone on a *verified* WhatsApp sender — is
auto-satisfied and never asked (`is_native_field`). The admin UI greys these
cells out.

**Field sourcing.** `extract_configured_fields` tags each value with a
`source`: `native` (from the channel), `known` (already on a returning
citizen's profile), `extracted` (parsed from this message), or `None` (absent).
The distinction matters — `missing_fields` treats `native`/`known` as already
satisfied, but only `native`/`extracted` values are trustworthy enough to feed
back into identity resolution, and only `extracted` values go into the
ticket's citizen-provided-details summary.

**Admin UI.** Administration → **Intake Fields**
(`apps/dashboard/src/components/admin/IntakeFieldsPanel.tsx`): a grid, rows =
the 5 catalog fields, columns = channels, each cell a select with **Not asked /
Optional / Mandatory / Mandatory even if anonymous** (mapping directly to a
field config's absence/presence and its two flags). Native cells are shown as
"Provided by channel" and disabled. Saving `PUT`s to
`/api/v1/tenant/intake-fields`; the backend rejects a channel with no mandatory
identity field (name/mobile/email) with a `422` shown inline.

**Custom fields (admin "Add field").** Admins can extend the catalog with
tenant-defined fields (label + free-text or numeric validation, optional exact
digit count) from the same screen — stored as `intakeFieldCatalog` in
`config_json` (max 10). ai-core merges them into the runtime catalog
(`catalog_for_tenant`, `app/conversation/intake_fields.py`), giving each a
generic label-anchored extractor and validator — so a new field cascades
automatically into the per-channel grid, the bot's intake form, reply
extraction/validation, the assistant's per-turn instructions, and the ticket's
citizen-provided summary. Removing a custom field also strips it from every
channel's configuration. Custom fields are a single source of truth in tenant
config — unlike the 5 built-ins, nothing needs to be kept in sync across the
Java/Python boundary.

---

## Configurable priority rubric & general settings

Two more admin-authored, per-tenant config surfaces, both stored as their own
key inside the tenant's free-form `config_json` (merge-one-key, so they never
clobber `categories`/`sla`/`intakeFields` or each other) and both gated on the
`admin.tenant.config` RBAC action.

**AI priority rubric (`priorityRubric`).** Priority scoring used to be a fixed
weighted rule engine. An admin can now write a **free-text rubric** describing
how priority should be assessed; when it's set *and* an OpenAI key is
configured, ai-core scores each new complaint by asking the LLM
(`app/priority/llm_scorer.py` → `chat.completions`, strict-JSON
`{score: 0-10, label: critical|high|medium|low}`) to apply that rubric.
Fallbacks are total and silent: no rubric, no key, or any LLM error/timeout →
the deterministic engine (`app/priority/engine.py`) scores it instead, so ticket
creation never breaks and behaviour is unchanged until an admin opts in. The
config screen (Administration → **Priority Rules**) is **pre-filled with the
`default` rubric served by the backend — a plain-English writeup of exactly what
the engine does today** (the six weighted factors + the 8/6/4 label
thresholds), so saving it as-is keeps current behaviour. Endpoint:
`GET|PUT /api/v1/tenant/priority-rubric` (`PriorityRubricResource`).

**General settings (`generalSettings`).** A small, growing bag of tenant knobs
that were previously process-wide env constants. Currently one field:
`maxFollowupQuestions` (integer 0–5, default 2) — how many clarifying questions
the conversation agent may ask before it must log the complaint. ai-core reads
it per turn (`_effective_max_followups`, `app/conversation/agent.py`) with the
`AI_MAX_FOLLOWUP_QUESTIONS` env value as fallback. Admin screen: Administration
→ **Settings**. Endpoint: `GET|PUT /api/v1/tenant/general-settings`
(`GeneralSettingsResource`).

*Not yet configurable (kept hardcoded deliberately, to avoid config that
nothing reads):* classifier category set/keywords, SLA due-date computation,
priority factor weights/severity maps, unconfirmed auto-close window, phone
default region, and identity timeouts. These are documented as candidates for a
future round rather than half-wired now — the two consistency gaps worth noting
are that the stored `categories`/`sla` keys are not yet consumed by the runtime,
and the "14 days" auto-close appears as two independent literals (a Java
constant and a Python string) that must be kept in agreement by hand.

---

## HTTP API reference

### api-gateway — `http://localhost:8080`

**Health**
- `GET /api/v1/health` — aggregate health
- `GET /api/v1/health/eventbus` — Valkey connectivity + stream catalogue

**Auth**
- `POST /api/v1/auth/login` / `refresh` / `logout` / `forgot-password` / `reset-password`
- `GET /api/v1/auth/_dev/expired-token` — dev helper, mints an expired token

**Agent & tenant admin** (admin-only)
- `POST|GET /api/v1/agents`, `PATCH|DELETE /api/v1/agents/{id}` — email is
  immutable (`PATCH` rejects it with `EMAIL_IMMUTABLE`); `PATCH` otherwise
  whitelists `name`/`role`/`isActive`
- `PATCH /api/v1/agents/{id}/password` — admin sets a new password directly
  (8+ chars, bcrypt-hashed; no reset-link email flow)
- `GET|PUT /api/v1/tenant/config`
- `GET|PUT /api/v1/tenant/intake-fields` — per-channel configurable
  identity/intake fields (`IntakeFieldsResource`). `GET` returns the current
  config (or built-in defaults) plus the field `catalog`; `PUT` validates and
  saves it under the `intakeFields` key inside the tenant's `config_json`
  (merging, not clobbering `categories`/`sla`). Rejects unknown channels/field
  keys, non-boolean flags, and any channel left without at least one mandatory
  identity field (name/mobile/email) with `422 INVALID_INTAKE_FIELDS`. See
  [Configurable per-channel intake fields](#configurable-per-channel-intake-fields).
- `PUT /api/v1/tenant/intake-fields/catalog` — replace the tenant's **custom
  field catalog** (`{customFields: [{key, label, validation: "text"|"digits",
  digits?}]}`, ≤10 fields, keys letters/digits ≤30 chars and distinct from
  built-ins; `422 INVALID_FIELD_CATALOG`). Stored under `intakeFieldCatalog`
  in `config_json`; removing a field also strips it from every channel's
  configured list. ai-core's `catalog_for_tenant()` gives each custom field a
  generic label-anchored extractor + text/digits validator, so an
  admin-added field cascades to the bot's intake form, extraction,
  validation, and the assistant's instructions with no code changes.
  `GET /api/v1/tenant/intake-fields` returns the merged catalog (entries
  flagged `builtin`) plus the raw `customFields` list.
- `GET|PUT /api/v1/tenant/priority-rubric` — the tenant's free-text AI priority
  rubric (`PriorityRubricResource`). `GET` returns `{rubric, default}` (the
  `default` is the plain-English writeup of the current scoring engine, so the
  admin screen is pre-filled with today's logic); `PUT {rubric}` validates a
  string ≤ 8000 chars (`422 INVALID_PRIORITY_RUBRIC`) and merges only the
  `priorityRubric` key (empty string clears it). See
  [Configurable priority rubric & general settings](#configurable-priority-rubric--general-settings).
- `GET|PUT /api/v1/tenant/general-settings` — tenant general settings
  (`GeneralSettingsResource`). `GET` returns `{settings, defaults}`; `PUT`
  validates `maxFollowupQuestions` as an integer in `[0,5]`
  (`422 INVALID_GENERAL_SETTINGS`) and merges only the `generalSettings` key.
  Also accepts an optional `newsFeedUrl` (http(s), ≤500 chars; blank clears)
  — the login page's RSS headline source, served without auth via
  `GET /api/v1/public/news-config` (`PublicNewsConfigResource`) so the
  dashboard's `/api/news` route can read it before its env/BBC-Tamil
  fallbacks.
  Both endpoints reuse the `admin.tenant.config` RBAC action and the
  merge-one-key pattern, so `categories`/`sla`/`intakeFields`/`priorityRubric`/
  `generalSettings` never clobber one another.

**Announcements** (UI_REVAMP_v2 Feature C; RBAC `announcements.view` = all
roles, `announcements.manage` = admin)
- `GET /api/v1/announcements?activeOnly=` — active = `is_active=1` AND not past
  `expires_at` (evaluated at read time). Any authenticated role.
- `POST /api/v1/announcements` `{title, body, expiresAt?}` /
  `PATCH /api/v1/announcements/{id}` `{title?, body?, isActive?, expiresAt?}` /
  `DELETE /api/v1/announcements/{id}` — admin only; title ≥3 / body ≥10 chars
  (`422 INVALID_ANNOUNCEMENT`). Stored per tenant (`AnnouncementsResource` →
  db-writer `/api/v1/db/announcements`, table from `V8__announcements.sql`).
- `GET /api/v1/public/announcements` — **no auth** (login-page ticker):
  `{id, title}` only, for the default tenant's active announcements
  (`PublicAnnouncementsResource`; lives under the `/api/v1/public/` exclusion,
  like the citizen status lookup).

**Admin system operations** (UI_REVAMP_v2 Feature D; RBAC `admin.system.reset`)
- `POST /api/v1/admin/reset` `{password, confirmation:"RESET"}` — wipes ALL
  tenant data (tickets/messages/notes/events, identities, pending queue,
  announcements, non-admin agents) keeping the tenants row and the calling
  admin. Layered safeguards: JWT (`/api/v1/admin` in `AuthFilter`), admin role,
  bcrypt re-verification of the admin's CURRENT password (401
  `INVALID_PASSWORD`), literal `RESET` confirmation (400
  `CONFIRMATION_REQUIRED`, re-checked in db-writer), and a 60s per-tenant rate
  limit (429 `RATE_LIMITED`). A `tenant.reset` audit event with per-table
  delete counts is written inside the same transaction (after the deletes, so
  it survives the `ticket_events` wipe — the WARN log line fires before);
  db-writer's ticket cache is flushed. `SystemAdminResource` → db-writer
  `POST /api/v1/db/admin/reset`.

**Analytics** (any role may view; `agentId`/customer filters beyond one's
own tickets and `/agents` performance are lead/admin only via
`analytics.view.all`)
- `GET /api/v1/analytics/volume|sla|priority|agents` — `?period=` (e.g.
  `30d`, default 30), `?agentId=`, `?identityId=`, `?category=`,
  `?priorityLabel=`
- `GET /api/v1/analytics/agents-directory` — lead/admin only; `{id, name}`
  list for the "by agent" filter dropdown
- `GET /api/v1/analytics/customers?q=` — typeahead search (name/email/phone)
  for the "by customer" filter

**Tickets** (RBAC-scoped: agents see their own, lead/admin see all)
- `GET /api/v1/tickets` (`?identityStatus=confirmed` for the main queue,
  `?identityStatus=pending,anonymous` for the Unconfirmed queue). Also accepts
  `?page=` (1-based), `?pageSize=` (default 30, max 100), `?sortBy=` (one of
  `ticketNumber`/`createdAt`/`status`/`category`/`priorityScore`/`priorityLabel`/
  `channel`/`identityStatus`/`citizenName`/`citizenEmail`/`citizenPhone`) and
  `?sortDir=asc|desc` (default `createdAt` `desc` — newest first). Each row is
  enriched with `citizen_name`/`citizen_email`/`citizen_phone` (db-writer LEFT
  JOINs `identity_profiles`), and the response carries the **full matching
  `total`** (not just the page size) for pagination.
  `GET /api/v1/tickets/{id}` (detail includes the full message timeline and
  internal notes)
- `GET /api/v1/tickets/{id}/events` — the ticket's **audit trail** (creation,
  assignments, status transitions) with actor/assignee agent ids resolved to
  display names; backed by the `ticket_events` table. Assignments are audited
  via a `ticket.assigned`/`ticket.unassigned` event recorded by db-writer
  whenever `assignedTo` changes (the gateway's assign endpoint passes
  `actorAgentId` so the trail shows who did it).
- `POST /api/v1/tickets/{id}/transition` — on transition to `resolved` or
  `closed`, also sends the citizen a structured status-update email (see
  [Citizen-facing notifications](#citizen-facing-notifications))
- `PATCH /api/v1/tickets/{id}/assign` — lead/admin only
  (`ticket.assignee.edit`); body `{assignedTo}` (agent id, or
  null/omitted to unassign)
- `GET/POST /api/v1/tickets/{id}/notes` — internal, agent-facing annotations
- `POST /api/v1/tickets/{id}/reply` — send an update to the citizen; records
  an outbound message and, for email-origin tickets, actually sends it
- `POST /api/v1/tickets/{id}/generate-resolution-summary`
- `POST /api/v1/tickets/archive-stale` — admin-only
  (`admin.tickets.archive-stale`); soft-deletes unconfirmed tickets older
  than `olderThanDays` (default 60)

**Public citizen portal**
- `GET /api/v1/public/status/{ref}` — no auth; `ref` is a `TKT-XXXXX` ticket number, an `ANON-XXXX` ref, or an email

**Channel webhooks**
- `POST /api/v1/webhooks/whatsapp` (HMAC-validated), `GET /api/v1/webhooks/whatsapp` (Meta handshake)

**Internal / dev / adapter test endpoints**
- `POST /api/v1/internal/adapters/email/poll` — manual IMAP poll
- `POST /api/v1/internal/adapters/email/test-send` — send a test outbound email;
  `{sent:true}` on success, `502 {sent:false, error:<real message>}` on a
  provider failure (e.g. Resend's sandbox recipient restriction — see
  [docs/02a_ADAPTER_EMAIL.md](docs/02a_ADAPTER_EMAIL.md))
- `POST /api/v1/internal/adapters/whatsapp/send` — send an outbound WhatsApp
  message via Meta Graph API (called by ai-core's `sender.py`)
- `GET /api/v1/internal/events/latest?stream=` — inspect the last published event on a stream
- `POST /api/v1/internal/validate-event` — validate a payload against the adapter contract
- `POST /api/v1/internal/notifications/test`
- `GET /api/v1/adapters/twitter/status` — Phase-2 stub, 503 `PHASE_2_FEATURE`

### db-writer — `http://localhost:8090`

**Health / schema / backup**
- `GET /api/v1/health`, `GET /api/v1/internal/schema/version`, `GET /api/v1/internal/schema/tables`, `GET /api/v1/internal/backup/status`

**Analytics**
- `GET /api/v1/db/analytics/volume|sla|priority|agents` — tenant + rolling
  `period` window, plus optional `agentId`/`identityId`/`category`/
  `priorityLabel` filters; excludes archived tickets. `/agents` is the
  resolved-count + avg-resolution-hours-per-agent query.

**Tickets**
- `POST /api/v1/db/tickets`, `GET /api/v1/db/tickets` (filterable/paginated
  — `identityStatus`, `threadId`, `ticketNumber`, `originMessageId` (Feature
  19 — swipe-reply/In-Reply-To matching), `includeArchived`, etc.),
  `GET/PATCH /api/v1/db/tickets/{id}`
- `POST /api/v1/db/tickets/{id}/transition`
- `POST/GET /api/v1/db/tickets/{id}/notes`, `GET/POST /api/v1/db/tickets/{id}/messages`, `GET /api/v1/db/tickets/{id}/events`
- `POST /api/v1/db/tickets/{id}/generate-resolution-summary` — 503 in Phase 1 (no AI wired here yet)
- `POST /api/v1/db/tickets/archive-stale` — soft-delete (sets `archived_at`)
  unconfirmed tickets older than `olderThanDays` for one `tenantId`
- `POST /api/v1/db/tickets/auto-close-unconfirmed` — transitions
  `identityStatus=pending` tickets older than `olderThanDays` (default 14)
  to `status=closed`, across every tenant; returns the closed tickets so
  the caller can notify each citizen

**Identities**
- `POST /api/v1/db/identities`, `GET /api/v1/db/identities` (by
  email/phone, or `?q=` for a partial name/email/phone match — the
  analytics "by customer" typeahead)
- `GET /api/v1/db/identities/{id}` — looks up by primary key first, falling
  back to `masterId` (see the identity-id caveat below)
- `PATCH /api/v1/db/identities/{id}/merge`
- `GET /api/v1/db/identities/anon-check`
- `POST /api/v1/db/identities/pending`, `GET /api/v1/db/identities/pending/timed-out`

**Agents / tenants**
- `POST|GET /api/v1/db/agents`, `GET|PATCH /api/v1/db/agents/{id}`
- `GET /api/v1/db/tenants/{id}`, `PUT /api/v1/db/tenants/{id}/config`

### ai-core — `http://localhost:8001`

- `GET /api/v1/health`, `GET /q/health/live`, `GET /q/health/ready`
- `POST /api/v1/identity/resolve` — resolve a channel identity → master profile
- `POST /api/v1/internal/process-test-event` — dev-only: run the conversation agent on a synthetic event
- `POST /api/v1/internal/test-llm-health`
- `POST /api/v1/internal/pii/scrub`, `POST /api/v1/internal/pii/rehydrate`
- `POST /api/v1/internal/classify`
- `POST /api/v1/internal/deduplicate`
- `POST /api/v1/internal/priority/score`

### dashboard (BFF route handlers) — `http://localhost:3000`

Every route below is a thin proxy to the matching api-gateway endpoint via
`gatewayFetch` (`src/lib/gateway.ts`), forwarding the `access_token` cookie.

- `GET /api/health`
- `POST /api/auth/login`, `POST /api/auth/logout` (revokes the refresh token,
  clears the `access_token`/`role` cookies — used by the topbar Logout button)
- `GET/POST /api/agents`, `PATCH /api/agents/[id]`, `PATCH /api/agents/[id]/password`
- `GET/PUT /api/tenant/intake-fields` — proxies the intake-fields config for
  the Administration → Intake Fields admin UI
- `GET/PUT /api/tenant/priority-rubric` — proxies the AI priority-rubric config
  (Administration → Priority Rules)
- `GET/PUT /api/tenant/general-settings` — proxies tenant general settings
  (Administration → Settings)
- `GET /api/tickets` (forwards `?identityStatus=` for the Confirmed / Needs-identity
  queue toggle), `GET /api/tickets/[id]`, `GET /api/tickets/[id]/events` (the
  detail page's Audit trail section)
- `PUT /api/tenant/intake-fields/catalog` — add/remove custom intake fields
  (Administration → Intake Fields → "Add field")
- `POST /api/tickets/[id]/transition`, `PATCH /api/tickets/[id]/assign`,
  `GET/POST /api/tickets/[id]/notes`, `POST /api/tickets/[id]/reply`,
  `POST /api/tickets/[id]/generate-resolution-summary`
- `GET /api/analytics/volume|sla|priority|agents|agents-directory|customers`
- `GET/POST /api/announcements`, `PATCH/DELETE /api/announcements/[id]` —
  announcements (bell/banner + Administration → Announcements)
- `GET /api/public/announcements` — login-page ticker (public, no cookie)
- `POST /api/admin/reset` — the Administration → System danger-zone reset
- `GET /api/news` — **not** a gateway proxy: fetches + parses the configured
  RSS feed server-side (default BBC Tamil, `NEWS_RSS_URL` to change); returns
  `{articles: []}` on any failure so the login widget hides silently
- `GET /api/system/health` — **not** a gateway proxy: probes each service's
  health endpoint server-side for the Administration → System panel

---

## Environment variables

Each service ships `.env.example` (Docker-friendly defaults) and
`.env.local.example` (local no-Docker defaults) under its own directory —
copy to `.env`/`.env.local` and fill in real values. **Never commit either.**

### api-gateway (prefix `GATEWAY_*`)
`APP_ENV`, `TENANT_ID`, `LOG_LEVEL`, `GATEWAY_HTTP_PORT`/`QUARKUS_HTTP_PORT`,
`GATEWAY_VALKEY_URL`, `AI_CORE_URL`, `DB_WRITER_URL`,
`DB_WRITER_INTERNAL_API_KEY` (shared pod-to-pod secret — must match
db-writer's and ai-core's own copy), `GATEWAY_MAIL_FROM`, `DASHBOARD_ORIGIN`
(CORS allow-origin for the Vercel-hosted dashboard; comma-separate multiple
origins, defaults to `http://localhost:3000`).
`EMAIL_PROVIDER` (`smtp` default, or `resend` — Render's free tier blocks
outbound SMTP ports 25/465/587 entirely, so real Gmail SMTP send only works
locally or on a paid Render plan; `resend` sends over HTTPS instead),
`RESEND_API_KEY`, `RESEND_FROM_ADDRESS` (defaults to `onboarding@resend.dev`,
which needs no domain verification).
Email adapter: `EMAIL_SMTP_MOCK`, `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`,
`EMAIL_SMTP_USER`, `EMAIL_SMTP_PASSWORD`, `EMAIL_FROM_ADDRESS`,
`EMAIL_IMAP_HOST`, `EMAIL_IMAP_PORT`, `EMAIL_IMAP_MAILBOX`,
`EMAIL_IMAP_POLL_INTERVAL`, `EMAIL_IMAP_USER`, `EMAIL_IMAP_PASSWORD` (IMAP
user/password default to the SMTP credential if unset — one Gmail App
Password covers both directions).
WhatsApp adapter: `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`,
`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_API_VERSION`
(default `v21.0` — bump if Meta retires that version; `WHATSAPP_GRAPH_API_BASE_URL`
also exists but is a test-only seam, not meant to be set in `.env`).
Other: `DEV_SEED_ENABLED`, `JWT_SECRET`, `JWT_EXPIRY_ACCESS`, `JWT_EXPIRY_REFRESH`,
`TICKET_AUTO_CLOSE_INTERVAL` (default `1h` — how often the 14-day
unconfirmed-ticket auto-closer sweeps; see
[Queue separation & ticket lifecycle](#queue-separation--ticket-lifecycle)).

### db-writer (prefix `DB_WRITER_*`)
`APP_ENV`, `TENANT_ID`, `LOG_LEVEL`, `DB_WRITER_HTTP_PORT`/`QUARKUS_HTTP_PORT`,
`DB_WRITER_DB_PATH`, `DB_WRITER_INTERNAL_API_KEY` (empty = pod-to-pod auth
disabled, the local dev default), `BACKUP_DESTINATION`,
`BACKUP_INTERVAL_MINUTES`. (`DB_WRITER_CACHE_MAX_SIZE`/`_TTL_MINUTES` are
documented in the feature spec but not actually read — `TicketCache.java`
hardcodes max 1000 / 2-min TTL.)

### ai-core (prefix `AI_CORE_*`)
`APP_ENV`, `TENANT_ID`, `LOG_LEVEL`, `AI_CORE_PORT`, `VALKEY_URL`,
`EVENT_BUS_MAX_RETRIES`, `EVENT_BUS_RETRY_DELAY_MS`,
`EVENT_BUS_CONSUMER_GROUP`, `DB_WRITER_URL`, `DB_WRITER_INTERNAL_API_KEY`,
`API_GATEWAY_URL` (delivers `ai.reply.send` via api-gateway's email or
WhatsApp send endpoint, by channel),
`EMAIL_SEND_TIMEOUT_SECONDS` (default 30 — httpx timeout for that call; a
real SMTP/Resend send is slower than the old mock path),
`WHATSAPP_SEND_TIMEOUT_SECONDS` (default 15 — Graph API has no SMTP-style
handshake, so a shorter timeout than email's is enough),
`IDENTITY_MERGE_CONFIDENCE_THRESHOLD`, `IDENTITY_PENDING_TIMEOUT_HOURS`,
`IDENTITY_ANON_REF_PREFIX`, `DEFAULT_REGION`, `CONVERSATION_STATE_TTL_HOURS`,
`AI_MAX_FOLLOWUP_QUESTIONS`, `DEFAULT_LLM_PROVIDER`, `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `OPENAI_ASSISTANT_ID` (empty = rule-based fallback),
`OPENAI_MODEL`, `PII_SCRUBBER_ENABLED`.

### dashboard
`APP_ENV`, `NEXT_PUBLIC_TENANT_ID`, `NEXT_PUBLIC_API_GATEWAY_URL`
(browser-facing), `API_GATEWAY_INTERNAL_URL` (server-side/Docker-mode
container-name URL), `DB_WRITER_URL`, `AI_CORE_URL` (both default to
`http://localhost:8090`/`:8001` — used only by Administration → System's
service-health probe, which checks these two directly rather than through
the gateway proxy; set to db-writer's/ai-core's real deployed URLs in
production or that panel shows every service "Unreachable"),
`NEWS_RSS_URL` (optional — RSS 2.0 feed for the login
page's headlines widget; defaults to BBC Tamil, no API key; the widget hides
itself if the feed is unreachable). No NextAuth — auth is a custom cookie set
by `app/api/auth/login/route.ts`, which proxies straight to api-gateway.

---

## Logging, log levels & transaction tracing

**Log level.** Every service reads `LOG_LEVEL` from its environment
(default `INFO`):
- api-gateway / db-writer: `quarkus.log.level=${LOG_LEVEL:INFO}`
  (`services/*/src/main/resources/application.properties`).
- ai-core: `settings.log_level` → `logging.basicConfig(level=...)`
  (`app/main.py`).

`INFO` (the default everywhere) surfaces info/warning/error — i.e.
"log everything" Phase 1 emits. Set `LOG_LEVEL=ERROR` in production to
silence routine info/warning traffic and keep only failures.

**Common log (local dev).** `scripts/dev-local.sh` writes each service's own
log (`scripts/<service>.log`, unchanged) **and** tees every line, tagged
with its source, into `scripts/combined.log`:
```
tail -f scripts/combined.log
```
shows every service's activity interleaved in the order it actually
happened — no need to tail four separate files to watch one transaction
move through the system.

**Transaction tracing (`traceId`).** Every inbound message is assigned a
`traceId` (a UUID) the moment an adapter receives it
(`EmailAdapter.parseMessage` / `WhatsAppParser.parse` on api-gateway). That
same id is carried through every downstream event and logged at each stage:

1. **api-gateway** — adapter receipt → `ChannelMessagePublisher.publish` →
   `EventBusPublisher.publish` (three INFO log lines, same `traceId`).
2. **ai-core** — `dispatcher.py`'s consumer logs receipt, `ConversationAgent`
   logs the turn start/decisions, `IdentityResolver` logs the resolution
   outcome, and every event it publishes (`identity.resolved`,
   `complaint.ready`, `ai.reply.send`) carries the same `traceId` (via
   `build_event(..., trace_id=...)` — previously each downstream event
   minted its own fresh, disconnected id; this was fixed alongside adding
   the logging).
3. **db-writer** — `ai-core`'s `DbWriterClient` sends the id onward as an
   `X-Trace-Id` header on every call; db-writer's `RequestLoggingFilter`
   logs it on every `/api/v1/db/*` request/response.

So `grep <traceId> scripts/combined.log` (or the individual per-service
logs) reconstructs one transaction end-to-end across all three backend
services. Log levels used throughout: **INFO** for normal progress (message
received, event published, resolution outcome, request succeeded), **WARN**
for recoverable problems (validation failure, DLQ routing, a 4xx from
db-writer), **ERROR** for failures (exceptions, a 5xx from db-writer, a
failed event publish).

**Known gap:** direct, non-event-driven HTTP flows (dashboard login, the
public status lookup, agent/ticket CRUD) don't have a `traceId` to carry,
since they aren't part of an adapter-originated transaction — db-writer's
`RequestLoggingFilter` logs `traceId=null` for those, which is expected.

---

## Testing

- **api-gateway / db-writer** (Java): `cd services/<service> && mvn test`
  (JUnit 5 + `@QuarkusTest`).
- **ai-core** (Python): `cd services/ai-core && pytest tests/ -q` (inside
  the service's `.venv`).
- **dashboard**: no automated test suite yet in Phase 1; verified manually
  through the browser and via the BFF route handlers.

---

## Dashboard app

See [Services → dashboard](#services) above for the current route layout,
and [12_AGENT_DASHBOARD](docs/12_AGENT_DASHBOARD.md) for the full target
design (route groups, component library, charts) versus what's actually
built today.

---

## Feature docs index

One doc per feature under `docs/`, each with implementation notes tracking
where the actual code deviated from (or corrected) the original spec:

| Doc | Feature |
|---|---|
| [ORCHESTRATOR.md](docs/ORCHESTRATOR.md) | Master brief: vision, monorepo layout, tech stack, conventions, build order |
| [SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md) | Architecture reference, single-writer/SQLite rationale |
| [SCAFFOLD_STATUS.md](docs/SCAFFOLD_STATUS.md) | Living build-status log across every feature |
| [01_EVENT_BUS.md](docs/01_EVENT_BUS.md) | Valkey Streams backbone, publisher/consumer, retry+DLQ |
| [02a_ADAPTER_EMAIL.md](docs/02a_ADAPTER_EMAIL.md) | IMAP polling + SMTP outbound |
| [02b_ADAPTER_WHATSAPP.md](docs/02b_ADAPTER_WHATSAPP.md) | Meta Business webhook adapter |
| [02cde_ADAPTERS_PHASE2.md](docs/02cde_ADAPTERS_PHASE2.md) | Twitter/IVR/WebChat — Phase 2 stubs only |
| [02f_ADAPTER_CONTRACT.md](docs/02f_ADAPTER_CONTRACT.md) | Canonical event schema every adapter emits |
| [03_IDENTITY_RESOLVER.md](docs/03_IDENTITY_RESOLVER.md) | Identity resolution, merging, anonymous refs |
| [04_DB_WRITER_SERVICE.md](docs/04_DB_WRITER_SERVICE.md) | The sole SQLite-writing REST API |
| [05_TICKET_SCHEMA.md](docs/05_TICKET_SCHEMA.md) | Full DDL, dev seed data |
| [06_to_10_AI_PIPELINE.md](docs/06_to_10_AI_PIPELINE.md) | Conversation agent, PII scrub, classify, dedup, priority |
| [11_MULTI_TENANCY.md](docs/11_MULTI_TENANCY.md) | JWT auth, RBAC, tenant config |
| [12_AGENT_DASHBOARD.md](docs/12_AGENT_DASHBOARD.md) | Full dashboard spec (target vs. built) |
| [13_to_16_REMAINING.md](docs/13_to_16_REMAINING.md) | Analytics, notifications, Phase-2 encryption design, deployment |

---

## Phase roadmap

**Phase 1 (built):** Email + WhatsApp channels (both inbound *and* outbound
— Meta Graph API send); identity gate; basic PII scrubbing; classification;
priority scoring; SQLite WAL via db-writer; full agent dashboard
(functional-minimal UI); outbound email + WhatsApp notifications; dev mock
seed data; JWT auth + RBAC; transaction tracing & log-level control (this
doc's [Logging](#logging-log-levels--transaction-tracing) section);
cross-channel ticket threading/dedup (subject-line or explicit-reference
matching, open-status-gated thread reuse, identity+open-count fallback for
subject-less channels, content-level same-topic disambiguation) and a
"status of my complaint" summary, both channel-agnostic (see
[Subject-line ticket threading & dedup](#subject-line-ticket-threading--dedup));
message-quality gating — coherence check (email hard-rejects with no
ticket, WhatsApp asks for confirmation) and same-topic disambiguation, both
LLM-driven and best-effort (see "Message quality" in the same section).

**Not yet wired despite existing code:** the rule-based (no-LLM) identity
gate recognises "anonymous" or a labeled reply to its structured intake
question (Service/Customer ID, Mobile, Name, Area Pin Code — see
[Services → ai-core](#services)), but nothing beyond that single-message
label matching — no real NLU, so e.g. an unlabeled value gets missed (the
OpenAI Assistants path handles free text correctly via tool-calling); IMAP
IDLE (real-time push) — polling only; WhatsApp pre-approved template
messages — outbound WhatsApp only supports free-form text, which Meta
restricts to within 24h of the citizen's last inbound message (see
[docs/02b_ADAPTER_WHATSAPP.md](docs/02b_ADAPTER_WHATSAPP.md)); a send
attempted outside that window simply fails; an interactive "which of your
open complaints is this?" disambiguation flow for the 2+-open-tickets case
(see the Feature 17 note above) — today it just creates a new ticket,
which an agent can merge manually via the dashboard if needed; documented,
deliberately deferred, not a silent gap.

**Phase 2 (planned, not built):** Twitter/IVR/WebChat channels; field-level
AES-256-GCM encryption for PII columns (`PiiEncryptionService`, KMS/Vault key
management, key rotation); SMS/webhook notifications; blind-index PII
search; enforced no-PII logging; JSON-structured log output in production
(`quarkus.log.console.json` is currently disabled in dev profile for
readability).

---

## Security notes

- JWT (HS256), 15-min access / 7-day rotating refresh tokens
  ([11_MULTI_TENANCY](docs/11_MULTI_TENANCY.md)).
- Three roles: `admin`, `lead`, `agent` — RBAC enforced in api-gateway.
  **Gotcha**: `AuthFilter.isProtected(path)` hardcodes the path prefixes it
  populates `CurrentUser` for (`/api/v1/agents`, `/api/v1/tenant`,
  `/api/v1/tickets`, `/api/v1/analytics`) — a new RBAC-protected resource
  under a path not in that list silently gets an unpopulated `CurrentUser`
  (NPEs on `tenantId()`, and every `RbacPolicy.can(...)` check fails closed
  as if unauthenticated). Add the new prefix to `isProtected()` when adding
  a resource — this bit us once already when `/api/v1/analytics` was added.
- Pod-to-pod auth between api-gateway/ai-core → db-writer via a shared
  `X-Internal-Key` (`DB_WRITER_INTERNAL_API_KEY`), a no-op when unset (local
  dev default; Docker mode currently leaves it unset too — not yet enforced
  there).
- WhatsApp webhook signature validation (HMAC-SHA256 over the raw body); a
  fixed dev-only bypass token (`sha256=test_bypass_in_dev`) works only when
  `APP_ENV=development`.
- PII fields (`name`, `email`, `phone`, ticket `content`/`resolution`) are
  marked `PHASE_2_ENCRYPT` in the schema — encrypted at rest only from
  Phase 2 onward; Phase 1 stores them in plaintext SQLite columns.
- Never commit `.env`/`.env.local` files (gitignored); only `.env.example`/
  `.env.local.example` templates are tracked.
