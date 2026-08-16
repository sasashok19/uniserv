"""The WhatsApp conversation menu (Feature 26).

Every inbound WhatsApp message goes through this module before anything else.
It is a small, deterministic state machine — no LLM, no heuristics — that owns
what the citizen is currently doing:

    (no session)  --any message-->  MENU          [welcome, by name if we know it]
    MENU  --"update my details"-->  PROFILE       [Name / Email / Main menu]
    MENU  --"ticket status"----->   AWAIT_TICKET_CHOICE  [their tickets, tappable]
                                or  AWAIT_TICKET_ID      [>5: ask for the number]
    MENU  --"new ticket"------->    INTAKE        [hands off to the AI pipeline]
    MENU  --"end chat"--------->    (cleared)     [farewell]
    PROFILE       --"name"-->       AWAIT_NAME
    PROFILE       --"email"-->      AWAIT_EMAIL
    AWAIT_NAME    --text-->         MENU          [saved, or told why not]
    AWAIT_EMAIL   --text-->         MENU          [saved, or invalid / in use]
    AWAIT_TICKET_CHOICE --tap-->    AWAIT_NOTE    [details: status/ETA/updated]
    AWAIT_TICKET_ID --ticket id-->  AWAIT_NOTE    [same]
    AWAIT_NOTE    --any message-->  (cleared)     [note appended to the ticket]
    INTAKE        --ticket filed--> MENU          [one message: details + Main menu]
    any           --"#" or "Main menu"-->  MENU

**Every sub-message carries a way back** (Feature 29). ``#`` always worked, but
it is invisible on a phone: the citizen sees buttons, so the button has to be
there. Anything below the top level is sent with a Main menu option on it.

**Why deterministic rather than prompt-driven.** The status a citizen is told,
and which ticket their note lands on, are facts. Everything here is composed in
code from the ticket row for exactly the reason ``status_lookup`` already gives:
a model that rephrases can rephrase wrongly, and a citizen acting on a
hallucinated status is worse than one who was told nothing.

**Strict, but strict at the top level.** The menu decides which *flow* you are
in. Inside a flow the citizen's text is that flow's input — a ticket ID, a note,
an intake answer — and is not matched against the menu. Only ``#`` pulls out.
This is what keeps the Feature 20 intake exchange working: "Nithya" is an answer
to the form, not an unrecognised menu option.

**A first message is never thrown away.** A citizen who opens with "power cut in
Madambakkam" gets the welcome menu, and their words are held in ``carryOver``
until they press 2 — at which point they are prepended to the intake, so nobody
is made to retype a complaint they already sent.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.conversation import menu_content
from app.conversation.intake_fields import catalog_for_tenant, fields_for_channel, render_field_form
from app.dedup.service import ADDRESSABLE_STATUSES, OPEN_STATUSES
from app.events.client import get_valkey
from app.identity.db_client import DbWriterClient
from app.tickets.intake import _reply_window_days, extract_ticket_number

logger = logging.getLogger("ai-core")

CHANNEL = "whatsapp"

# How many of the citizen's most recent tickets to inspect when deciding whether
# we are waiting on an answer. Bounded because this runs on every message that
# arrives without a session; a citizen with more than a couple of live tickets
# is rare, and the newest is overwhelmingly the one in play.
_AWAITING_REPLY_CANDIDATES = 5

# Meta's interactive limits. Enforced here as well as in the gateway's
# validation: a payload Meta rejects means the citizen gets nothing.
BUTTON_TITLE_MAX = 20
BODY_MAX = 1024
FOOTER_MAX = 60
BUTTON_ID_PREFIX = "menu_"

# Meta's list-message limits (Feature 29). The gateway truncates to these too;
# the reason to know them here is that the ticket list has to decide how many
# tickets fit ALONGSIDE its navigation rows.
LIST_ROWS_MAX = 10
ROW_TITLE_MAX = 24
ROW_DESCRIPTION_MAX = 72

STATE_MENU = "menu"
STATE_PROFILE = "profile"
STATE_AWAIT_NAME = "await_name"
STATE_AWAIT_EMAIL = "await_email"
STATE_AWAIT_TICKET_CHOICE = "await_ticket_choice"
STATE_AWAIT_TICKET_ID = "await_ticket_id"
STATE_AWAIT_NOTE = "await_note"
STATE_INTAKE = "intake"

RETURN_TO_MENU = "#"

# The options, named rather than numbered (Feature 29). Feature 28 called them
# "1".."3"; inserting "update my details" at the top would have renumbered the
# other three, and every stored label, log line and test would have quietly
# changed meaning. The citizen still types 1-4 — see the aliases below.
OPTION_PROFILE = "profile"
OPTION_STATUS = "status"
OPTION_NEW = "new"
OPTION_END = "end"

#: option -> the config key holding its label. Order is the menu's order.
OPTION_LABELS: dict[str, str] = {
    OPTION_PROFILE: "labelProfile",
    OPTION_STATUS: "labelStatus",
    OPTION_NEW: "labelNewTicket",
    OPTION_END: "labelEndChat",
}

# The citizen has more open+resolved tickets than this -> ask for the number
# instead of listing everything. The user set the threshold; a list message
# could hold a couple more, but past a handful "which of these is it?" stops
# being a help and the ID they already have is faster.
TICKET_LIST_THRESHOLD = 5

# What "my tickets" means to a citizen: everything still live, plus the ones we
# have just fixed. `closed` is excluded because the user said so, and
# `cancelled` because a ticket we decided not to act on is not a status anyone
# is waiting on.
LISTED_STATUSES = f"{OPEN_STATUSES},resolved"

# Accepted spellings of each option. WhatsApp citizens type "1." and "1)" as
# often as "1", and an interactive reply arrives as the button or row TITLE
# (see WhatsAppParser), not its number — so the words have to be accepted too or
# the options would be dead.
_OPTION_ALIASES: dict[str, str] = {
    "1": OPTION_PROFILE, "1.": OPTION_PROFILE, "1)": OPTION_PROFILE,
    "one": OPTION_PROFILE, "profile": OPTION_PROFILE, "details": OPTION_PROFILE,
    "2": OPTION_STATUS, "2.": OPTION_STATUS, "2)": OPTION_STATUS,
    "two": OPTION_STATUS, "status": OPTION_STATUS,
    "3": OPTION_NEW, "3.": OPTION_NEW, "3)": OPTION_NEW,
    "three": OPTION_NEW, "register": OPTION_NEW, "new": OPTION_NEW,
    "4": OPTION_END, "4.": OPTION_END, "4)": OPTION_END,
    "four": OPTION_END, "end": OPTION_END, "exit": OPTION_END, "bye": OPTION_END,
}

# Only the local part is checked loosely: the citizen's own inbox is the real
# validator, and a regex strict enough to reject every invalid address also
# rejects real ones.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

NAME_MIN = 2
NAME_MAX = 60


@dataclass
class MenuMessage:
    """One outgoing WhatsApp message.

    ``buttons`` turns it into a Meta *interactive* message — tappable options
    instead of "press 1" — and ``footer`` is the small grey line beneath them.
    Both are ignored by the plain-text path, so a tenant with interactive mode
    off, or a channel that cannot render buttons, still gets a complete message
    from the same object.

    Whether that goes out as reply-buttons or as a list is the ADAPTER's
    decision, not this module's: more than three entries, or any entry carrying
    a ``description``, has to be a list because Meta caps buttons at three. So
    the four-option menu and the ticket list are built here exactly like a
    three-button message, and ``listLabel`` only matters if the adapter picks
    the list shape.
    """

    text: str
    buttons: Optional[list[dict]] = None
    footer: Optional[str] = None
    list_label: Optional[str] = None

    def __str__(self) -> str:  # keeps existing text assertions and logs readable
        return self.text


@dataclass
class MenuOutcome:
    """What the dispatcher should do with this message.

    ``replies`` are sent in order. ``stop`` means the menu has fully handled the
    message and the AI pipeline must not run. When ``stop`` is False the message
    continues into ``ensure_ticket_stub``/``ConversationAgent`` with ``text`` in
    place of the raw text (carry-over merged in).
    """

    replies: list[MenuMessage] = field(default_factory=list)
    stop: bool = True
    text: Optional[str] = None
    #: The citizen pressed "register a new ticket" and is now describing it.
    #: Routing must not quietly file that onto an existing ticket — see
    #: ``ensure_ticket_stub(explicit_new_complaint=...)``.
    explicit_new_complaint: bool = False


# ---------------------------------------------------------------------------
# Session storage
# ---------------------------------------------------------------------------

def _session_key(tenant_id: str, thread_key: str) -> str:
    return f"wamenu:{tenant_id}:{thread_key}"


async def load_session(tenant_id: str, thread_key: str) -> Optional[dict]:
    """The citizen's menu session, or None when there is none (or Valkey is down).

    A read failure deliberately reads as "no session": the citizen then gets the
    welcome menu again, which is a mildly repetitive but completely functional
    conversation. The alternative — treating an unreadable session as some
    assumed state — would file their next message against a flow they are not in.
    """
    try:
        raw = await get_valkey().get(_session_key(tenant_id, thread_key))
    except Exception as exc:  # noqa: BLE001 - session read is best-effort
        logger.warning("failed to load menu session: %s", exc)
        return None
    if not raw:
        return None
    try:
        session = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return session if isinstance(session, dict) else None


async def save_session(tenant_id: str, thread_key: str, session: dict, ttl_hours: int) -> None:
    try:
        await get_valkey().set(
            _session_key(tenant_id, thread_key), json.dumps(session), ex=ttl_hours * 3600)
    except Exception as exc:  # noqa: BLE001 - session persistence is best-effort
        logger.warning("failed to save menu session: %s", exc)


async def clear_session(tenant_id: str, thread_key: str) -> None:
    try:
        await get_valkey().delete(_session_key(tenant_id, thread_key))
    except Exception as exc:  # noqa: BLE001 - session clearing is best-effort
        logger.warning("failed to clear menu session: %s", exc)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_timestamp(raw: Optional[str]) -> Optional[str]:
    """``2026-08-18 23:59:59`` -> ``18 Aug 2026``, for a citizen to read.

    Times are dropped deliberately. Every one of these columns is UTC, the
    citizens are in IST, and "18 Aug 2026, 23:59" would be read as local and be
    wrong by five and a half hours. A date carries the promise honestly; an
    hour we cannot localise does not.
    """
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:len(fmt) + 2].strip(), fmt).strftime("%d %b %Y")
        except ValueError:
            continue
    return text


_STATUS_LABELS = {
    "open": "Open",
    "assigned": "Assigned to an engineer",
    "in_progress": "Work in progress",
    "pending_customer": "Waiting for your reply",
    "resolved": "Resolved",
    "closed": "Closed",
    "reopened": "Reopened",
    "cancelled": "Cancelled",
}


def _status_label(status: Optional[str]) -> str:
    key = (status or "open").strip().lower()
    return _STATUS_LABELS.get(key, key.replace("_", " ").capitalize())


def format_ticket_details(content: dict, ticket: dict, key: str = "ticketDetails") -> str:
    """The one-ticket summary: number, chief complaint, status, ETA, last
    updated. Composed from the row, never paraphrased — see the module docstring.

    The chief complaint (Feature 23) is what the citizen actually reported, in
    one line. Without it a status reply is "TKT-00042 is in progress", which
    means nothing to someone holding three open tickets.
    """
    complaint = (ticket.get("chief_complaint") or ticket.get("chiefComplaint") or "").strip()
    return menu_content.render(
        content, key,
        ticket=ticket.get("ticket_number") or ticket.get("ticketNumber") or "",
        # Falls back rather than rendering a bare "Complaint:" label: a stub
        # still mid-intake, or a ticket predating Feature 23, has none yet.
        complaint=complaint or content.get("complaintUnknown", "not summarised yet"),
        status=_status_label(ticket.get("status")),
        eta=_format_timestamp(ticket.get("eta_at")) or content.get("etaUnknown", "not set yet"),
        updated=_format_timestamp(ticket.get("updated_at")) or "just now",
    )


def _with_hint(content: dict, text: str) -> MenuMessage:
    """Append the "press # for the main menu" line.

    The requirement is that every message carries it. Skipped only when the text
    already contains it — the main-menu message itself ends with the hint, and
    repeating it twice in one send reads as a bug.
    """
    hint = menu_content.render(content, "menuHint")
    if not hint or hint in text:
        return MenuMessage(text)
    return MenuMessage(f"{text}\n\n{hint}")


def _option_entry(content: dict, key: str, option_id: str) -> Optional[dict]:
    """One tappable option, or None when its label is blank.

    Titles are truncated rather than rejected: a label an admin made too long
    should cost a clipped word, not a citizen receiving nothing.
    """
    title = menu_content.render(content, key).strip()
    if not title:
        return None
    return {"id": f"{BUTTON_ID_PREFIX}{option_id}", "title": title[:BUTTON_TITLE_MAX]}


def menu_buttons(content: dict) -> Optional[list[dict]]:
    """The four options as tappable entries, or None for plain text.

    Kept under the Feature 28 name because that is what the dispatcher and the
    tests call it; there are four of them now, so the adapter renders them as a
    list rather than as reply-buttons.
    """
    if not content.get("useInteractiveButtons", True):
        return None
    entries = []
    for option_id, key in OPTION_LABELS.items():
        entry = _option_entry(content, key, option_id)
        if entry is None:
            return None   # a blank label would render an unlabelled option
        entries.append(entry)
    return entries


def _main_menu_entry(content: dict) -> Optional[dict]:
    """The "Main menu" way back that every sub-message carries."""
    return _option_entry(content, "labelMainMenu", "menu")


def _interactive(content: dict) -> bool:
    return bool(content.get("useInteractiveButtons", True))


def _compose(content: dict, body: str, entries: Optional[list[dict]],
             list_label: Optional[str] = None) -> MenuMessage:
    """Body + options + the hint, put where each one fits.

    Meta caps the footer at 60 characters and rejects longer, so a hint that
    does not fit goes into the body instead of being dropped.
    """
    hint = menu_content.render(content, "menuHint")
    if entries:
        if hint and len(hint) > FOOTER_MAX:
            body, hint = f"{body}\n\n{hint}", ""
        return MenuMessage(body[:BODY_MAX], buttons=entries, footer=hint or None,
                           list_label=list_label)
    if hint and hint not in body:
        body = f"{body}\n\n{hint}"
    return MenuMessage(body[:BODY_MAX])


def _greeting(content: dict, name: Optional[str]) -> str:
    """The welcome line, naming the citizen when we know who they are.

    Feature 29's first requirement. An identified number gets ``welcomeNamed``;
    an unknown one gets the anonymous ``welcome`` and is offered the profile
    option, which doubles as onboarding.
    """
    if name:
        return menu_content.render(content, "welcomeNamed", name=name)
    return menu_content.render(content, "welcome")


def main_menu_message(content: dict, greet: bool, name: Optional[str] = None,
                      note: Optional[str] = None) -> MenuMessage:
    """The welcome + options block. ``greet`` is False for a ``#`` return —
    a citizen already mid-conversation does not need welcoming again.

    ``note`` is the line explaining why they are seeing this again (a mis-key),
    placed after the greeting so the message reads as a greeting with an
    explanation rather than as a telling-off.

    With interactive options the numbered prompt is dropped — the options ARE
    the list, and "Press 1" next to a row labelled "Ticket status" is noise.
    Without them, everything stays in the body exactly as before.
    """
    entries = menu_buttons(content)
    parts = [_greeting(content, name)] if greet else []
    if note:
        parts.append(note)

    if entries:
        parts.append(menu_content.render(content, "menuIntro"))
        return _compose(content, "\n\n".join(p for p in parts if p), entries,
                        list_label=menu_content.render(content, "listButtonLabel"))

    parts.append(menu_content.render(content, "menuPrompt"))
    return _compose(content, "\n\n".join(p for p in parts if p), None)


def _sub_message(content: dict, text: str, extra: Optional[list[dict]] = None) -> MenuMessage:
    """Any message below the top level, with a Main menu option on it.

    "Press # to go back" was always true and always invisible: the citizen is
    looking at buttons. ``extra`` options come first, so the way back is the
    last thing in the list rather than the first thing they tap.
    """
    if not _interactive(content):
        return _with_hint(content, text)
    entries = list(extra or [])
    back = _main_menu_entry(content)
    if back:
        entries.append(back)
    return _compose(content, text, entries or None)


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

async def handle_inbound(
    db: DbWriterClient, tenant_id: str, thread_key: str, raw_text: Optional[str],
    identity_value: Optional[str], tenant_config: Optional[dict], trace_id: Optional[str] = None,
    in_reply_to: Optional[str] = None,
) -> MenuOutcome:
    """Route one inbound WhatsApp message through the menu.

    Returns a :class:`MenuOutcome`. The caller sends ``replies`` and, when
    ``stop`` is False, continues into the normal AI pipeline with ``text``.
    """
    content = menu_content.resolve(tenant_config)
    if not content.get("enabled", True):
        # The menu can be switched off per tenant, which restores the pre-Feature-26
        # behaviour exactly: straight into the routing ladder and the assistant.
        return MenuOutcome(replies=[], stop=False, text=raw_text)

    ttl = int(content.get("sessionTtlHours", menu_content.DEFAULT_SESSION_TTL_HOURS))
    text = (raw_text or "").strip()
    session = await load_session(tenant_id, thread_key)
    # One line saying what state this message landed in and whether it looked
    # like a menu option. Without it, "why did the citizen get the menu again?"
    # can only be answered by reading the code against a Valkey dump.
    logger.info("whatsapp menu inbound traceId=%s state=%s option=%s replyTo=%s",
                trace_id, (session or {}).get("state", "none"),
                _match_option(text, content), bool(in_reply_to))

    # `#`, and the Main menu option on every sub-message, outrank every state —
    # including "no session at all".
    if _wants_main_menu(text, content):
        await save_session(tenant_id, thread_key, {"state": STATE_MENU}, ttl)
        name = await citizen_name(db, tenant_id, identity_value, trace_id) if not session else None
        return MenuOutcome(replies=[main_menu_message(content, greet=not session, name=name)])

    if not session:
        # Feature 28: a citizen ANSWERING us is not a citizen INITIATING a chat.
        #
        # An agent replies from the ticket screen ("which street is this?"), the
        # citizen replies on WhatsApp, and with no session that answer used to
        # get the welcome menu — so it never reached the ticket and the agent
        # never saw it. The agent's reply goes out through the gateway, which
        # ai-core never sees, so there is no session for it to have created.
        #
        # Checked here rather than by weakening strict mode: the menu still owns
        # every message that starts a conversation, and this owns the ones that
        # continue one we started.
        #
        # A CHOSEN OPTION IS NEVER AN ANSWER. Live failure: an agent had an
        # unanswered "Is this resolved?" on TKT-00014, so this check said yes to
        # everything — the citizen's "3", then their button tap on "New ticket",
        # then the complaint details they typed all bypassed the menu and were
        # filed onto TKT-00014. They could not get out. `_at_menu` had the order
        # right; this branch did not.
        if _match_option(text, content) is None and await awaiting_our_reply(
                db, tenant_id, identity_value, in_reply_to, tenant_config, trace_id):
            logger.info("inbound answers a question we asked traceId=%s — skipping the menu",
                        trace_id)
            return MenuOutcome(replies=[], stop=False, text=raw_text)
        name = await citizen_name(db, tenant_id, identity_value, trace_id)
        return await _first_contact(tenant_id, thread_key, content, text, ttl, name)

    state = session.get("state")
    if state == STATE_MENU:
        return await _at_menu(db, tenant_id, thread_key, content, session, text, ttl,
                              tenant_config, trace_id, identity_value, in_reply_to)
    if state == STATE_PROFILE:
        return await _at_profile_menu(db, tenant_id, thread_key, content, session, text,
                                      identity_value, ttl, trace_id)
    if state in (STATE_AWAIT_NAME, STATE_AWAIT_EMAIL):
        return await _await_profile_value(db, tenant_id, thread_key, content, session, text,
                                          identity_value, ttl, trace_id)
    if state == STATE_AWAIT_TICKET_CHOICE:
        return await _await_ticket_choice(db, tenant_id, thread_key, content, session, text,
                                          identity_value, ttl, trace_id)
    if state == STATE_AWAIT_TICKET_ID:
        return await _await_ticket_id(db, tenant_id, thread_key, content, session, text,
                                      identity_value, ttl, trace_id)
    if state == STATE_AWAIT_NOTE:
        return await _await_note(db, tenant_id, thread_key, content, session, text, ttl, trace_id)
    if state == STATE_INTAKE:
        return await _in_intake(tenant_id, thread_key, session, text, ttl)

    # An unrecognised state can only come from a half-written or hand-edited
    # session. Restart rather than guess.
    logger.warning("unknown menu state %r; restarting the menu traceId=%s", state, trace_id)
    name = await citizen_name(db, tenant_id, identity_value, trace_id)
    return await _first_contact(tenant_id, thread_key, content, text, ttl, name)


async def awaiting_our_reply(
    db: DbWriterClient, tenant_id: str, identity_value: Optional[str],
    in_reply_to: Optional[str], tenant_config: Optional[dict], trace_id: Optional[str],
) -> bool:
    """Are we waiting on an answer from this citizen right now? (Feature 28)

    Two signals, cheapest first:

    1. **They swipe-replied to a message we sent.** Meta hands us its wamid as
       ``context.id``; if it matches a message we recorded, this is
       unambiguously a continuation. Exact, one lookup, no interpretation — the
       same signal routing rung 0 uses.
    2. **The last thing said on one of their tickets was said by us**, inside
       the reply window. That is what an unanswered agent follow-up looks like.

    Deliberately conservative. A false positive sends a genuine new complaint
    into the routing ladder, which is where it would have gone before the menu
    existed and which knows how to start a new ticket anyway. A false negative
    loses a citizen's answer, which is the bug this exists to fix.

    A true first contact owns no tickets, so the common case costs one indexed
    query and no message fetches at all.
    """
    if in_reply_to:
        try:
            if await db.find_message_by_channel_id(tenant_id, in_reply_to, trace_id=trace_id):
                return True
        except Exception:  # noqa: BLE001 - fall through to the slower signal
            logger.warning("reply-to lookup failed traceId=%s", trace_id)

    if not identity_value:
        return False
    try:
        identity = await db.find_by_phone(tenant_id, identity_value, trace_id=trace_id)
        master_id = (identity or {}).get("master_id")
        if not master_id:
            return False
        tickets = await db.list_tickets(
            tenant_id, identityId=master_id, status=ADDRESSABLE_STATUSES,
            sortBy="createdAt", sortDir="desc", pageSize=_AWAITING_REPLY_CANDIDATES,
            trace_id=trace_id)
    except Exception:  # noqa: BLE001 - never block the menu on a lookup problem
        logger.warning("awaiting-reply lookup failed traceId=%s", trace_id)
        return False

    cutoff = _reply_window_cutoff(tenant_config)
    # Why each candidate was rejected, logged as one line when none qualify.
    # Diagnosing this from the outside otherwise means reading the whole
    # conversation and guessing — which is exactly what it cost the first time.
    rejected: list[str] = []
    for ticket in tickets[:_AWAITING_REPLY_CANDIDATES]:
        number = ticket.get("ticket_number") or ticket.get("id")
        try:
            messages = await db.get_messages(ticket["id"], trace_id=trace_id)
        except Exception:  # noqa: BLE001 - one ticket failing must not decide the answer
            rejected.append(f"{number}:messages-unreadable")
            continue
        if not messages:
            rejected.append(f"{number}:no-messages")
            continue
        last = messages[-1]
        if last.get("direction") != "outbound":
            rejected.append(f"{number}:citizen-spoke-last")
            continue
        # It must be a HUMAN who spoke last, not us.
        #
        # This originally accepted any outbound message, which trapped citizens:
        # the citizen answers the agent, the assistant replies, and now the
        # assistant's own reply is the last outbound — so every later message
        # was still "an answer", bypassed the menu, and fell through the routing
        # ladder to "we couldn't tell which complaint this is about", then to
        # silence once the ask had been escalated. Only `#` got them out.
        # An agent asking a question is a state we are waiting on; the
        # assistant having said something is not.
        if last.get("author_type") != "agent":
            rejected.append(f"{number}:last-outbound-was-{last.get('author_type') or 'unknown'}")
            continue
        if (last.get("created_at") or "") < cutoff:
            rejected.append(f"{number}:outside-reply-window")
            continue
        # An intake request belongs to the menu's own option-2 flow, which has
        # its own session, so an answer to it is not an answer to an agent.
        if last.get("is_intake_request"):
            rejected.append(f"{number}:intake-question")
            continue
        logger.info("ticket %s is awaiting the citizen's reply traceId=%s", number, trace_id)
        return True

    logger.info("nothing is awaiting this citizen's reply traceId=%s checked=%d rejected=%s",
                trace_id, len(tickets[:_AWAITING_REPLY_CANDIDATES]), rejected or "none")
    return False


def _reply_window_cutoff(tenant_config: Optional[dict]) -> str:
    days = _reply_window_days(tenant_config)
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


async def _first_contact(
    tenant_id: str, thread_key: str, content: dict, text: str, ttl: int,
    name: Optional[str] = None,
) -> MenuOutcome:
    """No session: greet, show the menu, and hold on to whatever they said.

    ``carryOver`` is the whole point of stashing it — see the module docstring.
    A message that is only a menu key is not carried over: "2" is not a
    complaint, and prepending it to the intake would corrupt it.
    """
    session: dict[str, Any] = {"state": STATE_MENU}
    if text and _match_option(text, content) is None:
        session["carryOver"] = text
    await save_session(tenant_id, thread_key, session, ttl)
    return MenuOutcome(replies=[main_menu_message(content, greet=True, name=name)])


def _matches_label(text: str, content: Optional[dict], key: str) -> bool:
    """Is this message a tap on the option labelled by ``key``?

    Meta delivers an interactive reply as the button or row TITLE (see
    ``WhatsAppParser``), so matching is against the tenant's own configured
    label — a tenant that renames an option to "Pukaar darj karein" must still
    have the tap land on it. Titles are clipped to 20 characters on the way out,
    so the clipped form has to match too.
    """
    if not text or not content:
        return False
    normalised = text.strip().lower()
    label = str(content.get(key) or "").strip().lower()
    if not label:
        return False
    return normalised in (label, label[:BUTTON_TITLE_MAX])


def _match_option(text: str, content: Optional[dict] = None) -> Optional[str]:
    """"1", "one", or a tapped option -> its option id. None when it is not one.

    The numeric aliases stay for citizens who type instead of tapping.
    """
    if not text:
        return None
    for option_id, key in OPTION_LABELS.items():
        if _matches_label(text, content, key):
            return option_id

    # Whole-message match only. This used to also try the first word, to catch a
    # button title — but button titles are matched against the configured labels
    # above now, and the first-word rule actively misfired: "new water logging
    # problem in my street" starts with "new", so a real complaint was read as
    # the "new ticket" option. A menu key is the entire message or it is not a
    # menu key.
    return _OPTION_ALIASES.get(text.strip().lower())


def _wants_main_menu(text: str, content: Optional[dict]) -> bool:
    """``#``, or a tap on the Main menu option that every sub-message carries."""
    return text.strip() == RETURN_TO_MENU or _matches_label(text, content, "labelMainMenu")


