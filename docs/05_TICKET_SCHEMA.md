# Feature 05 — Ticket Schema

## Phase Scope
- **Phase 1:** Plain text PII fields with PHASE_2_ENCRYPT markers
- **Phase 2:** Add PiiFieldConverter to marked columns, add blind index columns

## What This Module Does
Defines the complete SQLite schema. Single source of truth for all data.
Managed via Flyway migrations inside the db-writer service.

---

## SQLite WAL Configuration

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;
```

Connection string:
```
jdbc:sqlite:/data/uniserve.db?journal_mode=WAL&foreign_keys=on
```

---

## Schema

### tenants
```sql
CREATE TABLE tenants (
  id             TEXT PRIMARY KEY,           -- UUID
  name           TEXT NOT NULL,
  slug           TEXT UNIQUE NOT NULL,
  deployment_mode TEXT DEFAULT 'cloud',      -- 'cloud' | 'onprem'
  llm_provider   TEXT DEFAULT 'anthropic',
  config_json    TEXT DEFAULT '{}',          -- JSON: categories, SLA, channels
  created_at     TEXT DEFAULT (datetime('now'))
);
```

### agents
```sql
CREATE TABLE agents (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenants(id),
  name           TEXT NOT NULL,
  -- PHASE_2_ENCRYPT: name
  email          TEXT NOT NULL,
  -- PHASE_2_ENCRYPT: email
  -- PHASE_2: ADD email_idx TEXT (blind index)
  password_hash  TEXT NOT NULL,
  role           TEXT NOT NULL CHECK(role IN ('admin','lead','agent')),
  is_active      INTEGER DEFAULT 1,
  created_at     TEXT DEFAULT (datetime('now')),
  UNIQUE(tenant_id, email)
);
CREATE INDEX idx_agents_tenant ON agents(tenant_id);
```

### identity_profiles
```sql
CREATE TABLE identity_profiles (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenants(id),
  master_id      TEXT UNIQUE NOT NULL,
  name           TEXT,
  -- PHASE_2_ENCRYPT: name
  email          TEXT,
  -- PHASE_2_ENCRYPT: email
  -- PHASE_2: ADD email_idx TEXT (HMAC blind index for matching)
  phone          TEXT,
  -- PHASE_2_ENCRYPT: phone
  -- PHASE_2: ADD phone_idx TEXT (HMAC blind index for matching)
  channel_ids_json TEXT DEFAULT '[]',        -- JSON: [{channel, value, verified}]
  is_anonymous   INTEGER DEFAULT 0,
  anon_ref_id    TEXT UNIQUE,               -- e.g. "ANON-7X3K"
  merged_into    TEXT,                       -- master_id of profile merged into
  created_at     TEXT DEFAULT (datetime('now')),
  updated_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_identity_tenant ON identity_profiles(tenant_id);
CREATE INDEX idx_identity_email  ON identity_profiles(tenant_id, email);
CREATE INDEX idx_identity_phone  ON identity_profiles(tenant_id, phone);
-- PHASE_2: CREATE INDEX idx_identity_email_idx ON identity_profiles(tenant_id, email_idx);
-- PHASE_2: CREATE INDEX idx_identity_phone_idx ON identity_profiles(tenant_id, phone_idx);
```

### tickets
```sql
CREATE TABLE tickets (
  id               TEXT PRIMARY KEY,
  tenant_id        TEXT NOT NULL REFERENCES tenants(id),
  ticket_number    TEXT NOT NULL,            -- e.g. "TKT-00142"
  identity_id      TEXT REFERENCES identity_profiles(id),
  identity_status  TEXT DEFAULT 'pending'
                   CHECK(identity_status IN
                     ('pending','confirmed','anonymous','timeout')),
  identity_source  TEXT,
                   -- 'channel' | 'user_provided' | 'anonymous_declared'
  assigned_to      TEXT REFERENCES agents(id),
  status           TEXT DEFAULT 'open'
                   CHECK(status IN
                     ('open','assigned','in_progress',
                      'resolved','closed','reopened')),
  category         TEXT,
  subcategory      TEXT,
  priority_score   REAL,                     -- 0.00–10.00
  priority_label   TEXT
                   CHECK(priority_label IN
                     ('critical','high','medium','low')),
  sentiment_score  REAL,                     -- -1.0 to 1.0
  channel_origin   TEXT NOT NULL,
  is_duplicate     INTEGER DEFAULT 0,
  parent_ticket_id TEXT REFERENCES tickets(id),
  resolution       TEXT,
                   -- populated by AI summary before close
                   -- PHASE_2_ENCRYPT: resolution
  sla_due_at       TEXT,
  resolved_at      TEXT,
  closed_at        TEXT,
  reopened_count   INTEGER DEFAULT 0,
  reopened_by      TEXT REFERENCES agents(id),
  created_at       TEXT DEFAULT (datetime('now')),
  updated_at       TEXT DEFAULT (datetime('now')),
  UNIQUE(tenant_id, ticket_number)
);
CREATE INDEX idx_tickets_tenant_status   ON tickets(tenant_id, status);
CREATE INDEX idx_tickets_tenant_priority ON tickets(tenant_id, priority_score DESC);
CREATE INDEX idx_tickets_assigned        ON tickets(assigned_to);
CREATE INDEX idx_tickets_created         ON tickets(tenant_id, created_at DESC);
```

Columns added by later migrations (V5–V12), all nullable so no backfill is
required:

| Column | Migration | Purpose |
| --- | --- | --- |
| `thread_id` | V5 | Conversation thread key — the DB-side thread→ticket lookup (Valkey state expires in ~2h, an unconfirmed thread can sit for days) |
| `archived_at` | V5 | Soft delete; non-null hides the ticket from every queue, never physically removed |
| `service_id` | V6 | Service/Customer ID promoted out of the first message's free text |
| `origin_message_id` | V7 | The originating inbound email's `Message-ID` / WhatsApp `wamid`, reused for reply threading and for resolving a swipe-reply to its ticket |
| `chief_complaint` | V12 | **Feature 23** — the citizen's complaint in one line (≤140 chars), derived by ai-core from the message that opened the ticket and re-derived as they reply. See "Chief complaint" below |

### `chief_complaint` (Feature 23)

The one-line answer to "what is this ticket about". Before it existed the only
place that answer lived was the free text of the ticket's first inbound
message, so neither the queue nor the ticket header could show it — an agent
triaging saw status, priority, category and channel, every attribute *about* a
complaint and nothing *of* it.

Written only by ai-core (`app/tickets/chief_complaint.py`), never by an agent:

- **Derived, not copied.** An LLM one-liner from the citizen's own text, with a
  deterministic condensation of their opening sentence as the fallback when the
  LLM is unreachable.
- **It follows the conversation.** Re-derived on every inbound citizen message,
  because an opening message is usually the least informative thing a citizen
  will say ("no power") — the location, the duration and the "it's the whole
  street" arrive in later replies.
- **Two invariants.** An intake-form answer is never a complaint (a bare name,
  email or customer number is skipped via Feature 20's `looks_like_intake_answer`,
  or the field would end up holding the citizen's own phone number); and a worse
  value never replaces a better one (the deterministic path only ever supplies
  the *first* value, so an LLM outage cannot overwrite a derived line with a raw
  truncation).

Sortable server-side as `sortBy=chiefComplaint`, which groups identical
complaint text together — the cheapest duplicate-spotter in the queue.

**Nullable, with two ways to fill in.** A ticket created before V12 has none
until either (a) its next citizen message, at which point `refresh` derives one
from the ticket's whole inbound history rather than from that message alone —
so active tickets self-heal — or (b)
`services/ai-core/scripts/backfill_chief_complaints.py`, for the resolved and
closed tickets that will never get another message. A ticket whose only inbound
messages were intake answers legitimately stays NULL; the UI renders that as
"Not yet determined" rather than pretending.

### ticket_messages
```sql
CREATE TABLE ticket_messages (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenants(id),
  ticket_id      TEXT NOT NULL REFERENCES tickets(id),
  channel        TEXT NOT NULL,
  direction      TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
  author_type    TEXT NOT NULL
                 CHECK(author_type IN ('ai','agent','user','system')),
  author_id      TEXT,                       -- agent id or null
  author_label   TEXT,                       -- display name
  content        TEXT,
  -- PHASE_2_ENCRYPT: content
  media_urls_json TEXT DEFAULT '[]',
  is_ai_generated INTEGER DEFAULT 0,
  created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_messages_ticket ON ticket_messages(ticket_id, created_at);
```

### `ticket_messages.channel_message_id` / `is_intake_request` (Feature 24, V13)

`channel_message_id` is the id the CHANNEL PROVIDER gave a message — a WhatsApp
wamid or an email `Message-ID`. Set on inbound messages from the webhook/poller
and on outbound messages after a successful send.

It exists because a citizen's reply names the message it replies to
(`context.id` on WhatsApp, `In-Reply-To` on email) and that message is one of
**ours**. Storing provider ids for inbound messages only meant the single most
reliable routing signal available was unusable, and a reply of "Yes it is" had
to be matched by heuristics — which is exactly how it reached the wrong ticket.
With this, routing rung 0 resolves such a reply to its ticket exactly, with no
interpretation and no LLM.

`is_intake_request` is 1 on an outbound message that ASKED the citizen for
identity/intake details. A bare "yes" is structurally identical whether it
answers *"did you mean x@gmail.com?"* or *"is this resolved?"*, so the intake
guard may only claim such a message where an intake question was actually asked.

### `unrouted_messages` (Feature 24, V13)

Citizen messages routing could not attribute to any ticket and deliberately did
not invent one for. Columns: `channel`, `channel_identity_value` (the raw
address — NOT a resolved identity, since routing may have failed precisely
because identity never resolved), `content`, `channel_message_id`, `reason`,
`status` (`pending`|`escalated`|`attached`|`discarded`), `resolved_ticket_id`,
`resolved_by`, `ask_count`.

The alternatives were both worse. Dropping the message loses a citizen's words
entirely — nobody can fix what was never stored — and a placeholder ticket puts
permanent noise in the queue. `ask_count` is what stops the clarify loop: the
second unroutable message from a contact escalates rather than asking again.

See the README's *Inbound routing ladder*.


### ticket_notes
```sql
-- Agent / Lead / Admin notes with mandatory note enforcement
CREATE TABLE ticket_notes (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenants(id),
  ticket_id      TEXT NOT NULL REFERENCES tickets(id),
  agent_id       TEXT NOT NULL REFERENCES agents(id),
  content        TEXT NOT NULL CHECK(length(content) >= 1),
  -- Phase 1: length >= 1 (bare minimum)
  -- Status transition notes enforce 20-char minimum at application layer
  is_mandatory   INTEGER DEFAULT 0,
                 -- 1 = triggered by status transition
  transition_from TEXT,                      -- status before
  transition_to   TEXT,                      -- status after
  created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_notes_ticket ON ticket_notes(ticket_id, created_at);
```

### ticket_events (audit trail)
```sql
CREATE TABLE ticket_events (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenants(id),
  ticket_id      TEXT NOT NULL REFERENCES tickets(id),
  event_type     TEXT NOT NULL,
  actor_type     TEXT NOT NULL CHECK(actor_type IN ('system','ai','agent')),
  actor_id       TEXT,
  meta_json      TEXT DEFAULT '{}',
  created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_events_ticket ON ticket_events(ticket_id, created_at);
```

### identity_pending_queue
```sql
CREATE TABLE identity_pending_queue (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenants(id),
  thread_id      TEXT NOT NULL,
  channel        TEXT NOT NULL,
  channel_identity_value TEXT,
  raw_message    TEXT,
  timeout_at     TEXT NOT NULL,
  created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_pending_timeout ON identity_pending_queue(tenant_id, timeout_at);
```

---

## Flyway Migrations

```
services/db-writer/src/main/resources/db/migration/
├── V1__initial_schema.sql
├── V2__add_indexes.sql
└── V3__seed_dev_data.sql   ← runs only when APP_ENV=development
```

---

## Test Stubs

```http
### Get schema version
GET http://localhost:8081/api/v1/internal/schema/version
Authorization: Bearer {{admin_token}}

### Expected
HTTP/1.1 200 OK
{ "version": "1", "appliedMigrations": 3 }

### Verify table exists
GET http://localhost:8081/api/v1/internal/schema/tables
Authorization: Bearer {{admin_token}}

### Expected
HTTP/1.1 200 OK
{ "tables": ["tenants","agents","identity_profiles","tickets",
             "ticket_messages","ticket_notes","ticket_events",
             "identity_pending_queue"] }
```

---

## Mock Data Seed (V3__seed_dev_data.sql)

Inserts when `APP_ENV=development`:

```sql
-- 1 tenant
INSERT INTO tenants(id, name, slug, config_json) VALUES
  ('t1', 'TNEB Demo', 'tneb', '{"categories":{"billing":["incorrect_amount","payment_not_reflected"],"outage":["power_cut","low_voltage"]},"sla":{"default":{"response_hours":4,"resolution_hours":48}}}');

-- 3 agents (admin, lead, agent)
INSERT INTO agents(id, tenant_id, name, email, password_hash, role) VALUES
  ('a1','t1','Admin User','admin@tneb.demo','$2a$12$...hashed...','admin'),
  ('a2','t1','Lead Agent','lead@tneb.demo','$2a$12$...hashed...','lead'),
  ('a3','t1','Field Agent','agent@tneb.demo','$2a$12$...hashed...','agent');

-- 5 identity profiles
-- 25 tickets across all statuses, priorities, channels
-- 40+ notes and messages across tickets
-- Full audit trail events
-- See seed/MockDataSeed.sql for complete insert statements
```

**Login credentials for development:**
- Admin: `admin@tneb.demo` / `Admin@123`
- Lead: `lead@tneb.demo` / `Lead@123`
- Agent: `agent@tneb.demo` / `Agent@123`

---

## Phase 1 Implementation Notes (deviations & corrections)
- **Port 8090** (doc says 8081).
- `schema/version` reports the real latest migration version (**"3"**, i.e. V1+V2+V3); the doc's `"1"` predates the V2/V3 split. `appliedMigrations:3` matches.
- The dev seed **omits the 25 demo tickets** so the first created ticket per tenant is deterministically `TKT-00001` (matches the 04 stub). Seeded agents carry placeholder `password_hash` values that the api-gateway **reseeds to real bcrypt hashes on dev startup** (Feature 11) so login works.
- Flyway runs with `migrate-at-start=true` + `baseline-on-migrate=true`.
- Flyway remains the **single source of schema truth**: the 8 tables (+ indexes) are
  created purely by `V1__initial_schema.sql`/`V2__add_indexes.sql`, never by Hibernate.
  db-writer's Java layer maps Hibernate ORM Panache entities onto these tables
  (`quarkus.hibernate-orm.database.generation=none`, so Hibernate never generates or
  validates DDL against them) — the schema itself is unchanged from what's documented
  here; only the *access layer* moved from plain JDBC to Panache. Re-verified on a
  fresh volume: Flyway applies V1→V2→V3 cleanly, `schema/version` and `schema/tables`
  report correctly, and all 5 seeded identity profiles / 3 seeded agents / 1 pending
  entry are readable through the new entity layer.
- **V8 adds a 9th table: `announcements`** (UI_REVAMP_v2 Feature C) —
  tenant-scoped admin notices for the dashboard bell/banner and the public
  login-page ticker. Columns: `id` (uuid), `tenant_id` → tenants, `title`
  (CHECK ≥3 chars), `body` (CHECK ≥10 chars), `created_by` → agents,
  `is_active` (default 1), `expires_at` (TEXT, NULL = never — expiry is
  evaluated at read time by `AnnouncementService`, no background sweep),
  `created_at`/`updated_at`. Index `idx_announcements_tenant_active`
  on `(tenant_id, is_active, expires_at)`. Mapped by the
  `com.uniserve.dbwriter.model.Announcement` Panache entity, same
  Flyway-owns-DDL rule as every other table. Note the schema's `REFERENCES`
  clauses are decorative here as elsewhere: the sqlite JDBC URL does not
  enable `foreign_keys`, which the tenant DB-reset feature (`/api/v1/db/admin/reset`)
  relies on when it writes its surviving `tenant.reset` audit event with a
  synthetic ticket id.
- **V9 widens `tickets.status`** with `pending_customer` (agent asked the
  citizen a question and parks the ticket awaiting the reply). SQLite cannot
  alter a CHECK constraint, so V9 rebuilds the table in place (create-copy-
  swap + index recreation) with the widened CHECK; data and the
  `UNIQUE(tenant_id, ticket_number)` constraint are preserved. Flow:
  `in_progress ⇄ pending_customer` and `pending_customer → resolved`; RBAC
  action `ticket.status.to_pending_customer` (all roles).

## Status: `cancelled` (Feature 21)

`tickets.status` gained `cancelled` in **V11** (SQLite cannot alter a CHECK
constraint, so the table is rebuilt in place — same 12-step shape as V9).

`cancelled` means *this was never real work*: a confirmed duplicate, a test
row, a withdrawn complaint. It is deliberately distinct from `closed`, which
means the work was done, because reporting must be able to tell them apart:

- `closed_at` **is** stamped (queue and SLA queries already key off it).
- `resolved_at` is deliberately left **NULL** — a cancelled ticket was never
  resolved, and letting it count as one would inflate resolution rate and skew
  MTTR (`AnalyticsResource` keys agent productivity off `resolved_at`).
- The SLA query excludes `status = 'cancelled'` outright. Without that, a
  cancelled ticket with a past `sla_due_at` and no `resolved_at` matches the
  breach clause and counts as breached **forever**.

Rules that are not the database's job:
- Admin only (`ticket.status.to_cancelled` — the one status action a lead
  cannot perform).
- Allowed from any non-terminal status; refused from `closed`/`cancelled`
  (`ALREADY_TERMINAL`).
- Always requires a note of at least 20 characters — cancelling records no
  resolution, so the note is the only account of why, and it is exactly what
  an audit will ask about.

## Writing to the audit trail from another service (Feature 22)

`POST /api/v1/db/tickets/{id}/events` appends a `ticket_events` row.
`ticket_events` was previously writable only from inside `TicketService`, so
no other service could say anything about a ticket except by changing its
status. ai-core uses this to record `ticket.duplicate_merged` on the ORIGINAL
ticket when a citizen confirms another ticket was a duplicate of it.

`actorType` is validated here against the table's own CHECK
(`system`/`ai`/`agent`) so a bad value fails as a 422 rather than an opaque
500 from the constraint. No schema change was needed.
