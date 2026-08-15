-- Feature 26: an ETA the citizen can actually be told, captured at the moment
-- someone first takes the ticket on.
--
-- Why a new column rather than reusing `sla_due_at`: they answer different
-- questions and would fight each other. `sla_due_at` is the deadline the TENANT
-- is held to — derived from category/priority policy, the thing a breach report
-- counts against. `eta_at` is the promise an AGENT made to a CITIZEN after
-- looking at the actual work. A ticket can be inside SLA and still have an
-- honest ETA past it (parts on order), and a citizen must be told the second,
-- not the first. `sla_due_at` also has no writer today — nothing in the repo
-- computes it — so overloading it would have quietly changed what an unused
-- column means the moment something did start computing it.
--
-- `first_transition_at` exists because "mandatory as part of the first
-- transition" needs "first" to be a fact, not a guess. It was previously only
-- derivable by scanning ticket_events for `status.%` and taking the earliest —
-- a read that every transition would then have to perform in order to decide
-- whether to enforce the ETA. One stamped column turns that into a null check.
--
-- Both are plain additive ALTERs. Neither touches the tickets CHECK constraint,
-- so this deliberately avoids the 12-step table rebuild that V9 and V11 needed
-- (SQLite cannot ALTER a CHECK).

ALTER TABLE tickets ADD COLUMN eta_at TEXT NULL;
ALTER TABLE tickets ADD COLUMN first_transition_at TEXT NULL;

-- Existing tickets predate the rule. Backfilling `first_transition_at` from the
-- audit trail is what stops every one of them demanding an ETA the next time an
-- agent touches it — the rule is "set an ETA when you first pick this up", and
-- these were picked up long ago. Tickets that genuinely never transitioned stay
-- NULL and will be asked for an ETA on their first move, which is correct.
UPDATE tickets
   SET first_transition_at = (
         SELECT MIN(e.created_at)
           FROM ticket_events e
          WHERE e.ticket_id = tickets.id
            AND e.event_type LIKE 'status.%'
       )
 WHERE first_transition_at IS NULL;

-- The citizen-facing "when will this be done?" read (WhatsApp menu option 1)
-- and the agent queue's overdue-ETA view both filter on it.
CREATE INDEX idx_tickets_eta ON tickets(tenant_id, eta_at);
