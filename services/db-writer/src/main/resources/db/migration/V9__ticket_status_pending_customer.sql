-- Add 'pending_customer' to the tickets.status CHECK (agent has asked the
-- citizen a question and parks the ticket awaiting their reply). SQLite
-- cannot alter a CHECK constraint, so rebuild the table in place (standard
-- 12-step): new table with the widened CHECK, copy, swap, recreate indexes.
CREATE TABLE tickets_new (
  id               TEXT PRIMARY KEY,
  tenant_id        TEXT NOT NULL REFERENCES tenants(id),
  ticket_number    TEXT NOT NULL,
  identity_id      TEXT REFERENCES identity_profiles(id),
  identity_status  TEXT DEFAULT 'pending'
                   CHECK(identity_status IN ('pending','confirmed','anonymous','timeout')),
  identity_source  TEXT,
  assigned_to      TEXT REFERENCES agents(id),
  status           TEXT DEFAULT 'open'
                   CHECK(status IN ('open','assigned','in_progress','pending_customer','resolved','closed','reopened')),
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
  thread_id        TEXT NULL,
  archived_at      TEXT NULL,
  service_id       TEXT NULL,
  origin_message_id TEXT NULL,
  UNIQUE(tenant_id, ticket_number)
);

INSERT INTO tickets_new (
  id, tenant_id, ticket_number, identity_id, identity_status, identity_source,
  assigned_to, status, category, subcategory, priority_score, priority_label,
  sentiment_score, channel_origin, is_duplicate, parent_ticket_id, resolution,
  sla_due_at, resolved_at, closed_at, reopened_count, reopened_by, created_at,
  updated_at, thread_id, archived_at, service_id, origin_message_id)
SELECT
  id, tenant_id, ticket_number, identity_id, identity_status, identity_source,
  assigned_to, status, category, subcategory, priority_score, priority_label,
  sentiment_score, channel_origin, is_duplicate, parent_ticket_id, resolution,
  sla_due_at, resolved_at, closed_at, reopened_count, reopened_by, created_at,
  updated_at, thread_id, archived_at, service_id, origin_message_id
FROM tickets;

DROP TABLE tickets;
ALTER TABLE tickets_new RENAME TO tickets;

CREATE INDEX idx_tickets_tenant_status   ON tickets(tenant_id, status);
CREATE INDEX idx_tickets_tenant_priority ON tickets(tenant_id, priority_score DESC);
CREATE INDEX idx_tickets_assigned        ON tickets(assigned_to);
CREATE INDEX idx_tickets_created         ON tickets(tenant_id, created_at DESC);
CREATE INDEX idx_tickets_thread          ON tickets(tenant_id, thread_id);
