"""The WhatsApp conversation menu (Feature 26).

Every inbound WhatsApp message goes through this module before anything else.
It is a small, deterministic state machine — no LLM, no heuristics — that owns
what the citizen is currently doing:

    (no session)  --any message-->  MENU          [welcome + 1/2/3]
    MENU          --"1"-->          AWAIT_TICKET_ID
    MENU          --"2"-->          INTAKE        [hands off to the AI pipeline]
    MENU          --"3"-->          (cleared)     [farewell]
    AWAIT_TICKET_ID --ticket id-->  AWAIT_NOTE    [details: status/ETA/updated]
    AWAIT_NOTE    --any message-->  (cleared)     [note appended to the ticket]
    INTAKE        --ticket filed--> (cleared)     [details + "message us again"]
    any           --"#"-->          MENU

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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.conversation import menu_content
from app.conversation.intake_fields import catalog_for_tenant, fields_for_channel, render_field_form
from app.dedup.service import ADDRESSABLE_STATUSES
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

# Meta's interactive reply-button limits. Enforced here as well as in the
# gateway's validation: a payload Meta rejects means the citizen gets nothing.
BUTTON_TITLE_MAX = 20
BODY_MAX = 1024
FOOTER_MAX = 60
BUTTON_ID_PREFIX = "menu_"

STATE_MENU = "menu"
STATE_AWAIT_TICKET_ID = "await_ticket_id"
STATE_AWAIT_NOTE = "await_note"
STATE_INTAKE = "intake"

RETURN_TO_MENU = "#"

# Accepted spellings of each option. WhatsApp citizens type "1." and "1)" as
# often as "1", and an interactive button reply arrives as the button's TITLE
# (see WhatsAppParser), not its number — so the words have to be accepted too or
# the buttons would be dead.
_OPTION_ALIASES: dict[str, str] = {
    "1": "1", "1.": "1", "1)": "1", "one": "1", "status": "1",
    "2": "2", "2.": "2", "2)": "2", "two": "2", "register": "2", "new": "2",
    "3": "3", "3.": "3", "3)": "3", "three": "3", "end": "3", "exit": "3", "bye": "3",
}


@dataclass
class MenuMessage:
    """One outgoing WhatsApp message.

    ``buttons`` turns it into a Meta *interactive reply-buttons* message —
    tappable options instead of "press 1" — and ``footer`` is the small grey
    line beneath them. Both are ignored by the plain-text path, so a tenant with
    interactive mode off, or a channel that cannot render buttons, still gets a
    complete message from the same object.
    """

    text: str
    buttons: Optional[list[dict]] = None
    footer: Optional[str] = None

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


def menu_buttons(content: dict) -> Optional[list[dict]]:
    """The three options as Meta interactive reply buttons, or None for text.

    Meta caps a reply-button set at 3 and each title at 20 characters, which is
    exactly why the menu has three options and why the labels are a separate,
    short config field rather than being derived from ``menuPrompt``. Titles are
    truncated rather than rejected here: a label an admin made too long should
    cost a clipped word, not a citizen receiving nothing.
    """
    if not content.get("useInteractiveButtons", True):
        return None
    buttons = []
    for option in ("1", "2", "3"):
        title = menu_content.render(content, f"option{option}Label").strip()
        if not title:
            return None   # a blank label would render an unlabelled button
        buttons.append({"id": f"{BUTTON_ID_PREFIX}{option}", "title": title[:BUTTON_TITLE_MAX]})
    return buttons


def main_menu_message(content: dict, greet: bool) -> MenuMessage:
    """The welcome + options block. ``greet`` is False for a ``#`` return —
    a citizen already mid-conversation does not need welcoming again.

    With interactive buttons the numbered prompt is dropped (the options ARE the
    buttons, and "Press 1" next to a button labelled "Ticket status" is noise)
    and the hint moves into the footer. Without them, everything stays in the
    body exactly as before.
    """
    buttons = menu_buttons(content)
    hint = menu_content.render(content, "menuHint")
    parts = [menu_content.render(content, "welcome")] if greet else []

    if buttons:
        parts.append(menu_content.render(content, "menuIntro"))
        body = "\n\n".join(p for p in parts if p)
        # Meta caps the footer at 60 characters and silently rejects longer;
        # a hint that does not fit is better dropped into the body.
        if hint and len(hint) <= FOOTER_MAX:
            return MenuMessage(body[:BODY_MAX], buttons=buttons, footer=hint)
        if hint:
            body = f"{body}\n\n{hint}"
        return MenuMessage(body[:BODY_MAX], buttons=buttons)

    parts.append(menu_content.render(content, "menuPrompt"))
    if hint:
        parts.append(hint)
    return MenuMessage("\n\n".join(p for p in parts if p))


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

    # `#` outranks every state, including "no session at all".
    if text == RETURN_TO_MENU:
        await save_session(tenant_id, thread_key, {"state": STATE_MENU}, ttl)
        return MenuOutcome(replies=[main_menu_message(content, greet=not session)])

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
        return await _first_contact(tenant_id, thread_key, content, text, ttl)

    state = session.get("state")
    if state == STATE_MENU:
        return await _at_menu(db, tenant_id, thread_key, content, session, text, ttl,
                              tenant_config, trace_id, identity_value, in_reply_to)
    if state == STATE_AWAIT_TICKET_ID:
        return await _await_ticket_id(db, tenant_id, thread_key, content, session, text,
                                      identity_value, ttl, trace_id)
    if state == STATE_AWAIT_NOTE:
        return await _await_note(db, tenant_id, thread_key, content, session, text, trace_id)
    if state == STATE_INTAKE:
        return await _in_intake(tenant_id, thread_key, session, text, ttl)

    # An unrecognised state can only come from a half-written or hand-edited
    # session. Restart rather than guess.
    logger.warning("unknown menu state %r; restarting the menu traceId=%s", state, trace_id)
    return await _first_contact(tenant_id, thread_key, content, text, ttl)


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
    return MenuOutcome(replies=[main_menu_message(content, greet=True)])


def _match_option(text: str, content: Optional[dict] = None) -> Optional[str]:
    """"1", "1.", "one", or a tapped button -> "1". None when it is not a menu key.

    Button taps are matched against the tenant's own configured LABELS, not a
    fixed word list: Meta delivers an interactive reply as the button's title
    (see `WhatsAppParser`), and a tenant that renames option 2 to "Pukaar darj
    karein" must still have the tap land on option 2. The numeric aliases stay
    for citizens who type instead of tapping.
    """
    if not text:
        return None
    normalised = text.strip().lower()

    if content:
        for option in ("1", "2", "3"):
            label = str(content.get(f"option{option}Label") or "").strip().lower()
            if label and normalised == label:
                return option
        # Titles are truncated to 20 chars on the way out, so a longer
        # configured label comes back clipped; match the clipped form too.
        for option in ("1", "2", "3"):
            label = str(content.get(f"option{option}Label") or "").strip().lower()
            if label and normalised == label[:BUTTON_TITLE_MAX]:
                return option

    # Whole-message match only. This used to also try the first word, to catch a
    # button title — but button titles are matched against the configured labels
    # above now, and the first-word rule actively misfired: "new water logging
    # problem in my street" starts with "new", so a real complaint was read as
    # "option 2". A menu key is the entire message or it is not a menu key.
    return _OPTION_ALIASES.get(normalised)


async def _at_menu(
    db: DbWriterClient, tenant_id: str, thread_key: str, content: dict, session: dict,
    text: str, ttl: int, tenant_config: Optional[dict], trace_id: Optional[str],
    identity_value: Optional[str] = None, in_reply_to: Optional[str] = None,
) -> MenuOutcome:
    option = _match_option(text, content)

    if option == "1":
        session["state"] = STATE_AWAIT_TICKET_ID
        await save_session(tenant_id, thread_key, session, ttl)
        return MenuOutcome(replies=[_with_hint(content, menu_content.render(content, "askTicketId"))])

    if option == "2":
        session["state"] = STATE_INTAKE
        await save_session(tenant_id, thread_key, session, ttl)
        return MenuOutcome(replies=[_with_hint(content, _register_intro(content, tenant_config))])

    if option == "3":
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

    # A genuine mis-key. Re-show the options rather than guessing, and keep
    # whatever they typed in case it was a complaint they will now register with 2.
    if text and not session.get("carryOver"):
        session["carryOver"] = text
        await save_session(tenant_id, thread_key, session, ttl)
    menu = main_menu_message(content, greet=False)
    return MenuOutcome(replies=[MenuMessage(
        menu_content.render(content, "unknownOption") + "\n\n" + menu.text,
        buttons=menu.buttons, footer=menu.footer)])


def _register_intro(content: dict, tenant_config: Optional[dict]) -> str:
    """Option 2's "here's what I need" message.

    The field list is the tenant's configured intake form, rendered by the same
    helper the AI intake path uses (``render_field_form``), so the menu can
    never ask for a different set of details than the flow it hands off to.
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
        return intro
    return f"{intro}\n\n{form}" if form else intro


