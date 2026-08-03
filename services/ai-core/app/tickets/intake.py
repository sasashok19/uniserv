"""Ticket lifecycle from the moment a message arrives (Feature 06 x 12).

Closes a gap in the original design: a ticket only existed once identity was
confirmed *and* enough complaint detail was gathered — a citizen who never
completed identity confirmation left no visible trace anywhere. Now a bare
stub is created on the very first message and updated in place (never
re-created) as the conversation progresses:

  arrival -> stub (identity_status=pending, no category)
  identity confirmed/anonymous -> same row, identityId + identityStatus set
  complaint.ready -> same row, category/priority/etc set (see tickets/service.py)

The thread->ticket lookup has to live in the database, not Valkey
conversation state: state expires in ~2 hours, but an unconfirmed thread may
sit for days before (or without ever) resolving identity.

Feature 15: a reply's subject line is a far more reliable signal than
thread/category matching for "is this the SAME complaint, continued" — an
email client always keeps the subject (as "Re: ...") when a citizen replies,
so once a ticket's number is embedded in every outbound subject, an inbound
subject that echoes it back unambiguously identifies which ticket this
message belongs to. A citizen starting a brand-new email (no ticket number
in the subject) is, by definition, a different complaint and must never be
folded into an old ticket just because it happens to land in the same
category — see the removed category-based dedup in tickets/service.py.

Feature 17: WhatsApp has no subject line, so it never had an equivalent of
the above — its thread key (`whatsapp:<phone>`) is the SAME for every
message that number ever sends, and the old threadId lookup below applied
no status filter at all. That meant a citizen whose ticket had already been
resolved, texting weeks later about something completely unrelated, got
silently appended to the old, resolved ticket rather than starting a new
one. Fixes, all channel-agnostic in principle:
- An explicit `TKT-XXXXX` reference now resolves regardless of channel —
  checked in the raw message body, not just an email subject, so a citizen
  on ANY channel who mentions a ticket number gets routed to it exactly
  (this is also what a citizen naturally does when asked to disambiguate
  between multiple open tickets, below).
- The threadId fallback now requires the ticket still be OPEN — an
  accidental thread-key collision (WhatsApp) must never resurrect a closed
  ticket, whereas a citizen-typed reference still can (that's a deliberate
  citizen action, e.g. reopening).
- For a channel with no subject line at all (WhatsApp today), resolution
  now tries identity + open-ticket count BEFORE the threadId match, not
  after: zero open tickets -> new; exactly one -> append (matches the
  identity+category dedup `check_duplicate` already does for the no-stub
  case); two or more -> still create a new ticket rather than guessing
  which one this continues (a wrong silent merge is worse than an extra
  ticket an agent can merge by hand). The threadId match is now reached
  ONLY when identity hasn't linked to any ticket yet (still a safety net
  for that narrow window) — it used to run FIRST, which meant it always
  won as long as a single ticket for that phone number was open, silently
  reusing it for a genuinely unrelated new complaint (reported live: a
  second, different complaint got appended as a note onto an existing
  "No power" ticket) — the exact "too coarse a signal" failure mode
  category-based dedup had for email, just recreated one layer deeper.
  A full "which of your N open complaints is this" back-and-forth is not
  implemented yet (see README's "Subject-line ticket threading & dedup"
  section).

Feature 18: even the fix above has a gap count-based logic alone can't
close — when there is EXACTLY one open ticket, "append" was still the
unconditional default, and a keyword classifier gives no signal either way
for an uncategorisable message ("Put not closed" doesn't match ANY
category keyword, same as a genuine vague follow-up like "any update?").
Live-tested: a second, unrelated complaint got appended onto an existing
"No power" ticket even after the reorder fix, because there was only ONE
open ticket at the time. Closed with a real content judgment
(`app/classify/message_quality.is_same_topic`) comparing the new message
against the existing ticket's own original complaint text — best-effort
(falls back to "same topic", i.e. append, on any LLM failure/unavailability,
same as every other LLM-assisted decision in this codebase).

Feature 19: even Feature 18's same-topic judgment can misfire on a short,
context-free follow-up ("It happens around 11PM" alone gives no topic
signal either way) — live-tested, this created a needless duplicate ticket
for a citizen who had explicitly swipe-replied to their original WhatsApp
message. A swipe-reply's quoted-message id (Meta's `context.id`) was
already captured by the WhatsApp adapter but never used for inbound
routing, only for outbound reply threading. `ensure_ticket_stub` now
checks it FIRST, against every ticket's own `origin_message_id` — the most
explicit, un-inferred continuation signal a citizen can give, ahead of
even an explicit ticket-number-in-text match. Requires a new
`originMessageId` filter on db-writer's `GET /api/v1/db/tickets`
(`TicketService.buildWhere`), since routing needs to look a message up by
what it's a reply to, not just by ticket number/thread/identity.

Feature 20: Features 17-19 all tuned "is this a NEW complaint or a
continuation" for messages that are, one way or another, ABOUT a complaint.
They never considered the other half of every WhatsApp conversation — the
citizen answering the intake form we just sent them ("Nithya",
"nithya@gmail.com", "56784567"). That text names no subject, location, or
problem, so Feature 18's `is_same_topic` correctly (by its own definition)
answers "different topic", and the router turned each answer into its own
brand-new ticket. Live-tested: one citizen, three messages, three tickets
(TKT-00016 stub, then TKT-00017 and TKT-00018 for the two intake replies) —
and because conversation state is keyed on the ticket
(`ConversationAgent._conv_key`), each new ticket also reset the assistant's
memory of the original complaint, so the third message's "complaint" was
recorded as the citizen's own email address.

The fix is a guard ahead of the topic judgment rather than a change to it:
a ticket that has no `category` yet has never had a complaint filed on it —
it is a stub still IN the intake back-and-forth — and a message that is
purely intake data (`looks_like_intake_answer`) is by definition an answer
to that back-and-forth, not a new complaint. Both conditions must hold, so
a genuine second complaint (which reads as prose, not form data) still
splits off its own ticket exactly as Feature 18 intended.
"""

