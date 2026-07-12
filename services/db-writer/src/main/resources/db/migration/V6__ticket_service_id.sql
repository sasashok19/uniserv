-- Feature 12/15: Service/Customer ID was only ever captured as free text
-- inside the ticket's first message. Promote it to a real column so
-- ticket detail can show it as structured, read-only data.

ALTER TABLE tickets ADD COLUMN service_id TEXT NULL;