async def citizen_name(
    db: DbWriterClient, tenant_id: str, identity_value: Optional[str], trace_id: Optional[str],
) -> Optional[str]:
    """The name we hold for this number, for the greeting. None if unknown.

    A lookup failure is not an error here: it costs the citizen's first name in
    a greeting, and greeting them anonymously is a complete conversation.
    """
    if not identity_value:
        return None
    try:
        identity = await db.find_by_phone(tenant_id, identity_value, trace_id=trace_id)
    except Exception:  # noqa: BLE001 - the greeting is not worth failing a turn for
        logger.warning("identity lookup for the greeting failed traceId=%s", trace_id)
        return None
    name = str((identity or {}).get("name") or "").strip()
    return name or None


async def _at_menu(
    db: DbWriterClient, tenant_id: str, thread_key: str, content: dict, session: dict,
    text: str, ttl: int, tenant_config: Optional[dict], trace_id: Optional[str],
    identity_value: Optional[str] = None, in_reply_to: Optional[str] = None,
) -> MenuOutcome:
    option = _match_option(text, content)

    if option == OPTION_PROFILE:
        session["state"] = STATE_PROFILE
        await save_session(tenant_id, thread_key, session, ttl)
        return MenuOutcome(replies=[_profile_menu_message(content)])

    if option == OPTION_STATUS:
        return await _show_ticket_list(db, tenant_id, thread_key, content, session,
                                       identity_value, ttl, trace_id)

    if option == OPTION_NEW:
        session["state"] = STATE_INTAKE
        await save_session(tenant_id, thread_key, session, ttl)
        return MenuOutcome(replies=[_sub_message(content, _register_intro(content, tenant_config))])

    if option == OPTION_END:
        # No hint appended: the conversation is over, and offering a way back
        # into a menu we have just closed contradicts the goodbye.
        await clear_session(tenant_id, thread_key)
        return MenuOutcome(replies=[MenuMessage(menu_content.render(content, "farewell"))])

    # Not one of the options. Before calling it a mis-key, check whether it is
    # an ANSWER to something we asked (Feature 28).
    #
    # This is the case the first version of the fix missed, and the one that
    # actually happens: the citizen used the menu earlier, so a session is still
    # alive for up to 12 hours. An agent then replies from the ticket screen,
    # the citizen answers "yes it is" — which matches no option — and the old
    # code showed them "Sorry, I didn't catch that" while their answer never
    # reached the ticket. Checking only the no-session branch covered the empty
    # case and left the common one broken.
    if await awaiting_our_reply(db, tenant_id, identity_value, in_reply_to,
                                tenant_config, trace_id):
        logger.info("inbound at the menu answers a question we asked traceId=%s — "
                    "handing it to the routing ladder", trace_id)
        # The agent has taken this conversation over, so the menu step aside
        # entirely rather than leaving a stale state for the next message.
        await clear_session(tenant_id, thread_key)
        return MenuOutcome(replies=[], stop=False, text=text)

    # A genuine mis-key. Greet them and re-show the options rather than
    # guessing, and keep whatever they typed in case it was a complaint they
    # will now register with the new-ticket option.
    #
    # Feature 29 scoped this deliberately. "Any message outside the options goes
    # back to the main menu" is right HERE — at the top level, with nothing
    # awaiting them — and wrong everywhere else: inside a flow their text is
    # that flow's input, and the check above has already handed over anything
    # that answers a question we asked. Applied literally it would undo every
    # Feature 28 follow-up.
    if text and not session.get("carryOver"):
        session["carryOver"] = text
        await save_session(tenant_id, thread_key, session, ttl)
    name = await citizen_name(db, tenant_id, identity_value, trace_id)
    return MenuOutcome(replies=[main_menu_message(
        content, greet=True, name=name,
        note=menu_content.render(content, "unknownOption"))])