import logging
import re
from typing import Optional

from app.classify.message_quality import match_open_ticket
from app.dedup.service import OPEN_STATUSES
from app.identity.db_client import DbWriterClient

logger = logging.getLogger("ai-core")

TICKET_NUMBER_RE = re.compile(r"TKT-\d{4,}")

# How many of the citizen's open tickets are put to the model at once. They
# arrive newest-first, so this bounds prompt size (and cost) on an account with
# a long tail of stale open tickets without affecting the realistic cases.
_MAX_MATCH_CANDIDATES = 8

# --- "Is this message just intake-form data?" (Feature 20) ------------------
# Deliberately deterministic (no LLM): this guard decides whether to even ASK
# the LLM topic question, so routing an identity answer must not itself depend
# on an LLM being reachable. The rules are structural — an address, a label, a
# bare identifier — never semantic, so they can't drift the way a prompt can.

_EMAIL_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,24}")
# Field labels the intake form actually prints. Matched per-token and counted
# as a POSITIVE signal, so the set is kept to words that essentially only
# appear when someone is naming a form field. ("area" is deliberately absent:
# "no power in my area" is a complaint, not a pin-code answer.)
_LABEL_TOKEN_RE = re.compile(
    r"^(?:name|e-?mail|mobile|service|customer|consumer|id|pin|pincode|anonymous)$", re.IGNORECASE)
# Words that carry no signal either way — skipped without counting, so that a
# message consisting of "Name: Nithya" and one consisting of "Nithya" are
# judged the same way.
_FILLER_TOKEN_RE = re.compile(
    r"^(?:is|are|am|my|the|a|an|and|it|its|it's|this|that|here|number|no\.|code|for|to|of|sir|madam"
    r"|thanks|thank|you|hi|hello|ok|okay|yes)$", re.IGNORECASE)
