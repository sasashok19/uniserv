-- Feature 24: inbound routing that can find the ticket we were talking on.
--
-- The bug this exists for: an agent asked "Is this resolved?" on a RESOLVED
-- ticket, the citizen replied "Yes it is" on WhatsApp, and the reply was filed
-- against a different, unrelated ticket. Three causes, two of which are schema:
--
-- 1. `channel_message_id` — WhatsApp gives us `context.id` on a swipe-reply and
--    email gives us `In-Reply-To`; both name the message the citizen replied
--    TO, which is one of OURS. We stored the provider id of inbound messages
--    only (on tickets.origin_message_id), never of the messages we send, so the
--    single most reliable routing signal available was unusable. Now every
--    outbound message records the id the provider assigned it, and an inbound
--    reply-to resolves to its ticket exactly — no heuristic, no LLM.
--
-- 2. `is_intake_request` — a bare "yes" is structurally indistinguishable from
--    "yes, that's my email" (see ai-core's `looks_like_intake_answer`), and the
--    intake guard was grabbing any such message for whichever stub was
--    mid-intake. Marking the outbound messages that actually ASKED an intake
--    question lets that guard fire only when the citizen is plausibly answering
--    one.
--
-- 3. (not schema) `resolved`/`pending_customer` were excluded from the routing
--    candidate set — see ai-core's app/dedup/service.py.

ALTER TABLE ticket_messages ADD COLUMN channel_message_id TEXT NULL;
ALTER TABLE ticket_messages ADD COLUMN is_intake_request INTEGER DEFAULT 0;

-- Routing looks a message up by the provider id on every inbound reply, so this
-- is a hot read path, not a reporting one.
CREATE INDEX idx_ticket_messages_channel_msg
  ON ticket_messages(tenant_id, channel_message_id);
-- "What did we last ask on this ticket, and was it an intake question?"
CREATE INDEX idx_ticket_messages_outbound
  ON ticket_messages(ticket_id, direction, created_at DESC);

-- Messages that could not be attributed to any ticket, and that must not
-- invent one: a bare "yes"/"ok"/"you are correct" with no ticket reference, no
-- reply-to, and nothing our outstanding questions explain. Previously such a
-- message either created a junk ticket or was appended to an unrelated one.
--
-- The alternative designs were worse. Dropping the message loses a citizen's
-- words entirely — no agent can ever find it, which is worse than a misroute.
-- Creating a placeholder ticket puts noise in the queue that reporting then has
-- to exclude forever. So it lands here: durable, visible to leads/admins in its
-- own queue, and attachable to the right ticket in one click.
CREATE TABLE unrouted_messages (
  id                      TEXT PRIMARY KEY,
  tenant_id               TEXT NOT NULL REFERENCES tenants(id),
  channel                 TEXT NOT NULL,
  -- The citizen's channel address (phone/email). Deliberately NOT a resolved
  -- identity_id: routing may fail precisely because identity never resolved,
  -- and we still have to keep the message.
  channel_identity_value  TEXT,
  content                 TEXT NOT NULL,
  channel_message_id      TEXT,
  reason                  TEXT,          -- why routing gave up, for the agent
  -- pending  : stored, citizen asked for a ticket reference
  -- escalated: asked once already and the next message was also unroutable
  -- attached : an agent filed it against a ticket (resolved_ticket_id set)
  -- discarded: an agent judged it noise
  status                  TEXT NOT NULL DEFAULT 'pending'
                          CHECK(status IN ('pending','escalated','attached','discarded')),
  resolved_ticket_id      TEXT REFERENCES tickets(id),
  resolved_by             TEXT REFERENCES agents(id),
  -- How many times we have asked THIS contact to clarify. The second
  -- unroutable message escalates instead of asking again, so a citizen who
  -- replies "I don't have it" is never stuck in an ask loop.
  ask_count               INTEGER NOT NULL DEFAULT 0,
  created_at              TEXT DEFAULT (datetime('now')),
  updated_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_unrouted_tenant_status ON unrouted_messages(tenant_id, status, created_at DESC);
-- ai-core reads "has this contact already been asked?" on every rung-5 message.
CREATE INDEX idx_unrouted_contact ON unrouted_messages(tenant_id, channel_identity_value, created_at DESC);
