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
