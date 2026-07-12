-- Feature 06/12: track a ticket from the moment a message arrives, not only
-- once identity is confirmed and enough detail is gathered. thread_id lets
-- ai-core find the same ticket across turns (Valkey conversation state
-- expires after a couple of hours — far too short for a thread that might
-- take days/weeks to confirm identity, so the lookup key has to live here
-- instead). archived_at is a soft-delete for the 60-day unconfirmed cleanup
-- — archived tickets are hidden from every queue but never actually removed.

ALTER TABLE tickets ADD COLUMN thread_id TEXT NULL;
ALTER TABLE tickets ADD COLUMN archived_at TEXT NULL;
CREATE INDEX idx_tickets_thread ON tickets(tenant_id, thread_id);
