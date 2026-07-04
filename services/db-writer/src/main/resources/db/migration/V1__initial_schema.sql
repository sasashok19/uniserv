-- Feature 05 — Ticket Schema (Phase 1). Plain-text PII with PHASE_2_ENCRYPT markers
-- in the spec; encryption/blind-index columns are added in Phase 2.

CREATE TABLE tenants (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  slug            TEXT UNIQUE NOT NULL,
  deployment_mode TEXT DEFAULT 'cloud',
  llm_provider    TEXT DEFAULT 'anthropic',
  config_json     TEXT DEFAULT '{}',
  created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE agents (
  id             TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL REFERENCES tenants(id),
  name           TEXT NOT NULL,
  email          TEXT NOT NULL,
  password_hash  TEXT NOT NULL,
  role           TEXT NOT NULL CHECK(role IN ('admin','lead','agent')),
  is_active      INTEGER DEFAULT 1,
  created_at     TEXT DEFAULT (datetime('now')),
  UNIQUE(tenant_id, email)
);

CREATE TABLE identity_profiles (
  id               TEXT PRIMARY KEY,
  tenant_id        TEXT NOT NULL REFERENCES tenants(id),
  master_id        TEXT UNIQUE NOT NULL,
  name             TEXT,
  email            TEXT,
  phone            TEXT,
  channel_ids_json TEXT DEFAULT '[]',
  is_anonymous     INTEGER DEFAULT 0,
  anon_ref_id      TEXT UNIQUE,
  merged_into      TEXT,
  created_at       TEXT DEFAULT (datetime('now')),
  updated_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE tickets (
  id               TEXT PRIMARY KEY,
  tenant_id        TEXT NOT NULL REFERENCES tenants(id),
  ticket_number    TEXT NOT NULL,
  identity_id      TEXT REFERENCES identity_profiles(id),
  identity_status  TEXT DEFAULT 'pending'
                   CHECK(identity_status IN ('pending','confirmed','anonymous','timeout')),
  identity_source  TEXT,
  assigned_to      TEXT REFERENCES agents(id),
  status           TEXT DEFAULT 'open'
                   CHECK(status IN ('open','assigned','in_progress','resolved','closed','reopened')),
  category         TEXT,
  subcategory      TEXT,
  priority_score   REAL,
  priority_label   TEXT CHECK(priority_label IN ('critical','high','medium','low')),
  sentiment_score  REAL,
  channel_origin   TEXT NOT NULL,
  is_duplicate     INTEGER DEFAULT 0,
  parent_ticket_id TEXT REFERENCES tickets(id),
  resolution       TEXT,
  sla_due_at       TEXT,
  resolved_at      TEXT,
  closed_at        TEXT,
  reopened_count   INTEGER DEFAULT 0,
  reopened_by      TEXT REFERENCES agents(id),
  created_at       TEXT DEFAULT (datetime('now')),
  updated_at       TEXT DEFAULT (datetime('now')),
  UNIQUE(tenant_id, ticket_number)
);

CREATE TABLE ticket_messages (
  id              TEXT PRIMARY KEY,
  tenant_id       TEXT NOT NULL REFERENCES tenants(id),
  ticket_id       TEXT NOT NULL REFERENCES tickets(id),
  channel         TEXT NOT NULL,
  direction       TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
  author_type     TEXT NOT NULL CHECK(author_type IN ('ai','agent','user','system')),
  author_id       TEXT,
  author_label    TEXT,
  content         TEXT,
  media_urls_json TEXT DEFAULT '[]',
  is_ai_generated INTEGER DEFAULT 0,
  created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE ticket_notes (
  id              TEXT PRIMARY KEY,
  tenant_id       TEXT NOT NULL REFERENCES tenants(id),
  ticket_id       TEXT NOT NULL REFERENCES tickets(id),
  agent_id        TEXT NOT NULL REFERENCES agents(id),
  content         TEXT NOT NULL CHECK(length(content) >= 1),
  is_mandatory    INTEGER DEFAULT 0,
  transition_from TEXT,
  transition_to   TEXT,
  created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE ticket_events (
  id          TEXT PRIMARY KEY,
  tenant_id   TEXT NOT NULL REFERENCES tenants(id),
  ticket_id   TEXT NOT NULL REFERENCES tickets(id),
  event_type  TEXT NOT NULL,
  actor_type  TEXT NOT NULL CHECK(actor_type IN ('system','ai','agent')),
  actor_id    TEXT,
  meta_json   TEXT DEFAULT '{}',
  created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE identity_pending_queue (
  id                     TEXT PRIMARY KEY,
  tenant_id              TEXT NOT NULL REFERENCES tenants(id),
  thread_id              TEXT NOT NULL,
  channel                TEXT NOT NULL,
  channel_identity_value TEXT,
  raw_message            TEXT,
  timeout_at             TEXT NOT NULL,
  created_at             TEXT DEFAULT (datetime('now'))
);