def _register_intro(content: dict, tenant_config: Optional[dict]) -> str:
    """The new-ticket option's "here's what I need" message.

    The field list is the tenant's configured intake form, rendered by the same
    helper the AI intake path uses (``render_field_form``), so the menu can
    never ask for a different set of details than the flow it hands off to.

    With no configured fields, ``registerIntro`` would end on "reply with the
    following details:" and then stop — so the plain "type your complaint" ask
    is used instead (Feature 29). That is also the shape a WhatsApp Flow form
    would replace, if we ever publish one.
    """
    intro = menu_content.render(content, "registerIntro")
    try:
        catalog = catalog_for_tenant(tenant_config)
        field_configs = fields_for_channel(tenant_config, CHANNEL, catalog)
        # verified=True: WhatsApp always supplies the phone number, so the
        # mobile field is native and must not be asked for.
        form = render_field_form(field_configs, CHANNEL, True, catalog)
    except Exception:  # noqa: BLE001 - a config problem must not block registration
        logger.exception("could not render the intake form for the menu")
        return menu_content.render(content, "askComplaint")
    if not form:
        return menu_content.render(content, "askComplaint")
    return f"{intro}\n\n{form}"


# ---------------------------------------------------------------------------
# Option: update my details (Feature 29)
# ---------------------------------------------------------------------------

