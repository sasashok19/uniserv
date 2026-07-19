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
  [Subject-line ticket threading & dedup](#subject-line-ticket-threading--dedup));
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
  complaint, not the intake reply. The OpenAI Assistants path gets a
  best-effort hint about the mandatory fields injected into its per-turn
  instructions, but cannot enforce the config as strictly as the rule-based
  path (its system prompt isn't regenerated per tenant — a known limitation).
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
  (identity requests, follow-ups) via api-gateway's email send endpoint.
  This event used to be published with nothing consuming it — the citizen
  never received the identity-request email, so no reply was possible and no
  ticket could ever form. WhatsApp-origin replies are recorded as
  undeliverable (no outbound WhatsApp send in this codebase — Phase 2). The
  identity-request message also tells the citizen their ticket will be
  auto-closed after 14 days without a reply (see
  [Queue separation & ticket lifecycle](#queue-separation--ticket-lifecycle)
  below). The same module's `send_ticket_ack_email` sends a structured
  acknowledgment — carrying the ticket ID/number, category, and status — as
  soon as a ticket is created or a message is appended to an existing one
  (called from `dispatcher.py`'s `complaint.ready` handler, right after
  `create_ticket_from_complaint` succeeds).
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
- `src/app/login/page.tsx` — agent login.
- `src/app/dashboard/page.tsx` — role-gated agent dashboard (Analytics /
  Ticket Queue / Administration). Ticket Queue rows link to the detail page
  below; nav tabs and status/priority/identity badges use a shared colour
  palette (`src/lib/badges.ts`). The Ticket Queue shows admins and leads a
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
  0–5); saves to `PUT /api/v1/tenant/general-settings`. Both new panels are
  described in
  [Configurable priority rubric & general settings](#configurable-priority-rubric--general-settings).
- `src/app/dashboard/tickets/[id]/page.tsx` — ticket detail, reflowed into a
  2-column layout: the left (main) column has citizen details
  (Name/Email/Phone/Service-Customer-ID — read-only, sourced from the
  ticket's identity + a `tickets.service_id` column), the status-transition
  control, **Internal Notes**, and **Write an update**, in that order; the
  right column is the conversation timeline in its own
  `max-h-[80vh] overflow-y-auto` scroll region — so the tools an agent acts
  on are visible without scrolling past the full message history first.
  Service/Customer ID is populated by ai-core going forward
  (`create_ticket_from_complaint`); tickets from before that column existed
  fall back to a regex parse of the first message's text
  (`TicketsResource.detail()`). Sending an update on an email-origin ticket
  calls `POST /api/v1/tickets/{id}/reply`, which records the outbound
  message and actually emails the citizen via `EmailAdapter.sendReply`
  (WhatsApp-origin tickets record the message but have no outbound send
  wired yet — Phase 2). "Assigned to" is an editable select (lead/admin
  only, `PATCH /api/v1/tickets/{id}/assign`) resolved to the agent's name
  via `TicketsResource.agentDirectory()`; agents see the name read-only.
  The Ticket Queue table shows the same resolved name in its own
  "Assigned to" column.
- `src/app/status/[ref]/page.tsx` — public, unauthenticated, server-rendered
  citizen status lookup by `ANON-XXXX` ref or email; calls api-gateway's
  `GET /api/v1/public/status/{ref}` server-side.
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
| `tickets` | `id`, `tenant_id`, `ticket_number` (e.g. `TKT-00142`), `identity_id`, `identity_status` (pending\|anonymous\|confirmed), `assigned_to`, `status` (open\|assigned\|in_progress\|resolved\|closed\|reopened), `category`/`subcategory`, `priority_score` (0–10), `priority_label`, `sentiment_score`, `channel_origin`, `thread_id`, `archived_at`, `is_duplicate`, `parent_ticket_id`, `service_id`, `sla_due_at` |
| `ticket_messages` | `channel`, `direction`, `author_type` (ai\|agent\|user\|system), `content`, `media_urls_json`, `is_ai_generated` |
| `ticket_notes` | `content`, `is_mandatory`, `transition_from`/`transition_to` |
| `ticket_events` | `event_type`, `actor_type`, `actor_id`, `meta_json` (full audit trail) |
| `identity_pending_queue` | `thread_id`, `channel`, `channel_identity_value`, `raw_message`, `timeout_at` (default 48h) |

**Ticket status flow:** `Open → Assigned → In-Progress → Resolved → Closed`,
with `Closed → Reopened → In-Progress`. Mandatory ≥20-character notes are
enforced (application layer) on In-Progress→Resolved, Resolved→Closed, and
Closed→Reopened.

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

Every citizen-facing email is structured (ticket ID/number, category,
status) and delivered through api-gateway's `EmailAdapter.sendReply` —
WhatsApp has no outbound send yet (Phase 2), so these are logged as
"not delivered" rather than sent for that channel.

- **Identity request.** Sent when the identity gate can't resolve who's
  writing in; now explicitly states the request will be auto-closed after
  14 days without a reply (`IDENTITY_REQUEST_MESSAGE`,
  `app/conversation/agent.py`).
- **Ticket acknowledgment.** Sent once a ticket is created *or* a message
  is appended to an existing one — carries the ticket ID/number, category,
  and status (`send_ticket_ack_email`, `app/notifications/sender.py`,
  called from `dispatcher.py`'s `complaint.ready` handler). Best-effort: a
  failed send never rolls back the ticket write.
- **Status update on resolve/close.** Sent only when a ticket transitions
  *to* `resolved` or `closed` — not on other transitions, and not for a
  standalone "add note" action — including the mandatory transition note's
  content (`TicketNotifier.sendStatusUpdateEmail`, api-gateway, shared by
  `TicketsResource`'s manual transition endpoint and
  `TicketAutoCloseScheduler`'s automatic 14-day close).

All three require an email address on file (either the ticket's
`channel_origin=email` with a resolved `identity_id`, or — for the
identity-request message — the raw address the citizen wrote in from) and
silently no-op otherwise (e.g. a WhatsApp-origin ticket, or a ticket that
never got far enough to have an identity record at all). Every subject
that carries a ticket number also gets `[Ticket TKT-XXXXX]` appended, and
the body a "please don't remove the ticket number from the subject" note
(`DO_NOT_REMOVE_NOTE`, `app/notifications/sender.py`) — see below for why
that matters.

## Subject-line ticket threading & dedup

**The bug:** a citizen who emailed in a genuinely new, unrelated complaint
could see it silently appended as a note onto an old *different* open
ticket, just because it classified into the same category as that other
ticket. The previous dedup (`app/dedup/service.py`'s `check_duplicate`)
matched on identity + category + open-status alone — too coarse a signal
once a citizen has more than one thing going on with the same category.

**The fix:** every outbound email's subject now carries the ticket number
(`[Ticket TKT-00042]`), and an inbound email's subject is checked for that
same reference before anything else (`extract_ticket_number`,
`app/tickets/intake.py`) — a citizen's reply always preserves the subject
line (as "Re: ..."), so this is a precise, citizen-visible signal rather
than an inferred one. `ensure_ticket_stub` resolves in this order:

1. Subject references a real ticket number → that exact ticket, regardless of thread/category.
2. Otherwise, the existing thread (`threadId`, via In-Reply-To/References headers).
3. Otherwise, a brand-new stub ticket — this is what a genuinely new complaint gets.

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
  Both endpoints reuse the `admin.tenant.config` RBAC action and the
  merge-one-key pattern, so `categories`/`sla`/`intakeFields`/`priorityRubric`/
  `generalSettings` never clobber one another.

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
- `GET /api/v1/public/status/{ref}` — no auth; `ref` is an `ANON-XXXX` ref or an email

**Channel webhooks**
- `POST /api/v1/webhooks/whatsapp` (HMAC-validated), `GET /api/v1/webhooks/whatsapp` (Meta handshake)

**Internal / dev / adapter test endpoints**
- `POST /api/v1/internal/adapters/email/poll` — manual IMAP poll
- `POST /api/v1/internal/adapters/email/test-send` — send a test outbound email
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
  — `identityStatus`, `threadId`, `ticketNumber`, `includeArchived`, etc.),
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
- `POST /api/auth/login`
- `GET/POST /api/agents`, `PATCH /api/agents/[id]`, `PATCH /api/agents/[id]/password`
- `GET/PUT /api/tenant/intake-fields` — proxies the intake-fields config for
  the Administration → Intake Fields admin UI
- `GET/PUT /api/tenant/priority-rubric` — proxies the AI priority-rubric config
  (Administration → Priority Rules)
- `GET/PUT /api/tenant/general-settings` — proxies tenant general settings
  (Administration → Settings)
- `GET /api/tickets` (forwards `?identityStatus=` for the Confirmed / Needs-identity
  queue toggle), `GET /api/tickets/[id]`
- `POST /api/tickets/[id]/transition`, `PATCH /api/tickets/[id]/assign`,
  `GET/POST /api/tickets/[id]/notes`, `POST /api/tickets/[id]/reply`,
  `POST /api/tickets/[id]/generate-resolution-summary`
- `GET /api/analytics/volume|sla|priority|agents|agents-directory|customers`

---

## Environment variables

Each service ships `.env.example` (Docker-friendly defaults) and
`.env.local.example` (local no-Docker defaults) under its own directory —
copy to `.env`/`.env.local` and fill in real values. **Never commit either.**

### api-gateway (prefix `GATEWAY_*`)
`APP_ENV`, `TENANT_ID`, `LOG_LEVEL`, `GATEWAY_HTTP_PORT`/`QUARKUS_HTTP_PORT`,
`GATEWAY_VALKEY_URL`, `AI_CORE_URL`, `DB_WRITER_URL`,
`DB_WRITER_INTERNAL_API_KEY` (shared pod-to-pod secret — must match
db-writer's and ai-core's own copy), `GATEWAY_MAIL_FROM`.
Email adapter: `EMAIL_SMTP_MOCK`, `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`,
`EMAIL_SMTP_USER`, `EMAIL_SMTP_PASSWORD`, `EMAIL_FROM_ADDRESS`,
`EMAIL_IMAP_HOST`, `EMAIL_IMAP_PORT`, `EMAIL_IMAP_MAILBOX`,
`EMAIL_IMAP_POLL_INTERVAL`, `EMAIL_IMAP_USER`, `EMAIL_IMAP_PASSWORD` (IMAP
user/password default to the SMTP credential if unset — one Gmail App
Password covers both directions).
WhatsApp adapter: `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`,
`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`.
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
`API_GATEWAY_URL` (delivers `ai.reply.send` via api-gateway's email endpoint),
`IDENTITY_MERGE_CONFIDENCE_THRESHOLD`, `IDENTITY_PENDING_TIMEOUT_HOURS`,
`IDENTITY_ANON_REF_PREFIX`, `DEFAULT_REGION`, `CONVERSATION_STATE_TTL_HOURS`,
`AI_MAX_FOLLOWUP_QUESTIONS`, `DEFAULT_LLM_PROVIDER`, `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `OPENAI_ASSISTANT_ID` (empty = rule-based fallback),
`OPENAI_MODEL`, `PII_SCRUBBER_ENABLED`.

### dashboard
`APP_ENV`, `NEXT_PUBLIC_TENANT_ID`, `NEXT_PUBLIC_API_GATEWAY_URL`
(browser-facing), `API_GATEWAY_INTERNAL_URL` (server-side/Docker-mode
container-name URL). No NextAuth — auth is a custom cookie set by
`app/api/auth/login/route.ts`, which proxies straight to api-gateway.

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

**Phase 1 (built):** Email + WhatsApp channels; identity gate; basic PII
scrubbing; classification; priority scoring; SQLite WAL via db-writer; full
agent dashboard (functional-minimal UI); outbound email notifications;
dev mock seed data; JWT auth + RBAC; transaction tracing & log-level
control (this doc's [Logging](#logging-log-levels--transaction-tracing) section).

**Not yet wired despite existing code:** the rule-based (no-LLM) identity
gate recognises "anonymous" or a labeled reply to its structured intake
question (Service/Customer ID, Mobile, Name, Area Pin Code — see
[Services → ai-core](#services)), but nothing beyond that single-message
label matching — no real NLU, so e.g. an unlabeled value gets missed (the
OpenAI Assistants path handles free text correctly via tool-calling); IMAP
IDLE (real-time push) — polling only; outbound WhatsApp send (Meta Business
API) — `ai.reply.send` is delivered for email only, WhatsApp replies are
recorded as undeliverable.

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
