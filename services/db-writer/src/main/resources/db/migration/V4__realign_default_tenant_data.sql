-- Fix: every service's TENANT_ID env var defaulted to "default", so all
-- live/test data (identities, tickets, messages, notes, events) landed
-- under tenant "default" — while V3's seeded demo agents (admin/lead/agent
-- @tneb.demo) live under tenant "t1" ("TNEB Demo", the one with real
-- category/SLA config). Result: logging in as any seeded agent showed zero
-- tickets. Realign existing "default"-tenant rows to "t1"; the env var
-- defaults are also fixed going forward so new data lands in the same place.

UPDATE identity_profiles SET tenant_id = 't1' WHERE tenant_id = 'default';
UPDATE identity_pending_queue SET tenant_id = 't1' WHERE tenant_id = 'default';
UPDATE tickets SET tenant_id = 't1' WHERE tenant_id = 'default';
UPDATE ticket_messages SET tenant_id = 't1' WHERE tenant_id = 'default';
UPDATE ticket_notes SET tenant_id = 't1' WHERE tenant_id = 'default';
UPDATE ticket_events SET tenant_id = 't1' WHERE tenant_id = 'default';