def _profile_menu_message(content: dict) -> MenuMessage:
    """Name / Email / Main menu — exactly three, so it renders as buttons."""
    extra = []
    for key, option_id in (("labelNameOption", "name"), ("labelEmailOption", "email")):
        entry = _option_entry(content, key, option_id)
        if entry:
            extra.append(entry)
    return _sub_message(content, menu_content.render(content, "profilePrompt"), extra)


async def _at_profile_menu(
    db: DbWriterClient, tenant_id: str, thread_key: str, content: dict, session: dict,
    text: str, identity_value: Optional[str], ttl: int, trace_id: Optional[str],
) -> MenuOutcome:
    if _matches_label(text, content, "labelNameOption") or text.strip().lower() in ("1", "name"):
        session["state"] = STATE_AWAIT_NAME
        await save_session(tenant_id, thread_key, session, ttl)
        # A citizen we have no name for is being onboarded rather than
        # corrected, and saying so explains why we are asking at all.
        known = await citizen_name(db, tenant_id, identity_value, trace_id)
        key = "askName" if known else "profileUnknownName"
        return MenuOutcome(replies=[_sub_message(content, menu_content.render(content, key))])

    if _matches_label(text, content, "labelEmailOption") or text.strip().lower() in ("2", "email"):
        session["state"] = STATE_AWAIT_EMAIL
        await save_session(tenant_id, thread_key, session, ttl)
        return MenuOutcome(replies=[_sub_message(content, menu_content.render(content, "askEmail"))])

    # Neither option, and Main menu was handled before we got here.
    return MenuOutcome(replies=[_profile_menu_message(content)])