# A bare identifier the citizen was asked for: service/customer id, mobile,
# pin code. 4+ characters so an ordinary numeral in prose ("11PM", "2 days")
# never qualifies.
_IDENTIFIER_TOKEN_RE = re.compile(r"^[+#]?[\d][\d\-/]{0,19}$")
_MIN_IDENTIFIER_DIGITS = 4
# Emoji, stray punctuation, a lone "-" — carries no meaning either way, and a
# 🙏 at the end of "Thanks 🙏 Nithya" must not make the message unreadable.
_NO_LETTERS_OR_DIGITS_RE = re.compile(r"^[^\w]+$", re.UNICODE)


def _is_name_like(token: str) -> bool:
    """A token that could be part of somebody's name: has a letter, has no
    digit. Written as a predicate rather than a character class because a
    class can't express "any script" in Python's `re` — `\\w` excludes the
    combining vowel marks that Tamil, Devanagari and most Indic scripts are
    built from, so "சித்ரா" would be rejected as unreadable by any pattern
    that spells out its allowed characters."""
    return any(ch.isalpha() for ch in token) and not any(ch.isdigit() for ch in token)
# The decisive negative check. Anything a citizen writes to DESCRIBE something
# — a negation, a state, a utility, a request — disqualifies the message from
# being "just form data", however short it is and whatever labels it happens
# to contain. Without this, "my phone is not working" reads as a Mobile-field
# answer ("phone" is a label, the rest is short and alphabetic); with it, the
# leftover "not"/"working" settles the question. Erring here is one-directional
# by design: a missed intake answer only costs the Feature-18 topic check
# being consulted, which is the pre-Feature-20 behaviour.
_STATEMENT_WORD_RE = re.compile(
    r"^(?:not|n't|isn't|don't|doesn't|didn't|can't|won't|cannot|no|none|never|still|again|yet|but"
    r"|work|works|working|worked|broke|broken|break|down|out|off|dead|fail|failed|failure"
    r"|issue|issues|problem|problems|complaint|complain|fix|fixed|repair|resolve|resolved|help"
    r"|since|yesterday|today|tomorrow|days|hours|weeks|months|morning|night|evening"
    r"|power|electricity|water|light|lights|meter|bill|billing|supply|voltage|current|line|wire"
    r"|streetlight|streetlamp|transformer|blackout|sewage|sewer|drainage|drain|garbage|waste"
    r"|pipeline|pipe|connection|refund|overcharge|overcharged|reading|tariff|deposit|arrears"
    r"|leak|leaking|outage|cut|low|high|slow|bad|wrong|poor|delay|delayed|pending|open|closed"
    r"|update|status|why|when|where|how|what)$",
    re.IGNORECASE)

# Negations and affirmations are statement words on their own ("no power") but
# ordinary punctuation in a correction ("no, it's dharshini@gmail.com" — the
# literal shape of the reply the Feature 20 email-typo question asks for).
# They're only forgiven alongside a concrete value in the same message, which
# is exactly what makes it a correction rather than a statement.
_CORRECTION_PARTICLE_RE = re.compile(
    r"^(?:no|nope|yes|yeah|yep|not|correct|incorrect|right|wrong|actually|sorry|instead|rather"
    r"|change|changed|typo|mistake|use|should|be)$",
    re.IGNORECASE)

_MAX_INTAKE_ANSWER_WORDS = 25
_MAX_RESIDUAL_NAME_TOKENS = 4
_MAX_BARE_NAME_TOKENS = 3


