-- Feature: Admin announcements (UI_REVAMP_v2 Feature C).
-- Tenant-scoped notices authored by admins, shown to agents (topbar bell +
-- banner) and, title-only, on the public login page ticker.
CREATE TABLE IF NOT EXISTS announcements (
  id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  title       TEXT NOT NULL CHECK(length(trim(title)) >= 3),
  body        TEXT NOT NULL CHECK(length(trim(body)) >= 10),
  created_by  TEXT NOT NULL REFERENCES agents(id),
  is_active   INTEGER NOT NULL DEFAULT 1,
  expires_at  TEXT,              -- ISO 8601 / sqlite datetime, NULL = never expires
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_announcements_tenant_active
  ON announcements(tenant_id, is_active, expires_at);