async def _await_profile_value(
    db: DbWriterClient, tenant_id: str, thread_key: str, content: dict, session: dict,
    text: str, identity_value: Optional[str], ttl: int, trace_id: Optional[str],
) -> MenuOutcome:
    """The typed name or email. Their message IS the submit (Feature 29).

    WhatsApp has no text box with a Submit button outside of a published Flow,
    so the exchange is the ordinary one: we ask, they reply, the Main menu
    option on our ask is the cancel.
    """
    field = "name" if session.get("state") == STATE_AWAIT_NAME else "email"
    value = text.strip()

    invalid = _invalid_reason(field, value)
    if invalid:
        # Stay in this state: they are mid-correction, and dropping them at the
        # menu would make them start over to fix a typo.
        return MenuOutcome(replies=[_sub_message(content, menu_content.render(content, invalid))])

    saved, reason = await _save_profile_field(
        db, tenant_id, identity_value, field, value, trace_id)
    if not saved:
        return MenuOutcome(replies=[_sub_message(content, menu_content.render(content, reason))])

    session["state"] = STATE_MENU
    await save_session(tenant_id, thread_key, session, ttl)
    confirmation = menu_content.render(
        content, "nameUpdated" if field == "name" else "emailUpdated",
        name=value, email=value)
    return MenuOutcome(replies=[_sub_message(content, confirmation)])