def looks_like_intake_answer(text: Optional[str]) -> bool:
    """True when a message is (only) the citizen answering the intake form —
    name / email / service id / pin code — with no complaint content of its
    own.

    Everything left over after removing the structural parts (an email
    address, a form label, a bare identifier) must read like a name fragment
    rather than a statement, and any statement word anywhere disqualifies the
    message outright (bar a negation/affirmation sitting next to a concrete
    value — that's a correction, see `_CORRECTION_PARTICLE_RE`). With no
    structural part at all, only a one-or-two-word
    bare name qualifies — see the note at the end. Long messages are rejected
    up front: a form answer is short, and anything discursive enough to run
    past a dozen words is making a point, not filling in a field.
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if len(stripped.split()) > _MAX_INTAKE_ANSWER_WORDS:
        return False

    has_email = bool(_EMAIL_TOKEN_RE.search(stripped))
    residue = _EMAIL_TOKEN_RE.sub(" ", stripped)
    tokens = [t for t in (raw.strip(".,;:!?()[]-") for raw in re.split(r"[\s,;:/|]+", residue))
              if t and not _NO_LETTERS_OR_DIGITS_RE.match(t)]
    if not tokens:
        # Nothing but an email address (or nothing but emoji) — the former is
        # the commonest intake answer of all, the latter answers nothing.
        return has_email

    # A pure yes/no. Nothing else it can be: an unprompted message is never
    # just "yes", whereas the reply to "did you mean x@gmail.com?" invariably
    # is — and if this doesn't route back to the stub that asked, the
    # correction turn spawns the duplicate ticket the whole guard prevents.
    if all(_CORRECTION_PARTICLE_RE.match(t) or _FILLER_TOKEN_RE.match(t) for t in tokens):
        return True

    # Identifiers are often typed in groups ("600 042", "+91 89390 14142"), so
    # digits are counted across the whole message rather than per token.
    digits = sum(len(re.sub(r"\D", "", t)) for t in tokens if _IDENTIFIER_TOKEN_RE.match(t))
    has_identifier = digits >= _MIN_IDENTIFIER_DIGITS
    # A concrete value in the message is what licenses reading "no"/"yes" as
    # correction punctuation rather than as complaint content.
    correcting = has_email or has_identifier

    has_label = False
    leftover = []
    for token in tokens:
        if correcting and _CORRECTION_PARTICLE_RE.match(token):
            continue
        if _STATEMENT_WORD_RE.match(token):
            return False
        if _LABEL_TOKEN_RE.match(token):
            has_label = True
            continue
        if _FILLER_TOKEN_RE.match(token) or _IDENTIFIER_TOKEN_RE.match(token):
            continue
        leftover.append(token)

    if not all(_is_name_like(token) for token in leftover):
        return False
    if has_email or has_label or has_identifier:
        return len(leftover) <= _MAX_RESIDUAL_NAME_TOKENS
    # No structural marker at all: the only remaining thing this can be is a
    # bare name typed on its own ("Nithya", "Ravi Kumar Sharma") — exactly how
    # citizens answer "what's your name?", and unrecognisable as intake data
    # by any other means. This is the loosest rule here and it does misread a
    # terse noun-phrase complaint ("stray dogs") as a name; the utility and
    # service nouns citizens actually use that way are named in
    # `_STATEMENT_WORD_RE` above, but that list can never be complete. The
    # trade is deliberate and one-sided: a false positive appends to a stub
    # whose intake is still unfinished (the assistant carries both messages in
    # one conversation, and an agent can split them), whereas a false negative
    # is the reported bug itself — a duplicate ticket AND a wiped conversation.
    return 1 <= len(leftover) <= _MAX_BARE_NAME_TOKENS


def extract_ticket_number(text: Optional[str]) -> Optional[str]:
    """Pull a ticket number (e.g. "TKT-00042") out of a subject line or
    message body — either way, an explicit citizen-visible reference."""
    if not text:
        return None
    match = TICKET_NUMBER_RE.search(text)
    return match.group(0) if match else None


async def _find_identity_for_channel(
    db: DbWriterClient, tenant_id: str, identity_type: Optional[str], identity_value: Optional[str],
    trace_id: Optional[str] = None,
) -> Optional[dict]:
    """Best-effort identity lookup by the channel's own address — used only
    for ROUTING (which open ticket, if any, this message continues), not for
    identity confirmation (that's the conversation agent's job)."""
    if not identity_value:
        return None
    if identity_type == "phone":
        return await db.find_by_phone(tenant_id, identity_value, trace_id=trace_id)
    if identity_type == "email":
        return await db.find_by_email(tenant_id, identity_value, trace_id=trace_id)
    return None


async def ensure_ticket_stub(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str,
    subject: Optional[str] = None, raw_text: Optional[str] = None,
    channel_identity_type: Optional[str] = None, channel_identity_value: Optional[str] = None,
    origin_message_id: Optional[str] = None, in_reply_to: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> dict:
    """Find the ticket this message belongs to, or create a bare stub.

    Resolution order, most explicit signal first:

    1. `in_reply_to` (Feature 19) — a WhatsApp swipe-reply's quoted-message
       id or an email's In-Reply-To header. When it matches some ticket's
       own `origin_message_id`, the citizen has taken an explicit UI action
       (or their mail client has) pointing at exactly one prior message —
       stronger than anything inferred from text or identity, and needs no
       interpretation at all. Previously this field was parsed by the
       WhatsApp adapter (`WhatsAppParser.inReplyTo`) but never used for
       inbound routing, only for outbound reply threading — a citizen who
       swiped to reply on their original complaint still fell through to
       the identity/topic heuristic below, which has no way to know a
       swipe-reply happened and can (and, live-tested, did) misjudge a
       short follow-up like "It happens around 11PM" as a different topic
       from the original message, creating a duplicate ticket instead of
       appending to the one being replied to.
    2. An explicit `TKT-XXXXX` reference (subject or message body) — a
       citizen-visible, explicit reference rather than an inferred one,
       and is what lets a reply to an old ticket resolve to that exact
       ticket even if `in_reply_to` isn't available (or the citizen
       re-quotes an old message in a new one rather than replying to it).
    3. The identity's one still-in-intake stub, when this message is nothing
       but intake-form data (Feature 20) — the citizen is answering the
       question that stub asked, so no count or topic reasoning applies.
    4. Identity + open-ticket-count/topic heuristic, then thread_key — see
       below and the module docstring. `thread_key` itself is unique per
       email when there's no real In-Reply-To (see
       `ConversationAgent._thread_key`), so the threadId lookup is a
       perfectly good PRIMARY signal for email; for WhatsApp (a stable
       per-phone key, not a per-conversation one) it's only a safety-net
       FALLBACK for the narrow window before identity has linked to a
       ticket at all.
    """
    if in_reply_to:
        matches = await db.list_tickets(tenant_id, originMessageId=in_reply_to, trace_id=trace_id)
        if matches:
            logger.info("ticket resolved via in-reply-to traceId=%s inReplyTo=%s ticketId=%s",
                        trace_id, in_reply_to, matches[0]["id"])
            return {"id": matches[0]["id"], "ticketNumber": matches[0].get("ticket_number")}

    referenced = extract_ticket_number(subject) or extract_ticket_number(raw_text)
    if referenced:
        matches = await db.list_tickets(tenant_id, ticketNumber=referenced, trace_id=trace_id)
        if matches:
            logger.info("ticket resolved via explicit reference traceId=%s ticketNumber=%s ticketId=%s",
                        trace_id, referenced, matches[0]["id"])
            return {"id": matches[0]["id"], "ticketNumber": matches[0].get("ticket_number")}
        logger.warning("message referenced unknown ticket traceId=%s ticketNumber=%s — treating as new",
                        trace_id, referenced)

    if channel_identity_value:
        identity = await _find_identity_for_channel(
            db, tenant_id, channel_identity_type, channel_identity_value, trace_id=trace_id)
        if identity and identity.get("master_id"):
            open_tickets = await db.list_tickets(
                tenant_id, identityId=identity["master_id"], status=OPEN_STATUSES,
                sortBy="createdAt", sortDir="desc", trace_id=trace_id)
            # Feature 20: an intake answer belongs to the stub that ASKED for
            # it, full stop — before any count or topic reasoning. A stub with
            # no category has never had a complaint filed on it, so it is by
            # definition still mid-intake; when exactly one such stub is open,
            # there is no ambiguity about which conversation this answers.
            # Checked even when several tickets are open, so a thread already
            # split by this bug self-heals on the citizen's next reply instead
            # of shedding another ticket per message.
            intake_stubs = [t for t in open_tickets if not t.get("category")]
            if len(intake_stubs) == 1 and looks_like_intake_answer(raw_text):
                logger.info(
                    "ticket resolved via in-intake stub (message is intake-form data, not a new "
                    "complaint) traceId=%s ticketId=%s openTickets=%d",
                    trace_id, intake_stubs[0]["id"], len(open_tickets),
                )
                return {"id": intake_stubs[0]["id"], "ticketNumber": intake_stubs[0].get("ticket_number")}
            if open_tickets:
                resolved = await _match_against_open_tickets(
                    db, tenant_id, thread_key, channel, open_tickets, raw_text,
                    origin_message_id, trace_id)
                if resolved is not None:
                    return resolved
            # Exactly zero open tickets linked to this identity — fall
            # through to the thread-key check below (safety net for a
            # ticket that hasn't been linked to the identity yet, e.g.
            # still on its very first turn).

    existing = await db.list_tickets(tenant_id, threadId=thread_key, status=OPEN_STATUSES, trace_id=trace_id)
    if existing:
        return {"id": existing[0]["id"], "ticketNumber": existing[0].get("ticket_number")}

    return await _create_stub(db, tenant_id, thread_key, channel, origin_message_id, trace_id)


async def _match_against_open_tickets(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str, open_tickets: list[dict],
    raw_text: Optional[str], origin_message_id: Optional[str], trace_id: Optional[str],
) -> Optional[dict]:
    """Decide, in ONE judgment, which of the citizen's open tickets this
    message continues (Feature 22).

    Returns the resolved stub, or ``None`` to let the caller fall through to
    the thread-key check and, ultimately, a fresh stub.

    Replaces the Feature 17/18 count-based rules, which could only reason when
    exactly ONE ticket was open and otherwise gave up ("2+ open, don't
    guess" → always a new ticket). That gap is what produced the reported
    email case: a stale unconfirmed stub was still open, so the second email
    never reached the topic check at all. Asking the model to pick from the
    citizen's open complaints handles one and many identically.

    Three outcomes:
    - ``same``    → route to that ticket; it is the same complaint.
    - ``unclear`` → create a NEW stub, but carry `suspectedDuplicateOf` so the
      conversation asks the citizen rather than a heuristic guessing. Nothing
      is merged until they say so, so the wrong answer here costs an extra
      question, never a swallowed complaint.
    - ``different``/no match → ``None``; this is a new complaint.
    """
    candidates = []
    for ticket in open_tickets[:_MAX_MATCH_CANDIDATES]:
        text = await _existing_complaint_text(db, ticket["id"], trace_id)
        if text:
            candidates.append({"ticket": ticket, "ticketNumber": ticket.get("ticket_number"),
                               "text": text, "category": ticket.get("category")})
    if not candidates:
        # No fetchable complaint text to compare against (a brand-new stub
        # whose first message hasn't been persisted yet). Keep the pre-Feature
        # 22 behaviour so the narrow first-turn window is unchanged: WhatsApp
        # appends to a sole open ticket, email starts a new one.
        if channel != "email" and len(open_tickets) == 1:
            return {"id": open_tickets[0]["id"], "ticketNumber": open_tickets[0].get("ticket_number")}
        return None

    match = await match_open_ticket(
        [{"ticketNumber": c["ticketNumber"], "text": c["text"], "category": c["category"]} for c in candidates],
        raw_text or "")

    if match is None:
        # The judgment itself was unavailable (no key, timeout, bad response) —
        # a network condition, not a decision about this message. Fall back to
        # each channel's long-standing default rather than inventing one:
        # WhatsApp's stable per-phone thread means "append" is safe there,
        # while a fresh email has always been its own complaint.
        logger.info("open-ticket match unavailable traceId=%s channel=%s — using channel default",
                    trace_id, channel)
        if channel != "email" and len(open_tickets) == 1:
            return {"id": open_tickets[0]["id"], "ticketNumber": open_tickets[0].get("ticket_number")}
        return None

    verdict, index = match["verdict"], match["index"]
    if index is None or verdict == "different":
        logger.info("no open ticket matches this message traceId=%s verdict=%s reason=%s",
                    trace_id, verdict, match.get("reason"))
        return None

    chosen = candidates[index]["ticket"]
    if verdict == "same":
        logger.info("ticket resolved via open-ticket match traceId=%s ticketId=%s reason=%s",
                    trace_id, chosen["id"], match.get("reason"))
        return {"id": chosen["id"], "ticketNumber": chosen.get("ticket_number")}

    # unclear — create the ticket, flag the suspicion, and let the citizen settle it.
    logger.info(
        "possible duplicate of ticketId=%s but the message is ambiguous — creating a new ticket "
        "and asking the citizen traceId=%s reason=%s",
        chosen["id"], trace_id, match.get("reason"),
    )
    stub = await _create_stub(db, tenant_id, thread_key, channel, origin_message_id, trace_id)
    stub["suspectedDuplicateOf"] = {
        "id": chosen["id"],
        "ticketNumber": chosen.get("ticket_number"),
        "summary": candidates[index]["text"][:300],
    }
    # Record the suspicion on the ticket itself, not just in the conversation
    # turn. The citizen may never answer the question — they often don't — and
    # without this the flag would live only in Valkey state that expires in two
    # hours, leaving an agent looking at two tickets with no indication they
    # might be the same complaint. Best-effort: routing must not fail over an
    # audit write.
    try:
        await db.add_event(stub["id"], {
            "eventType": "ticket.possible_duplicate",
            "actorType": "ai",
            "meta": {
                "duplicateOfId": chosen["id"],
                "duplicateOfNumber": chosen.get("ticket_number"),
                "reason": match.get("reason"),
            },
        }, trace_id=trace_id)
    except Exception:  # noqa: BLE001 - see above
        logger.warning("failed to record possible-duplicate event traceId=%s ticketId=%s",
                        trace_id, stub["id"])
    return stub


async def _existing_complaint_text(db: DbWriterClient, ticket_id: str, trace_id: Optional[str]) -> Optional[str]:
    """The ticket's ORIGINAL complaint text (its first inbound message) —
    the "existing complaint" side of the same-topic comparison above.
    Best-effort: any failure just means the comparison is skipped (falls
    back to the safe "same topic" default in the caller), never blocks
    ticket routing over a message-history fetch problem."""
    try:
        messages = await db.get_messages(ticket_id, trace_id=trace_id)
        inbound = [m for m in messages if m.get("direction") == "inbound" and m.get("content")]
    except Exception:  # noqa: BLE001 - best-effort, see docstring
        return None
    return inbound[0]["content"] if inbound else None


async def _create_stub(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str,
    origin_message_id: Optional[str], trace_id: Optional[str],
) -> dict:
    ticket = await db.create_ticket({
        "tenantId": tenant_id,
        "threadId": thread_key,
        "channelOrigin": channel,
        "identityStatus": "pending",
        "status": "open",
        "originMessageId": origin_message_id,
    }, trace_id=trace_id)
    logger.info("ticket stub created traceId=%s threadId=%s ticketId=%s ticketNumber=%s",
                trace_id, thread_key, ticket.get("id"), ticket.get("ticketNumber"))
    return {"id": ticket["id"], "ticketNumber": ticket.get("ticketNumber")}


async def update_ticket_identity(
    db: DbWriterClient, ticket_id: str, master_id: Optional[str], identity_status: str,
    trace_id: Optional[str] = None, extra_fields: Optional[dict] = None,
) -> None:
    """Reflect identity resolution onto the stub immediately — this is what
    moves a ticket out of the Unconfirmed queue as soon as identity confirms,
    independent of whether complaint details are ready yet.

    `extra_fields` carries any other ticket column the same turn has learned
    (Feature 20: the Service/Customer ID). Those used to be written only when
    the complaint was finally submitted, so a citizen stuck on one bad field
    — a mistyped email, say — left an intake reply whose other, perfectly
    good answers were visible nowhere: not on the ticket, not to an agent
    looking at the Unconfirmed queue, and gone entirely if conversation state
    expired before they replied again."""
    payload = {
        "identityId": master_id,
        "identityStatus": identity_status,
        **(extra_fields or {}),
    }
    await db.update_ticket(ticket_id, payload, trace_id=trace_id)
    logger.info("ticket identity updated traceId=%s ticketId=%s identityStatus=%s masterId=%s extra=%s",
                trace_id, ticket_id, identity_status, master_id, sorted(extra_fields or {}))
