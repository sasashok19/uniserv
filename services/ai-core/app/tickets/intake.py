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
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.classify.message_intent import assess_inbound
from app.classify.message_quality import FALLBACK_DUPLICATE_QUESTION, match_open_ticket
from app.classify.text_cleanup import strip_quoted_reply
from app.config import settings
from app.dedup import confirmation
from app.dedup.service import ADDRESSABLE_STATUSES, OPEN_STATUSES, TERMINAL_STATUSES
from app.identity.db_client import DbWriterClient

logger = logging.getLogger("ai-core")

TICKET_NUMBER_RE = re.compile(r"TKT-\d{4,}")

# How many of the citizen's open tickets are put to the model at once. They
# arrive newest-first, so this bounds prompt size (and cost) on an account with
# a long tail of stale open tickets without affecting the realistic cases.
_MAX_MATCH_CANDIDATES = 8

# How far back to look for "have we already asked this contact to clarify?".
# Independent of the reply window: that one bounds attribution, this one bounds
# how long a citizen stays exempt from being asked the same thing twice.
_ESCALATION_LOOKBACK_DAYS = 7

# Sent when a message cannot be attributed and does not read as a complaint
# (routing rung 5). It has to do two jobs at once, because we genuinely do not
# know which case this is: give them a way to reach the right ticket, and a way
# to start a new one.
ASK_FOR_REFERENCE = (
    "Thanks for your message. We couldn't tell which complaint this is about. "
    "If you're replying about an existing complaint, please send us its ticket "
    "number (it looks like TKT-00123). If this is a new problem, please describe "
    "what's wrong — for example \"no power in Anna Nagar since Tuesday\" — and "
    "we'll register it for you."
)

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


# Whole-message greetings and sign-offs, in the languages this deployment
# actually sees. Matched against the ENTIRE message, so "hi, my power is out"
# is a complaint and only "hi" is a pleasantry.
_PLEASANTRY = frozenset({
    "hi", "hii", "hiii", "hello", "helo", "hey", "yo",
    "good morning", "good afternoon", "good evening", "good day",
    "thanks", "thank you", "thanks a lot", "thank u", "thx", "ty",
    "ok", "okay", "k", "kk", "fine", "cool", "great", "nice",
    "bye", "goodbye", "see you", "welcome",
    "vanakkam", "nandri", "namaste", "namaskaram", "shukriya", "dhanyavad",
})


def looks_like_pleasantry(text: Optional[str]) -> bool:
    """Is the WHOLE message just a greeting or a thank-you?

    Deterministic and deliberately narrow — no LLM, no fuzzy matching. A false
    positive here silently drops something a citizen wrote, so the rule is that
    the entire message, stripped of punctuation and emoji-free padding, has to
    be one of a short list.
    """
    stripped = (text or "").strip().lower()
    if not stripped or len(stripped) > 20:
        return False
    stripped = stripped.strip(" .!?,;:-\u2026")
    return stripped in _PLEASANTRY


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