def _invalid_reason(field: str, value: str) -> Optional[str]:
    """The copy key explaining why this value cannot be saved, or None."""
    if field == "email":
        return None if _EMAIL_RE.match(value) else "emailInvalid"
    if not (NAME_MIN <= len(value) <= NAME_MAX) or not any(ch.isalpha() for ch in value):
        return "nameInvalid"
    # An email in the name box is a mis-tap on the previous screen, not a name.
    return "nameInvalid" if _EMAIL_RE.match(value) else None


async def _save_profile_field(
    db: DbWriterClient, tenant_id: str, identity_value: Optional[str], field: str,
    value: str, trace_id: Optional[str],
) -> tuple[bool, str]:
    """Write the correction. Returns (saved, copy key when not saved).

    ``overwrite`` is what makes this a correction rather than an enrichment:
    db-writer's PATCH otherwise refuses to touch a field it already holds, which
    is exactly the value the citizen is trying to fix.

    A number with no identity yet is a citizen who has never filed anything, so
    one is created — the profile option doubles as onboarding.
    """
    if not identity_value:
        return False, "ticketNotFound"
    try:
        identity = await db.find_by_phone(tenant_id, identity_value, trace_id=trace_id)
    except Exception:  # noqa: BLE001
        logger.exception("identity lookup failed before a profile update traceId=%s", trace_id)
        return False, "ticketNotFound"

    try:
        if not identity:
            await db.create_identity(
                {"tenantId": tenant_id, "phone": identity_value, field: value}, trace_id=trace_id)
            logger.info("created an identity from the profile menu traceId=%s", trace_id)
            return True, ""
        await db.update_identity(
            identity["id"], {field: value, "overwrite": True}, trace_id=trace_id)
        logger.info("citizen corrected their %s traceId=%s", field, trace_id)
        return True, ""
    except Exception as exc:  # noqa: BLE001 - the citizen must be told, not left waiting
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 409:
            # Taking an address that identifies someone else is a reassignment
            # of whoever owns those tickets, not an edit. db-writer refuses it.
            logger.info("profile email rejected as already in use traceId=%s", trace_id)
            return False, "emailInUse"
        logger.exception("failed to save the citizen's %s traceId=%s", field, trace_id)
        return False, "ticketNotFound"


# ---------------------------------------------------------------------------
# Option: ticket status (Feature 29)
# ---------------------------------------------------------------------------

async def _citizens_tickets(
    db: DbWriterClient, tenant_id: str, identity_value: Optional[str], trace_id: Optional[str],
) -> Optional[list[dict]]:
    """Their open and resolved tickets, newest first. None if we cannot tell.

    None and [] are deliberately different: "we could not look you up" and "you
    have no tickets" are different things to tell someone.
    """
    if not identity_value:
        return None
    try:
        identity = await db.find_by_phone(tenant_id, identity_value, trace_id=trace_id)
        master_id = (identity or {}).get("master_id")
        if not master_id:
            return []
        return await db.list_tickets(
            tenant_id, identityId=master_id, status=LISTED_STATUSES,
            sortBy="createdAt", sortDir="desc", pageSize=50, trace_id=trace_id)
    except Exception:  # noqa: BLE001
        logger.exception("could not list the citizen's tickets traceId=%s", trace_id)
        return None