async def _await_ticket_id(
    db: DbWriterClient, tenant_id: str, thread_key: str, content: dict, session: dict,
    text: str, identity_value: Optional[str], ttl: int, trace_id: Optional[str],
) -> MenuOutcome:
    ticket = await _find_citizens_ticket(db, tenant_id, text, identity_value, trace_id)
    if ticket is None:
        return MenuOutcome(replies=[
            _with_hint(content, menu_content.render(content, "ticketNotFound"))])

    session["state"] = STATE_AWAIT_NOTE
    session["ticketId"] = ticket.get("id")
    session["ticketNumber"] = ticket.get("ticket_number") or ticket.get("ticketNumber")
    await save_session(tenant_id, thread_key, session, ttl)

    details = format_ticket_details(content, ticket)
    invite = menu_content.render(content, "inviteNote")
    return MenuOutcome(replies=[_with_hint(content, f"{details}\n\n{invite}")])


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
    text: str, trace_id: Optional[str],
) -> MenuOutcome:
    ticket_id = session.get("ticketId")
    ticket_number = session.get("ticketNumber")
    if not text:
        return MenuOutcome(replies=[_with_hint(content, menu_content.render(content, "inviteNote"))])

    stored = await append_citizen_note(db, tenant_id, ticket_id, text, trace_id)
    if not stored:
        # Nothing was written, so nothing may be acknowledged. Telling a citizen
        # "the team will revert" about a note that does not exist is the one
        # outcome here that is worse than an error message.
        return MenuOutcome(replies=[_with_hint(content, menu_content.render(content, "ticketNotFound"))])

    await clear_session(tenant_id, thread_key)
    return MenuOutcome(replies=[
        MenuMessage(menu_content.render(content, "noteAdded", ticket=ticket_number or "")),
        MenuMessage(menu_content.render(content, "conversationEnd")),
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
    """The messages that close out option 2, once the ticket actually exists.

    Returns None when the menu is disabled or this thread was not in the menu's
    intake flow, in which case the caller should fall back to the ordinary
    ticket acknowledgement.
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

    await clear_session(tenant_id, thread_key)
    return [
        MenuMessage(format_ticket_details(content, ticket, key="ticketCreated")),
        MenuMessage(menu_content.render(content, "conversationEnd")),
    ]