def _cutoff(days: int) -> str:
    """A `SqliteTime`-format timestamp `days` ago, for string comparison against
    stored `created_at` values (db-writer writes `yyyy-MM-dd HH:mm:ss` UTC, which
    sorts lexicographically)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _reply_window_days(tenant_config: dict) -> int:
    """How long a bare reply may still be attributed to a ticket (Feature 24).
    Tenant setting wins over the service default; a nonsensical value is
    ignored rather than allowed to disable attribution entirely."""
    raw = ((tenant_config or {}).get("generalSettings") or {}).get("replyWindowDays")
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return settings.reply_window_days
    return days if days > 0 else settings.reply_window_days


async def _ticket_dialogue(
    db: DbWriterClient, ticket_id: str, trace_id: Optional[str],
) -> tuple[Optional[str], Optional[dict]]:
    """`(the citizen's original complaint, the last message we sent)` for one
    ticket, from a single message-timeline fetch.

    Both halves come from the same call on purpose: routing needs the complaint
    to tell tickets apart AND the last outbound to judge whether this message
    answers it, and a dedicated endpoint per half would double the round trips
    per candidate to save nothing. Best-effort — a fetch failure just means this
    ticket contributes no candidate, never that routing fails.
    """
    try:
        messages = await db.get_messages(ticket_id, trace_id=trace_id)
    except Exception:  # noqa: BLE001 - see docstring
        return None, None
    inbound = [m for m in messages if m.get("direction") == "inbound" and m.get("content")]
    outbound = [m for m in messages if m.get("direction") == "outbound" and m.get("content")]
    return (inbound[0]["content"] if inbound else None), (outbound[-1] if outbound else None)


async def _resolve_by_reply_to(
    db: DbWriterClient, tenant_id: str, in_reply_to: str, trace_id: Optional[str],
) -> Optional[dict]:
    """The ticket the message being replied to lives on (routing rung 0).

    Two lookups, because there are two kinds of message a citizen can reply to:

    - one of OURS (Feature 24) — the reply-to id matches the `channel_message_id`
      we recorded when we sent it. This is the case that matters and the one that
      was missing: "Is this resolved?" -> "Yes it is" resolves here, exactly,
      with no interpretation.
    - the ticket's OWN first inbound message (Feature 19) — the citizen
      swipe-replied to their original complaint.
    """
    message = await db.find_message_by_channel_id(tenant_id, in_reply_to, trace_id=trace_id)
    if message and message.get("ticket_id"):
        ticket = await db.get_ticket(message["ticket_id"], trace_id=trace_id)
        if ticket and ticket.get("id"):
            logger.info("ticket resolved via reply to our own message traceId=%s ticketId=%s",
                        trace_id, ticket["id"])
            return ticket
    matches = await db.list_tickets(tenant_id, originMessageId=in_reply_to, trace_id=trace_id)
    if matches:
        logger.info("ticket resolved via reply to the original complaint traceId=%s ticketId=%s",
                    trace_id, matches[0]["id"])
        return matches[0]
    return None


async def _resolve_by_reference(
    db: DbWriterClient, tenant_id: str, subject: Optional[str], raw_text: Optional[str],
    trace_id: Optional[str],
) -> Optional[dict]:
    """The ticket a `TKT-XXXXX` the citizen typed refers to (routing rung 1)."""
    referenced = extract_ticket_number(subject) or extract_ticket_number(raw_text)
    if not referenced:
        return None
    matches = await db.list_tickets(tenant_id, ticketNumber=referenced, trace_id=trace_id)
    if matches:
        logger.info("ticket resolved via explicit reference traceId=%s ticketNumber=%s ticketId=%s",
                    trace_id, referenced, matches[0]["id"])
        return matches[0]
    logger.warning("message referenced unknown ticket traceId=%s ticketNumber=%s — ignoring the reference",
                    trace_id, referenced)
    return None


async def _resolved(
    db: DbWriterClient, ticket: dict, trace_id: Optional[str], via: str,
) -> dict:
    """Package a resolved ticket, noting in its audit trail when a citizen has
    written to a ticket that was already finished (Feature 24).

    The status is deliberately NOT changed. A reply on a resolved ticket may be
    "yes, thanks" or "no, it is still broken", and only a human should decide
    which of those reopens work — an automatic reopen on the wrong reading would
    churn the backlog, and an automatic close on the wrong reading would bury a
    live complaint.
    """
    if (ticket.get("status") or "") in TERMINAL_STATUSES:
        try:
            await db.add_event(ticket["id"], {
                "eventType": "ticket.reply_after_resolution",
                "actorType": "system",
                "meta": {"status": ticket.get("status"), "via": via},
            }, trace_id=trace_id)
        except Exception:  # noqa: BLE001 - best-effort audit, never blocks routing
            logger.warning("failed to record reply-after-resolution traceId=%s ticketId=%s",
                           trace_id, ticket.get("id"))
    return {"id": ticket["id"], "ticketNumber": ticket.get("ticket_number")}


async def ensure_ticket_stub(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str,
    subject: Optional[str] = None, raw_text: Optional[str] = None,
    channel_identity_type: Optional[str] = None, channel_identity_value: Optional[str] = None,
    origin_message_id: Optional[str] = None, in_reply_to: Optional[str] = None,
    trace_id: Optional[str] = None, explicit_new_complaint: bool = False,
) -> dict:
    """Find the ticket this message belongs to, create a stub, or decline to do
    either (Feature 24).

    Returns ``{"id", "ticketNumber"}`` for a resolved/created ticket — plus
    ``suspectedDuplicateOf`` when the duplicate question needs asking — or
    ``{"unrouted": True, "ask": <text|None>}`` with NO ``id`` when no ticket
    could be attributed and inventing one would be wrong. Callers must check for
    an ``id`` before using it.

    The ladder, strongest signal first. Rungs 0-1 and 3 are free; rungs 2 and 4
    are ONE shared LLM call; nothing is ever guessed.

    0. **The message they replied to.** A WhatsApp swipe-reply's `context.id` or
       an email `In-Reply-To`, matched against the `channel_message_id` of a
       message WE sent (Feature 24) or a ticket's own original inbound message
       (Feature 19). Exact and interpretation-free.
    1. **A `TKT-XXXXX` the citizen typed.** Ranked ABOVE rung 0 deliberately:
       replying to a message is often just "the last thread in my app", whereas
       typing a ticket number is an unambiguous statement of intent. When the two
       disagree the typed reference wins and the disagreement is logged.
    2. **An answer to something we asked.** The judgment that was missing, and
       the reason a citizen's "Yes it is" landed on an unrelated ticket: every
       previous check compared the message against ticket COMPLAINT text, and a
       bare confirmation contains none. Candidates are the last outbound message
       on each of the citizen's tickets in any status, within the reply window —
       so an answer to "Is this resolved?" reaches a resolved ticket instead of
       being excluded from routing entirely.
    3. **An intake-form answer**, but only when the last thing we asked on that
       stub actually WAS an intake question. A bare "yes" is structurally
       identical whether it answers "did you mean x@gmail.com?" or "is this
       fixed?", and this guard used to claim either for whichever stub happened
       to be mid-intake.
    4. **A new complaint.** Coherent, and describing a problem — from the same
       call as rung 2. Runs the Feature 22 duplicate check before creating,
       so "the same complaint again" still asks rather than duplicating.
    5. **None of the above.** No ticket is created. The message is parked for a
       lead (`unrouted_messages`) and the citizen is asked which complaint they
       mean; a second unroutable message escalates instead of asking again.
       Storing it is the point — a dropped message is invisible to everyone,
       which is worse than a misroute an agent can fix.
    """
    # What the citizen typed THIS time, with our own quoted message and their
    # signature removed. Only ever used for judgments; the raw text is what gets
    # persisted, and an email reply otherwise arrives containing our question and
    # their original complaint, which would make rungs 2 and 4 answer yes to
    # almost anything.
    clean_text = strip_quoted_reply(raw_text)

    # --- Rung -1: the answer to a duplicate question we asked (Feature 26) ---
    #
    # Above everything, because this answer routes nowhere else. "Madambakkam"
    # names no ticket, replies to no message, answers no question recorded
    # against a ticket (none exists yet — that is the point), and reads as no
    # complaint. Every other rung would decline it and rung 5 would park it,
    # losing both the answer and the complaint it was about.
    pending = await confirmation.load_pending(tenant_id, thread_key)
    if pending:
        resolved = await _resolve_pending_duplicate(
            db, tenant_id, thread_key, channel, pending, clean_text, raw_text,
            origin_message_id, trace_id)
        if resolved is not None:
            return resolved

    reference_ticket = await _resolve_by_reference(db, tenant_id, subject, raw_text, trace_id)
    reply_ticket = await _resolve_by_reply_to(db, tenant_id, in_reply_to, trace_id) if in_reply_to else None

    if reference_ticket and reply_ticket and reference_ticket["id"] != reply_ticket["id"]:
        logger.warning(
            "routing signals disagree traceId=%s typedReference=%s replyTo=%s — the typed "
            "reference wins (a deliberate citizen action beats which thread they replied in)",
            trace_id, reference_ticket.get("ticket_number"), reply_ticket.get("ticket_number"))
    chosen = reference_ticket or reply_ticket
    if chosen:
        return await _resolved(db, chosen, trace_id,
                               "reference" if reference_ticket else "reply-to")

    # Everything below needs to know which tickets are this citizen's.
    identity = None
    if channel_identity_value:
        identity = await _find_identity_for_channel(
            db, tenant_id, channel_identity_type, channel_identity_value, trace_id=trace_id)
    master_id = (identity or {}).get("master_id")

    tickets: list[dict] = []
    if master_id:
        tickets = await db.list_tickets(
            tenant_id, identityId=master_id, status=ADDRESSABLE_STATUSES,
            sortBy="createdAt", sortDir="desc", trace_id=trace_id)
    if not tickets:
        # Identity hasn't linked to a ticket yet (the narrow first-turn window).
        # The thread key is a per-conversation id for email and a per-phone one
        # for WhatsApp, so it is a safety net here rather than a primary signal.
        tickets = await db.list_tickets(
            tenant_id, threadId=thread_key, status=ADDRESSABLE_STATUSES, trace_id=trace_id)

    if not tickets:
        # Nothing of theirs exists. This is the genuinely-first-contact case, and
        # the only question is whether the message is a complaint at all — "Hi"
        # must not become a ticket.
        return await _first_contact(
            db, tenant_id, thread_key, channel, clean_text, raw_text,
            channel_identity_value, origin_message_id, in_reply_to, trace_id)

    tenant_config = await db.get_tenant_config(tenant_id, trace_id=trace_id)
    window_cutoff = _cutoff(_reply_window_days(tenant_config))

    # One timeline fetch per candidate gives both halves of the context.
    dialogues: list[dict] = []
    for ticket in tickets[:_MAX_MATCH_CANDIDATES]:
        complaint, last_outbound = await _ticket_dialogue(db, ticket["id"], trace_id)
        dialogues.append({"ticket": ticket, "complaint": complaint, "lastOutbound": last_outbound})

    # --- Rung 2: is this an answer to something we asked? ------------------
    questions = [
        d for d in dialogues
        if d["lastOutbound"] and (d["lastOutbound"].get("created_at") or "") >= window_cutoff
    ]
    intent = await assess_inbound(
        [{"ticketNumber": d["ticket"].get("ticket_number"), "status": d["ticket"].get("status"),
          "question": d["lastOutbound"].get("content"), "complaint": d["complaint"]}
         for d in questions],
        clean_text, trace_id=trace_id)

    if intent is None:
        # The judgment itself was unavailable — a network condition, not a
        # decision about this message. Deliberately NOT a guess: fall back to
        # the structural rungs only, and ask the citizen if those decline.
        logger.info("inbound intent unavailable traceId=%s — structural rungs only", trace_id)
        return await _route_without_llm(
            db, tenant_id, thread_key, channel, dialogues, clean_text, raw_text,
            channel_identity_value, origin_message_id, in_reply_to, window_cutoff, trace_id)

    if intent["index"] is not None and not explicit_new_complaint:
        answered = questions[intent["index"]]["ticket"]
        logger.info("ticket resolved as an answer to our own question traceId=%s ticketId=%s status=%s "
                    "reason=%s", trace_id, answered["id"], answered.get("status"), intent["reason"])
        resolved = await _resolved(db, answered, trace_id, "answer-to-our-question")
        # Carry WHAT we asked, not just which ticket it was on. Without it the
        # assistant knows the message belongs here but not that it is an answer,
        # and replies "please let me know what problem you are reporting" to
        # someone who has just answered the agent's question (live-reported).
        last_outbound = questions[intent["index"]].get("lastOutbound") or {}
        resolved["answersQuestion"] = last_outbound.get("content")
        return resolved
    if intent["index"] is not None:
        # The citizen pressed "register a new ticket" and then described it, so
        # they have already told us this is not a reply. Rung 2 guesses; they
        # stated. An outstanding agent question on an older ticket must not
        # swallow a brand-new complaint (live failure: a water-logging report
        # filed onto a voltage-fluctuation ticket that had an open
        # "Is this resolved?" against it).
        logger.info("rung 2 matched ticketId=%s but the citizen explicitly chose a NEW ticket "
                    "traceId=%s — ignoring the match",
                    questions[intent["index"]]["ticket"]["id"], trace_id)

    # --- Rung 3: an intake answer, to a stub that actually asked one -------
    intake_stub = _in_intake_stub(dialogues, clean_text, window_cutoff)
    if intake_stub is not None:
        logger.info("ticket resolved via in-intake stub traceId=%s ticketId=%s", trace_id, intake_stub["id"])
        return await _resolved(db, intake_stub, trace_id, "intake-answer")

    # --- Rung 4: a new complaint ------------------------------------------
    #
    # `explicit_new_complaint` counts here as well as suppressing rung 2. The
    # citizen pressed "register a new ticket", so this conversation MUST end in
    # a ticket — falling through to rung 5 would park their words in a queue and
    # tell them nothing, which is exactly what happened live: they said "No it
    # is for a different area", `is_new_complaint` was False (a clarification is
    # not itself a complaint description), rung 2 was suppressed, and the reply
    # was silence. Having told us it is new, they get a ticket; the duplicate
    # check below still runs and still asks which area first.
    if intent["is_new_complaint"] or explicit_new_complaint:
        if not intent["is_new_complaint"]:
            logger.info("not read as a new complaint, but the citizen chose a NEW ticket "
                        "traceId=%s — creating rather than parking", trace_id)
        open_tickets = [d["ticket"] for d in dialogues
                        if (d["ticket"].get("status") or "") not in TERMINAL_STATUSES]
        if open_tickets:
            resolved = await _match_against_open_tickets(
                db, tenant_id, thread_key, channel, open_tickets, clean_text,
                origin_message_id, trace_id, tenant_config)
            if resolved is not None:
                return resolved
        return await _create_stub(db, tenant_id, thread_key, channel, origin_message_id, trace_id)

    # --- Rung 5: unattributable, and not a complaint -----------------------
    #
    # A bare greeting is not a complaint anyone can lose. The unrouted queue
    # exists because "a dropped message is invisible to everyone, which is worse
    # than a misroute" — that reasoning applies to a citizen's WORDS, and "Hi"
    # has none to preserve. Parking them fills a lead's queue with items that
    # can only ever be discarded (live-reported: two "Hi" messages sitting in it).
    # They still get a reply; they just leave no work behind.
    if looks_like_pleasantry(clean_text):
        logger.info("pleasantry not parked as unrouted traceId=%s", trace_id)
        return {"unrouted": True, "parked": False, "ask": ASK_FOR_REFERENCE}

    return await _park_unrouted(
        db, tenant_id, channel, clean_text, raw_text, channel_identity_value,
        in_reply_to, intent["reason"] or "not an answer to anything we asked, and not a complaint",
        trace_id)


def _in_intake_stub(dialogues: list[dict], clean_text: str, window_cutoff: str) -> Optional[dict]:
    """The stub this intake-form answer belongs to, if exactly one qualifies
    (routing rung 3).

    Two conditions, both required. The ticket must still be mid-intake (no
    `category` — no complaint has been filed on it), and the last thing we sent
    on it must have actually BEEN an intake request. The second is new in
    Feature 24 and is what stopped this rung from swallowing every bare "yes":
    `looks_like_intake_answer` cannot tell "yes, that's my email" from "yes, it
    is resolved", so it may only be trusted where an intake question was asked.
    """
    candidates = []
    for d in dialogues:
        outbound = d["lastOutbound"]
        if d["ticket"].get("category"):
            continue
        if not outbound or not outbound.get("is_intake_request"):
            continue
        if (outbound.get("created_at") or "") < window_cutoff:
            continue
        candidates.append(d["ticket"])
    if len(candidates) == 1 and looks_like_intake_answer(clean_text):
        return candidates[0]
    return None


async def _first_contact(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str,
    clean_text: str, raw_text: Optional[str], channel_identity_value: Optional[str],
    origin_message_id: Optional[str], in_reply_to: Optional[str], trace_id: Optional[str],
) -> dict:
    """This contact has no tickets at all. Create one only if they have actually
    reported something.

    The user's rule was "first message, no check needed" — softened here for one
    reason: "Hi", "Hello?" and "Is anyone there" are common openers, and each
    would otherwise become a permanent ticket that reporting has to explain
    forever. When the LLM is unreachable we DO create the ticket regardless: a
    lost first complaint is much worse than a junk row, and that is the
    long-standing bias everywhere in this pipeline.
    """
    intent = await assess_inbound([], clean_text, trace_id=trace_id)
    if intent is not None and not intent["is_new_complaint"]:
        logger.info("first contact is not a complaint traceId=%s reason=%s", trace_id, intent["reason"])
        return await _park_unrouted(
            db, tenant_id, channel, clean_text, raw_text, channel_identity_value,
            in_reply_to, intent["reason"] or "first message from this contact is not a complaint",
            trace_id)
    return await _create_stub(db, tenant_id, thread_key, channel, origin_message_id, trace_id)


async def _route_without_llm(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str, dialogues: list[dict],
    clean_text: str, raw_text: Optional[str], channel_identity_value: Optional[str],
    origin_message_id: Optional[str], in_reply_to: Optional[str], window_cutoff: str,
    trace_id: Optional[str],
) -> dict:
    """Routing with the LLM unavailable: structural rungs only, then ask.

    The pre-Feature-24 fallbacks (WhatsApp appends to a sole open ticket, email
    starts a new one) were themselves guesses, and one of them is precisely how
    the reported misroute happened. So an outage now costs a clarifying question
    rather than a wrong attribution — EXCEPT where a structural signal still
    stands on its own: an intake answer to a stub that asked an intake question
    needs no judgment, and a message that reads like a complaint by the
    deterministic test still opens a ticket rather than being held.
    """
    intake_stub = _in_intake_stub(dialogues, clean_text, window_cutoff)
    if intake_stub is not None:
        return await _resolved(db, intake_stub, trace_id, "intake-answer")
    # `looks_like_intake_answer` doubles as a serviceable "this is not prose"
    # test: anything it accepts is a bare name, identifier or acknowledgement,
    # none of which is a complaint.
    if looks_like_intake_answer(clean_text):
        return await _park_unrouted(
            db, tenant_id, channel, clean_text, raw_text, channel_identity_value,
            in_reply_to, "could not assess this message (AI unavailable) and it carries no complaint text",
            trace_id)
    return await _create_stub(db, tenant_id, thread_key, channel, origin_message_id, trace_id)


async def _park_unrouted(
    db: DbWriterClient, tenant_id: str, channel: str, clean_text: str, raw_text: Optional[str],
    channel_identity_value: Optional[str], in_reply_to: Optional[str], reason: str,
    trace_id: Optional[str],
) -> dict:
    """Routing rung 5: store the message, create no ticket, and tell the caller
    what to say back.

    `ask` is the reply to send the citizen, or ``None`` when we have already
    asked this contact once — the second unroutable message escalates instead,
    so a citizen who answers "I don't have it" is never trapped in a loop.
    """
    escalate = False
    if channel_identity_value:
        asked = await db.unrouted_ask_count(
            tenant_id, channel_identity_value, _cutoff(_ESCALATION_LOOKBACK_DAYS), trace_id=trace_id)
        escalate = asked > 0

    parked = None
    try:
        parked = await db.create_unrouted_message({
            "tenantId": tenant_id,
            "channel": channel,
            "channelIdentityValue": channel_identity_value,
            # The RAW text, not the stripped one: an agent resolving this needs
            # exactly what the citizen sent, quotes and all.
            "content": raw_text or clean_text,
            "channelMessageId": in_reply_to,
            "reason": reason,
            "status": "escalated" if escalate else "pending",
            "askCount": 0 if escalate else 1,
        }, trace_id=trace_id)
    except Exception:  # noqa: BLE001 - see below
        # Even this failing must not raise: the alternative is an unhandled
        # error on the citizen's message. It is logged loudly because a message
        # that reaches neither a ticket nor this queue is genuinely lost.
        logger.error("UNROUTED MESSAGE COULD NOT BE STORED traceId=%s channel=%s reason=%s text=%r",
                     trace_id, channel, reason, (raw_text or clean_text)[:200])

    logger.info("message not attributable to any ticket traceId=%s escalated=%s reason=%s",
                trace_id, escalate, reason)
    return {
        "unrouted": True,
        "unroutedId": (parked or {}).get("id"),
        "escalated": escalate,
        "reason": reason,
        "ask": None if escalate else ASK_FOR_REFERENCE,
    }


async def _match_against_open_tickets(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str, open_tickets: list[dict],
    raw_text: Optional[str], origin_message_id: Optional[str], trace_id: Optional[str],
    tenant_config: Optional[dict] = None,
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

    # unclear — Feature 26: ASK FIRST, create nothing.
    #
    # This used to create the ticket immediately and ask afterwards, which meant
    # an open "Power Cut in Madambakkam" plus a bare "Power cut" produced two
    # rows from the first message and only merged if the citizen replied. The
    # question now comes first and the citizen's words are held in Valkey until
    # they answer (app/dedup/confirmation.py). Exactly one round: an answer that
    # is still ambiguous falls through to create-and-flag, so nobody's complaint
    # can be trapped in a loop.
    summary = candidates[index]["text"][:300]
    question = match.get("question") or FALLBACK_DUPLICATE_QUESTION
    logger.info(
        "possible duplicate of ticketId=%s and the message is ambiguous — asking the citizen "
        "BEFORE creating anything traceId=%s reason=%s",
        chosen["id"], trace_id, match.get("reason"),
    )
    pending = confirmation.as_pending(raw_text or "", chosen, summary, question)
    await confirmation.save_pending(tenant_id, thread_key, pending)
    return {
        "awaitingDuplicateConfirmation": True,
        "ask": confirmation.build_question(
            _menu_copy(tenant_config, channel), pending["duplicateOf"], question),
        "duplicateOf": pending["duplicateOf"],
    }


async def _resolve_pending_duplicate(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str, pending: dict,
    clean_text: Optional[str], raw_text: Optional[str], origin_message_id: Optional[str],
    trace_id: Optional[str],
) -> Optional[dict]:
    """Turn the citizen's answer into a routing decision (Feature 26, rung -1).

    Returns None only when the confirmation state was unusable, in which case
    the caller carries on down the normal ladder rather than losing the message.
    """
    duplicate_of = pending.get("duplicateOf") or {}
    if not duplicate_of.get("id"):
        await confirmation.clear_pending(tenant_id, thread_key)
        return None

    outcome = await confirmation.resolve(
        db, tenant_id, thread_key, pending, clean_text, trace_id=trace_id)
    await confirmation.clear_pending(tenant_id, thread_key)

    if outcome["outcome"] == "same":
        # No ticket is created — this is the whole point of the feature. The
        # citizen's words go onto the ticket they confirmed.
        attached = await confirmation.attach_to_existing(
            db, tenant_id, outcome["ticketId"], channel,
            f"{pending.get('text') or ''}\n{raw_text or ''}".strip(), trace_id=trace_id)
        return {
            "duplicateResolved": "same",
            "id": outcome["ticketId"],
            "ticketNumber": outcome.get("ticketNumber"),
            "attached": attached,
        }

    if outcome["outcome"] == "different":
        stub = await _create_stub(db, tenant_id, thread_key, channel, origin_message_id, trace_id)
        stub["duplicateResolved"] = "different"
        stub["pendingText"] = outcome.get("text")
        return stub

    # Still unclear after one round: create and flag, as Feature 22 did.
    stub = await _create_flagged_stub(
        db, tenant_id, thread_key, channel, origin_message_id,
        duplicate_of["id"], duplicate_of.get("ticketNumber"),
        duplicate_of.get("summary") or "", "ambiguous after one confirmation round", trace_id)
    stub["duplicateResolved"] = "unclear"
    stub["pendingText"] = outcome.get("text")
    return stub


def _menu_copy(tenant_config: Optional[dict], channel: str) -> Optional[dict]:
    """The tenant's WhatsApp menu copy, when this message is on WhatsApp.

    Email has no configurable menu, so it gets ``confirmation.build_question``'s
    plain composition rather than a WhatsApp-shaped template.
    """
    if channel != "whatsapp":
        return None
    from app.conversation import menu_content
    return menu_content.resolve(tenant_config)


async def _create_flagged_stub(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str,
    origin_message_id: Optional[str], chosen_id: str, chosen_number: Optional[str],
    summary: str, reason: Optional[str], trace_id: Optional[str],
) -> dict:
    """Create the stub AND carry the duplicate suspicion (the Feature 22 path).

    Reached only after a confirmation round failed to settle it — see
    ``app/dedup/confirmation.resolve``.
    """
    stub = await _create_stub(db, tenant_id, thread_key, channel, origin_message_id, trace_id)
    stub["suspectedDuplicateOf"] = {
        "id": chosen_id,
        "ticketNumber": chosen_number,
        "summary": summary,
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
                "duplicateOfId": chosen_id,
                "duplicateOfNumber": chosen_number,
                "reason": reason,
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