def _ticket_row(content: dict, ticket: dict) -> dict:
    """One ticket as a tappable list row.

    The 24-character title is why the row id is the ticket NUMBER rather than
    the title: two tickets whose complaints differ only past the clip would
    otherwise arrive at Meta with identical ids and the whole send would be
    rejected. The description is where the complaint actually fits — 72
    characters, against a button's none.
    """
    number = str(ticket.get("ticket_number") or ticket.get("ticketNumber") or "")
    complaint = str(ticket.get("chief_complaint") or ticket.get("chiefComplaint") or "").strip()
    title = menu_content.render(
        content, "ticketRowTitle", ticket=number,
        complaint=complaint or content.get("complaintUnknown", "")).strip()
    description = menu_content.render(
        content, "ticketRowDescription",
        status=_status_label(ticket.get("status")),
        complaint=complaint,
        eta=_format_timestamp(ticket.get("eta_at")) or content.get("etaUnknown", ""),
        updated=_format_timestamp(ticket.get("updated_at")) or "just now").strip()
    return {"id": f"{BUTTON_ID_PREFIX}tkt_{number}", "title": title[:ROW_TITLE_MAX],
            "description": description[:ROW_DESCRIPTION_MAX]}


async def _show_ticket_list(
    db: DbWriterClient, tenant_id: str, thread_key: str, content: dict, session: dict,
    identity_value: Optional[str], ttl: int, trace_id: Optional[str],
) -> MenuOutcome:
    """Their tickets, tappable — or a request for the number when there are many."""
    tickets = await _citizens_tickets(db, tenant_id, identity_value, trace_id)

    if tickets is None or not _interactive(content):
        # No list to offer (lookup failed, or this tenant has interactive
        # messages switched off): fall back to the Feature 26 exchange, which
        # only ever needed the number.
        session["state"] = STATE_AWAIT_TICKET_ID
        await save_session(tenant_id, thread_key, session, ttl)
        return MenuOutcome(replies=[_sub_message(content, menu_content.render(content, "askTicketId"))])

    if not tickets:
        session["state"] = STATE_MENU
        await save_session(tenant_id, thread_key, session, ttl)
        return MenuOutcome(replies=[_sub_message(content, menu_content.render(content, "ticketListEmpty"))])

    many = len(tickets) > TICKET_LIST_THRESHOLD
    if many:
        # Two navigation rows have to fit alongside them, and Meta's list holds
        # ten in total.
        shown = tickets[:LIST_ROWS_MAX - 2]
        body = menu_content.render(content, "ticketListMany", count=len(tickets))
    else:
        shown = tickets
        body = menu_content.render(content, "ticketListIntro")

    rows = [_ticket_row(content, ticket) for ticket in shown]
    if many:
        entry = _option_entry(content, "labelTypeTicketId", "type_id")
        if entry:
            rows.append(entry)
    back = _main_menu_entry(content)
    if back:
        rows.append(back)

    session["state"] = STATE_AWAIT_TICKET_CHOICE
    session["listed"] = [row["id"] for row in rows]
    await save_session(tenant_id, thread_key, session, ttl)
    return MenuOutcome(replies=[_compose(
        content, body, rows, list_label=menu_content.render(content, "listButtonLabel"))])


async def _await_ticket_choice(
    db: DbWriterClient, tenant_id: str, thread_key: str, content: dict, session: dict,
    text: str, identity_value: Optional[str], ttl: int, trace_id: Optional[str],
) -> MenuOutcome:
    """A tapped row, or a typed ticket number.

    A tap arrives as the row's TITLE, which starts with the ticket number, so
    the same lookup handles both — and it is still the ownership-checked one, so
    a number typed from the list is no more trusted than any other.
    """
    if _matches_label(text, content, "labelTypeTicketId"):
        session["state"] = STATE_AWAIT_TICKET_ID
        await save_session(tenant_id, thread_key, session, ttl)
        return MenuOutcome(replies=[_sub_message(content, menu_content.render(content, "askTicketId"))])
    return await _await_ticket_id(db, tenant_id, thread_key, content, session, text,
                                  identity_value, ttl, trace_id)


async def _await_ticket_id(
    db: DbWriterClient, tenant_id: str, thread_key: str, content: dict, session: dict,
    text: str, identity_value: Optional[str], ttl: int, trace_id: Optional[str],
) -> MenuOutcome:
    ticket = await _find_citizens_ticket(db, tenant_id, text, identity_value, trace_id)
    if ticket is None:
        return MenuOutcome(replies=[
            _sub_message(content, menu_content.render(content, "ticketNotFound"))])

    session["state"] = STATE_AWAIT_NOTE
    session["ticketId"] = ticket.get("id")
    session["ticketNumber"] = ticket.get("ticket_number") or ticket.get("ticketNumber")
    session.pop("listed", None)
    await save_session(tenant_id, thread_key, session, ttl)

    details = format_ticket_details(content, ticket)
    invite = menu_content.render(content, "inviteNote")
    return MenuOutcome(replies=[_sub_message(content, f"{details}\n\n{invite}")])


async def _find_citizens_ticket(
    db: DbWriterClient, tenant_id: str, text: str, identity_value: Optional[str],
    trace_id: Optional[str],
) -> Optional[dict]:
    """The one ticket the citizen named — and only if it is theirs.

    Two deliberate constraints:

    * **One ticket, not their list.** Looked up by the number they gave, so the
      reply is about that ticket alone.
    * **Ownership is checked.** Ticket numbers are sequential and guessable
      (``TKT-00042``), so without this anyone could read out any citizen's
      complaint status by counting. A ticket that exists but belongs to someone
      else is reported exactly like one that does not exist — saying "that
      ticket isn't yours" would confirm it exists.
    """
    number = extract_ticket_number(text)
    if not number:
        # A bare "42" or "00042" is a reasonable thing for a citizen to send
        # when we asked for a ticket ID.
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits or len(digits) > 6:
            return None
        number = f"TKT-{int(digits):05d}"

    try:
        matches = await db.list_tickets(tenant_id, ticketNumber=number, trace_id=trace_id)
    except Exception:  # noqa: BLE001 - a lookup failure must read as "not found", not crash the turn
        logger.exception("ticket lookup failed for %s traceId=%s", number, trace_id)
        return None
    if not matches:
        return None
    ticket = matches[0]

    if not await _belongs_to(db, tenant_id, ticket, identity_value, trace_id):
        logger.info("ticket %s requested from a number it does not belong to traceId=%s",
                    number, trace_id)
        return None
    # The list projection carries every field the details message needs, but
    # re-read the full row so nothing depends on LIST_COLUMNS staying in step.
    try:
        return await db.get_ticket(ticket["id"], trace_id=trace_id)
    except Exception:  # noqa: BLE001
        return ticket


