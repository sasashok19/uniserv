-- Feature 05 — indexes

CREATE INDEX idx_agents_tenant          ON agents(tenant_id);

CREATE INDEX idx_identity_tenant        ON identity_profiles(tenant_id);
CREATE INDEX idx_identity_email         ON identity_profiles(tenant_id, email);
CREATE INDEX idx_identity_phone         ON identity_profiles(tenant_id, phone);

CREATE INDEX idx_tickets_tenant_status   ON tickets(tenant_id, status);
CREATE INDEX idx_tickets_tenant_priority ON tickets(tenant_id, priority_score DESC);
CREATE INDEX idx_tickets_assigned        ON tickets(assigned_to);
CREATE INDEX idx_tickets_created         ON tickets(tenant_id, created_at DESC);

CREATE INDEX idx_messages_ticket ON ticket_messages(ticket_id, created_at);
CREATE INDEX idx_notes_ticket    ON ticket_notes(ticket_id, created_at);
CREATE INDEX idx_events_ticket   ON ticket_events(ticket_id, created_at);
CREATE INDEX idx_pending_timeout ON identity_pending_queue(tenant_id, timeout_at);
