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
from datetime import datetime
from typing import Any, Optional

from app.conversation import menu_content
from app.conversation.intake_fields import catalog_for_tenant, fields_for_channel, render_field_form
from app.events.client import get_valkey
from app.identity.db_client import DbWriterClient
from app.tickets.intake import extract_ticket_number

logger = logging.getLogger("ai-core")

CHANNEL = "whatsapp"

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
class MenuOutcome:
    """What the dispatcher should do with this message.

    ``replies`` are sent in order. ``stop`` means the menu has fully handled the
    message and the AI pipeline must not run. When ``stop`` is False the message
    continues into ``ensure_ticket_stub``/``ConversationAgent`` with ``text`` in
    place of the raw text (carry-over merged in).
    """

    replies: list[str] = field(default_factory=list)
    stop: bool = True
    text: Optional[str] = None


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
    """The one-ticket summary: number, status, ETA, last updated. Composed from
    the row, never paraphrased — see the module docstring."""
    return menu_content.render(
        content, key,
        ticket=ticket.get("ticket_number") or ticket.get("ticketNumber") or "",
        status=_status_label(ticket.get("status")),
        eta=_format_timestamp(ticket.get("eta_at")) or content.get("etaUnknown", "not set yet"),
        updated=_format_timestamp(ticket.get("updated_at")) or "just now",
    )


def _with_hint(content: dict, text: str) -> str:
    """Append the "press # for the main menu" line.

    The requirement is that every message carries it. Skipped only when the text
    already contains it — the main-menu message itself ends with the hint, and
    repeating it twice in one send reads as a bug.
    """
    hint = menu_content.render(content, "menuHint")
    if not hint or hint in text:
        return text
    return f"{text}\n\n{hint}"


def main_menu_text(content: dict, greet: bool) -> str:
    """The welcome + options block. ``greet`` is False for a ``#`` return —
    a citizen already mid-conversation does not need welcoming again."""
    prompt = menu_content.render(content, "menuPrompt")
    hint = menu_content.render(content, "menuHint")
    parts = [menu_content.render(content, "welcome")] if greet else []
    parts.append(prompt)
    if hint:
        parts.append(hint)
    return "\n\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

async def handle_inbound(
    db: DbWriterClient, tenant_id: str, thread_key: str, raw_text: Optional[str],
    identity_value: Optional[str], tenant_config: Optional[dict], trace_id: Optional[str] = None,
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

    # `#` outranks every state, including "no session at all".
    if text == RETURN_TO_MENU:
        await save_session(tenant_id, thread_key, {"state": STATE_MENU}, ttl)
        return MenuOutcome(replies=[main_menu_text(content, greet=not session)])

    if not session:
        return await _first_contact(tenant_id, thread_key, content, text, ttl)

    state = session.get("state")
    if state == STATE_MENU:
        return await _at_menu(db, tenant_id, thread_key, content, session, text, ttl,
                              tenant_config, trace_id)
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


async def _first_contact(
    tenant_id: str, thread_key: str, content: dict, text: str, ttl: int,
) -> MenuOutcome:
    """No session: greet, show the menu, and hold on to whatever they said.

    ``carryOver`` is the whole point of stashing it — see the module docstring.
    A message that is only a menu key is not carried over: "2" is not a
    complaint, and prepending it to the intake would corrupt it.
    """
    session: dict[str, Any] = {"state": STATE_MENU}
    if text and _match_option(text) is None:
        session["carryOver"] = text
    await save_session(tenant_id, thread_key, session, ttl)
    return MenuOutcome(replies=[main_menu_text(content, greet=True)])


def _match_option(text: str) -> Optional[str]:
    """"1", "1.", "one", or a button title -> "1". None when it is not a menu key."""
    if not text:
        return None
    normalised = text.strip().lower()
    if normalised in _OPTION_ALIASES:
        return _OPTION_ALIASES[normalised]
    # A button reply arrives as the button's full title ("Register a new ticket").
    first = normalised.split()[0].strip(".,)") if normalised.split() else ""
    return _OPTION_ALIASES.get(first)


async def _at_menu(
    db: DbWriterClient, tenant_id: str, thread_key: str, content: dict, session: dict,
    text: str, ttl: int, tenant_config: Optional[dict], trace_id: Optional[str],
) -> MenuOutcome:
    option = _match_option(text)

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
        return MenuOutcome(replies=[menu_content.render(content, "farewell")])

    # Anything else at the menu is a mis-key. Re-show the options rather than
    # guessing, and keep whatever they typed in case it was a complaint they
    # will now register with 2.
    if text and not session.get("carryOver"):
        session["carryOver"] = text
        await save_session(tenant_id, thread_key, session, ttl)
    return MenuOutcome(replies=[
        menu_content.render(content, "unknownOption") + "\n\n" + main_menu_text(content, greet=False)])


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
        menu_content.render(content, "noteAdded", ticket=ticket_number or ""),
        menu_content.render(content, "conversationEnd"),
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
    return MenuOutcome(replies=[], stop=False, text=merged)


# ---------------------------------------------------------------------------
# Called from the complaint.ready path
# ---------------------------------------------------------------------------

async def finish_registration(
    db: DbWriterClient, tenant_id: str, thread_key: str, ticket_id: Optional[str],
    ticket_number: Optional[str], tenant_config: Optional[dict], trace_id: Optional[str] = None,
) -> Optional[list[str]]:
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
        format_ticket_details(content, ticket, key="ticketCreated"),
        menu_content.render(content, "conversationEnd"),
    ]