async def _belongs_to(
    db: DbWriterClient, tenant_id: str, ticket: dict, identity_value: Optional[str],
    trace_id: Optional[str],
) -> bool:
    if not identity_value:
        return False
    ticket_identity = ticket.get("identity_id") or ticket.get("identityId")
    if not ticket_identity:
        # A stub that never resolved an identity. Fall back to the thread key,
        # which for WhatsApp is the phone number itself.
        thread_id = ticket.get("thread_id") or ticket.get("threadId") or ""
        return thread_id == f"{CHANNEL}:{identity_value}"
    try:
        identity = await db.find_by_phone(tenant_id, identity_value, trace_id=trace_id)
    except Exception:  # noqa: BLE001 - fail closed: an unverifiable owner is not an owner
        logger.exception("identity lookup failed traceId=%s", trace_id)
        return False
    return bool(identity and identity.get("master_id") == ticket_identity)


async def _await_note(
    db: DbWriterClient, tenant_id: str, thread_key: str, content: dict, session: dict,
    text: str, ttl: int, trace_id: Optional[str],
) -> MenuOutcome:
    ticket_id = session.get("ticketId")
    ticket_number = session.get("ticketNumber")
    if not text:
        return MenuOutcome(replies=[_sub_message(content, menu_content.render(content, "inviteNote"))])

    stored = await append_citizen_note(db, tenant_id, ticket_id, text, trace_id)
    if not stored:
        # Nothing was written, so nothing may be acknowledged. Telling a citizen
        # "the team will revert" about a note that does not exist is the one
        # outcome here that is worse than an error message.
        return MenuOutcome(replies=[_sub_message(content, menu_content.render(content, "ticketNotFound"))])

    # Back to the menu rather than cleared (Feature 29): the acknowledgement
    # carries a Main menu option, and tapping it should open the menu rather
    # than be treated as a brand-new conversation.
    await save_session(tenant_id, thread_key, {"state": STATE_MENU}, ttl)
    return MenuOutcome(replies=[
        MenuMessage(menu_content.render(content, "noteAdded", ticket=ticket_number or "")),
        _sub_message(content, menu_content.render(content, "conversationEnd")),
    ])


async def append_citizen_note(
    db: DbWriterClient, tenant_id: str, ticket_id: Optional[str], text: str,
    trace_id: Optional[str],
) -> bool:
    """Put the citizen's words on the ticket's conversation timeline.

    A *message*, not a ``ticket_notes`` row: notes are the agents' internal
    record (and the mandatory-note audit trail), whereas this is the citizen
    speaking and belongs in the timeline the agent reads and can reply to.
    The event alongside it is what makes it findable as a citizen-initiated
    addition rather than just another inbound line.
    """
    if not ticket_id:
        return False
    try:
        await db.add_message(ticket_id, {
            "tenantId": tenant_id,
            "channel": CHANNEL,
            "direction": "inbound",
            "authorType": "user",
            "content": text,
        }, trace_id=trace_id)
    except Exception:  # noqa: BLE001 - reported to the caller, which must not then ack it
        logger.exception("failed to append citizen note to %s traceId=%s", ticket_id, trace_id)
        return False
    try:
        await db.add_event(ticket_id, {
            "eventType": "ticket.citizen_note",
            "actorType": "system",
        }, trace_id=trace_id)
    except Exception:  # noqa: BLE001 - the note is saved; its audit line is best-effort
        logger.warning("failed to record citizen_note event for %s traceId=%s", ticket_id, trace_id)
    return True


async def _in_intake(
    tenant_id: str, thread_key: str, session: dict, text: str, ttl: int,
) -> MenuOutcome:
    """Hand the message to the AI pipeline, merging any carried-over first message."""
    carry_over = session.pop("carryOver", None)
    if carry_over:
        await save_session(tenant_id, thread_key, session, ttl)
    merged = f"{carry_over}\n{text}" if carry_over and text else (carry_over or text)
    # They chose "register a new ticket" to get here, which is a statement that
    # this is NOT a reply to anything. Live failure: an agent had an outstanding
    # "Is this resolved?" on TKT-00014, and the citizen's brand-new water-logging
    # complaint was read as the answer to it and filed there.
    return MenuOutcome(replies=[], stop=False, text=merged, explicit_new_complaint=True)


# ---------------------------------------------------------------------------
# Called from the complaint.ready path
# ---------------------------------------------------------------------------

async def finish_registration(
    db: DbWriterClient, tenant_id: str, thread_key: str, ticket_id: Optional[str],
    ticket_number: Optional[str], tenant_config: Optional[dict], trace_id: Optional[str] = None,
) -> Optional[list[MenuMessage]]:
    """The message that closes out the new-ticket option, once it exists.

    Returns None when the menu is disabled or this thread was not in the menu's
    intake flow, in which case the caller should fall back to the ordinary
    ticket acknowledgement.

    **One message, not two** (Feature 29). This used to send the details and
    then "we're ending this conversation here"; back to back they read as a
    system talking to itself, and the citizen has just done the one thing that
    most deserves a clean confirmation. The ticket id and a Main menu option is
    the whole reply.
    """
    content = menu_content.resolve(tenant_config)
    if not content.get("enabled", True):
        return None
    session = await load_session(tenant_id, thread_key)
    if not session or session.get("state") != STATE_INTAKE:
        return None

    ticket: dict = {"ticket_number": ticket_number}
    if ticket_id:
        try:
            ticket = await db.get_ticket(ticket_id, trace_id=trace_id) or ticket
        except Exception:  # noqa: BLE001 - the ticket exists; only its ETA is at stake
            logger.warning("could not read ticket %s for the registration reply", ticket_id)

    ttl = int(content.get("sessionTtlHours", menu_content.DEFAULT_SESSION_TTL_HOURS))
    await save_session(tenant_id, thread_key, {"state": STATE_MENU}, ttl)
    return [_sub_message(content, format_ticket_details(content, ticket, key="ticketCreated"))]
