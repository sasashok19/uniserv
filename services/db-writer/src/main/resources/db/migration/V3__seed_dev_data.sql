-- Feature 05 — dev seed. Phase 1: runs as a normal migration (dev-focused stack).
-- Tickets are intentionally NOT seeded so the first created ticket per tenant is
-- TKT-00001 (matches the 04 test stub). password_hash values are placeholders —
-- real bcrypt hashing arrives with auth (Feature 11).

INSERT OR IGNORE INTO tenants(id, name, slug, config_json) VALUES
  ('t1', 'TNEB Demo', 'tneb', '{"categories":{"billing":["incorrect_amount","payment_not_reflected"],"outage":["power_cut","low_voltage"]},"sla":{"default":{"response_hours":4,"resolution_hours":48}}}'),
  ('default', 'Default Tenant', 'default', '{}');

INSERT OR IGNORE INTO agents(id, tenant_id, name, email, password_hash, role) VALUES
  ('a1','t1','Admin User','admin@tneb.demo','PLACEHOLDER_BCRYPT_HASH','admin'),
  ('a2','t1','Lead Agent','lead@tneb.demo','PLACEHOLDER_BCRYPT_HASH','lead'),
  ('a3','t1','Field Agent','agent@tneb.demo','PLACEHOLDER_BCRYPT_HASH','agent');

-- 5 identity profiles: 2 WhatsApp (phone), 1 email, 1 anonymous, 1 plain.
INSERT OR IGNORE INTO identity_profiles(id, tenant_id, master_id, name, email, phone, is_anonymous, anon_ref_id) VALUES
  ('i1','t1','m1','Seed WhatsApp One', NULL, '+919999900001', 0, NULL),
  ('i2','t1','m2','Seed WhatsApp Two', NULL, '+919999900002', 0, NULL),
  ('i3','t1','m3','Rajesh Kumar', 'rajesh@example.com', NULL, 0, NULL),
  ('i4','t1','m4', NULL, NULL, NULL, 1, 'ANON-TEST'),
  ('i5','t1','m5','Seed Plain', 'plain@example.com', NULL, 0, NULL);

-- 1 pending identity (timeout well in the future).
INSERT OR IGNORE INTO identity_pending_queue(id, tenant_id, thread_id, channel, channel_identity_value, raw_message, timeout_at) VALUES
  ('pq1','t1','seed-thread-pending','email','pending@example.com','My bill seems wrong', datetime('now','+48 hours'));
