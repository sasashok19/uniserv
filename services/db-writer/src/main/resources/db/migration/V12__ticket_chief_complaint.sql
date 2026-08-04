-- Feature 23: the citizen's chief complaint — the one-line answer to "what is
-- this ticket actually about". Until now the only place that existed was the
-- free text of the ticket's first inbound message, so neither the queue nor
-- the ticket-detail header could show it: an agent scanning the queue saw
-- TKT-00042 / open / high / billing and had to open the ticket to learn what
-- the citizen wanted.
--
-- Derived by ai-core from the first email/WhatsApp message that triggered the
-- ticket, and re-derived as the citizen answers back (see
-- services/ai-core/app/tickets/chief_complaint.py) — so it tracks the
-- complaint as it is actually understood, not just as it was first worded.
-- Nullable by necessity: a stub created on arrival has one only once its
-- first inbound message has been persisted, and a ticket created before this
-- migration has none until its next citizen reply.

ALTER TABLE tickets ADD COLUMN chief_complaint TEXT NULL;
