-- Feature 15: every outbound reply needs something to set In-Reply-To/References
-- against so citizens' mail clients thread it into the same conversation. The
-- inbound email that started the ticket is the one stable anchor for the whole
-- chain, so its own Message-ID is captured once and reused for every reply.

ALTER TABLE tickets ADD COLUMN origin_message_id TEXT NULL;
